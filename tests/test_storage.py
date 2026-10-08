import json
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
import httpx
from sqlalchemy import create_engine, select, func, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.adzuna import search_adzuna, _check_daily_limit
from app.database import Base
from app.models import Job, JobSource, Source, SearchCache, ApiUsage, JobFeedback
from app.job_identity import canonical_job_id
from app.search_service import feedback_json
from app.migrations import migrate
from app.schemas import SearchParams
from app.sources import seed_sources
from app.deduplication import deduplicate_search_results

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.session=Session(self.engine,autoflush=False)
        seed_sources(self.session)
    def tearDown(self):self.session.close();self.engine.dispose()
    def response(self,payload):
        return httpx.Response(200,json=payload,request=httpx.Request('GET','https://api.adzuna.com/test'))
    def search(self,payload):
        with patch.dict(os.environ,{'ADZUNA_APP_ID':'fixture-id','ADZUNA_APP_KEY':'fixture-key'}),patch('app.adzuna.httpx.get',return_value=self.response(payload)) as request:
            result=search_adzuna(self.session,SearchParams(keywords=['Bürohilfe']))
        return result,request.call_count
    def test_cached_query_and_duplicate_source_id_are_safe(self):
        raw={'id':'same-id','title':'Bürohilfe','description':'Büroarbeiten','redirect_url':'https://www.adzuna.de/details/1'}
        result,calls=self.search({'count':2,'results':[raw,raw]})
        self.assertEqual(calls,1)
        self.assertEqual(result[0][0].id,result[0][1].id)
        self.assertEqual(self.session.scalar(select(func.count(JobSource.id))),1)
        result,calls=self.search({'count':999,'results':[]})
        self.assertEqual(calls,0);self.assertEqual(result[1],2)
        self.assertEqual(self.session.scalar(select(func.count(ApiUsage.id))),1)
    def test_today_request_and_role_anchors(self):
        from app.adzuna import fetch_adzuna_payload
        with patch.dict(os.environ,{'ADZUNA_APP_ID':'fixture-id','ADZUNA_APP_KEY':'fixture-key'}),patch('app.adzuna.httpx.get',return_value=self.response({'count':0,'results':[]})) as request:
            fetch_adzuna_payload(self.session,SearchParams(keywords=['Bürokraft Quereinsteiger','Teamleiter Housekeeping'], max_age_days=0))
        params=request.call_args.kwargs['params']
        self.assertEqual(params['max_days_old'],1)
        self.assertEqual(params['results_per_page'],50)
        self.assertNotIn('quereinsteiger',params['what_or'])
        self.assertNotIn('teamleiter',params['what_or'])
        self.assertIn('buerokraft',params['what_or'])
    def test_source_id_updates_and_canonical_url_merge(self):
        raw={'id':'id-1','title':'Bürohilfe','description':'Büroarbeiten','redirect_url':'https://www.adzuna.de/details/1?utm_source=a'}
        result,_=self.search({'count':1,'results':[raw]});identity=result[0][0].id
        cache=self.session.scalar(select(SearchCache));cache.created_at=datetime.utcnow()-timedelta(hours=1);self.session.commit()
        result,_=self.search({'count':1,'results':[{**raw,'description':'Büroarbeiten und Datenpflege'}]})
        self.assertEqual(result[0][0].id,identity)
        cache.created_at=datetime.utcnow()-timedelta(hours=1);self.session.commit()
        result,_=self.search({'count':1,'results':[{**raw,'id':'id-2','redirect_url':'https://www.adzuna.de/details/1?utm_source=b'}]})
        self.assertEqual(result[0][0].id,identity)
        self.assertEqual(self.session.scalar(select(func.count(Job.id))),1)
        self.assertEqual(self.session.scalar(select(func.count(JobSource.id))),2)
    def test_rate_limits_across_time_windows(self):
        source=self.session.scalar(select(Source).where(Source.name=='Adzuna'))
        for age,count in [(timedelta(seconds=10),20),(timedelta(hours=1),240),(timedelta(days=2),950),(timedelta(days=20),2400)]:
            self.session.execute(text('DELETE FROM api_usage'))
            self.session.add_all([ApiUsage(source_id=source.id,endpoint='fixture',called_at=datetime.utcnow()-age) for _ in range(count)])
            self.session.commit()
            with self.assertRaises(RuntimeError):_check_daily_limit(self.session,source.id)
    def test_medium_merge_preserves_urls_from_both_sources(self):
        common=dict(title='Bürohilfe',company_raw='Example',company_normalized='example',location_text='Dortmund',date_posted=datetime.utcnow(),description_text='Dokumentation und Büroarbeiten.')
        a=Job(content_hash='hash-a',**common);b=Job(content_hash='hash-b',**common)
        self.session.add_all([a,b]);self.session.flush()
        self.session.add(JobFeedback(job_id=b.id,liked=True,disposition='interested',saved=True,note='Mi nota'))
        self.session.flush()
        adzuna=self.session.scalar(select(Source).where(Source.name=='Adzuna'))
        external=self.session.scalar(select(Source).where(Source.name=='Indeed'))
        self.session.add_all([JobSource(job_id=a.id,source_id=adzuna.id,source_job_id='a',original_url='https://www.adzuna.de/details/a'),JobSource(job_id=b.id,source_id=external.id,source_job_id='b',original_url='https://de.indeed.com/viewjob?jk=b')]);self.session.flush()
        jobs,_=deduplicate_search_results([a,b],self.session)
        self.assertEqual(len(jobs),1)
        self.assertEqual(self.session.scalar(select(func.count(JobSource.id)).where(JobSource.job_id==a.id)),2)
        self.assertEqual(canonical_job_id(self.session,b.id),a.id)
        self.assertTrue(feedback_json(self.session,b.id)['saved'])
        self.assertEqual(feedback_json(self.session,a.id)['disposition'],'interested')
    def test_new_repost_detects_older_stored_offer(self):
        common=dict(title='Bürohilfe',company_raw='Example',company_normalized='example',location_text='Dortmund',description_text='Dokumentation und Büroarbeiten.')
        past=Job(content_hash='hash-old',date_posted=datetime.utcnow()-timedelta(days=20),**common)
        current=Job(content_hash='hash-new',date_posted=datetime.utcnow(),**common)
        self.session.add_all([past,current]);self.session.flush()
        jobs,reposts=deduplicate_search_results([current],self.session)
        self.assertTrue(reposts[current.id]);self.assertTrue(current.possible_repost);self.assertEqual(len(jobs),1)

class OldSchemaTests(unittest.TestCase):
    def test_additive_migration_preserves_old_feedback(self):
        engine=create_engine('sqlite://')
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE jobs (id INTEGER PRIMARY KEY)'))
            connection.execute(text('CREATE TABLE searches (id INTEGER PRIMARY KEY)'))
            connection.execute(text('CREATE TABLE search_results (id INTEGER PRIMARY KEY)'))
            connection.execute(text('CREATE TABLE job_feedback (id INTEGER PRIMARY KEY, liked BOOLEAN)'))
            connection.execute(text('INSERT INTO job_feedback (id,liked) VALUES (1,1),(2,0)'))
        migrate(engine);migrate(engine)
        with engine.connect() as connection:
            rows=connection.execute(text('SELECT disposition FROM job_feedback ORDER BY id')).scalars().all()
            self.assertEqual(rows,['interested','rejected'])
        engine.dispose()

if __name__=='__main__':unittest.main()
