import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select, func, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main
from app.adzuna import normalize_job, search_adzuna, _check_daily_limit
from app.database import Base, get_session
from app.deduplication import deduplicate_search_results
from app.filtering import evaluate_hard_filters
from app.llm_service import local_analysis, analyze_job, validate_evidence, _openai_analysis
from app.models import Job, JobSource, Source, ApiUsage, AnalysisCache
from app.schemas import SearchParams, JobAnalysis, SettingsPayload
from app.scoring import score_job
from app.settings_service import DEFAULT_RULES, DEFAULT_WEIGHTS
from app.security import safe_url, canonical_url
from app.migrations import migrate

FIXTURES = json.loads((Path(__file__).resolve().parents[1]/"fixtures"/"jobs.json").read_text(encoding="utf-8"))

def fixture_job(raw, identity=1):
    data = normalize_job({**raw,"company":{"display_name":"Empresa de ejemplo"},"location":{"display_name":"Dortmund"},
        "created":datetime.utcnow().isoformat()+"Z","redirect_url":"https://www.adzuna.de/details/"+raw.get("id","fixture")})
    data.pop("original_url")
    data.pop("source_job_id")
    return Job(id=identity, **data)

class RulesTests(unittest.TestCase):
    def test_a_to_f_realistic_fixtures(self):
        for i, raw in enumerate(FIXTURES, 1):
            with self.subTest(raw["id"]):
                job = fixture_job(raw, i)
                result = evaluate_hard_filters(job,SearchParams(keywords=["Bürohilfe"]))
                self.assertEqual(result["status"],raw["expected_status"])
                if "expected_reason" in raw:self.assertEqual(result["excluded_reason"],raw["expected_reason"])
                analysis = local_analysis(job).model_dump()
                scored = score_job(job,["Bürohilfe"],result["flags"],analysis,result["status"]=="excluded")
                if "expected_band" in raw:
                    # These care/administration roles do not match this Bürohilfe-only query.
                    expected = 'Poco ajuste' if raw['id'] in ('fixture-d', 'fixture-e') else raw['expected_band']
                    self.assertEqual(scored["band"], expected)
                if result["status"]=="excluded":self.assertIsNone(scored["score"])

    def test_unknown_distance_date_and_employment_are_kept(self):
        job = fixture_job({"title":"Bürohilfe","description":""})
        job.date_posted=None
        result = evaluate_hard_filters(job, SearchParams(keywords=["x"],radius_km=0,employment_types=["full_time"]))
        self.assertEqual(result["status"],"new")
        job.distance_status,job.distance_km="approximate",15
        self.assertEqual(evaluate_hard_filters(job,SearchParams(keywords=["x"],radius_km=0))["status"],"new")
        job.distance_status="exact"
        self.assertEqual(evaluate_hard_filters(job,SearchParams(keywords=["x"],radius_km=0))["excluded_reason"],"OUTSIDE_RADIUS")

    def test_each_hard_filter_negations_qualifications_and_dates(self):
        cases=[("Nachtschicht erforderlich","NIGHT_SHIFT"),("Dreischicht","THREE_SHIFT"),
            ("Deutschkenntnisse auf Niveau C1 zwingend erforderlich","GERMAN_TOO_HIGH"),("Kaltakquise","CALL_CENTER_SALES")]
        for description,reason in cases:
            job=fixture_job({"title":"Bürohilfe","description":description})
            result=evaluate_hard_filters(job,SearchParams(keywords=["x"]))
            self.assertEqual(result["excluded_reason"],reason)
            self.assertIn(description,result["evidence"][0])
        for description in ["Keine Nachtschicht. Ausbildung wünschenswert.","Sehr gute Deutschkenntnisse.","Deutsch C1 nicht erforderlich."]:
            self.assertEqual(evaluate_hard_filters(fixture_job({"title":"Bürohilfe","description":description}),SearchParams(keywords=["x"]))["status"],"new")
        job=fixture_job({"title":"Bürohilfe","description":"Keine Nachtschicht. Nachtschicht erforderlich."})
        self.assertEqual(evaluate_hard_filters(job,SearchParams(keywords=["x"]))["excluded_reason"],"NIGHT_SHIFT")
        job=fixture_job({"title":"Bürohilfe","description":"Abgeschlossene Ausbildung erforderlich."})
        result=evaluate_hard_filters(job,SearchParams(keywords=["x"]))
        self.assertEqual(result["status"],"new");self.assertIn("POSSIBLE_QUALIFICATION_MISMATCH",result["flags"])
        job.date_posted=datetime.utcnow()-timedelta(days=20)
        self.assertEqual(evaluate_hard_filters(job,SearchParams(keywords=["x"]))["excluded_reason"],"TOO_OLD")

    def test_rule_switch_and_keyword_limits(self):
        job=fixture_job({"title":"Bürohilfe","description":"Nachtschicht"})
        with patch("app.filtering.preferences",return_value={"hard_rules":{**DEFAULT_RULES,"night_shift":False}}):
            self.assertEqual(evaluate_hard_filters(job,SearchParams(keywords=["x"]))["status"],"new")
        for radius in [-1,11,1.5]:
            with self.assertRaises(ValidationError):SearchParams(keywords=["x"],radius_km=radius)
        with self.assertRaises(ValidationError):SearchParams(keywords=[str(i) for i in range(21)])

    def test_dedup_reposts_and_url_validation(self):
        a=fixture_job(FIXTURES[0],1);b=fixture_job(FIXTURES[0],2)
        a.date_posted -= timedelta(days=1)
        jobs,reposts=deduplicate_search_results([a,a,b])
        self.assertEqual(len(jobs),2);self.assertTrue(reposts[1]);self.assertTrue(reposts[2])
        for url in ["javascript:alert(1)","file:///etc/passwd","https://user:secret@example.com","https://example.com\n"]:
            self.assertIsNone(safe_url(url))
        self.assertEqual(canonical_url("https://example.com/job/1?utm_source=a"),canonical_url("https://example.com/job/1"))

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
        self.factory=sessionmaker(bind=self.engine,autoflush=False)
        self.patches=[patch.object(main,"engine",self.engine),patch.object(main,"SessionLocal",self.factory)]
        for p in self.patches:p.start()
        def session_dependency():
            with self.factory() as session:yield session
        main.app.dependency_overrides[get_session]=session_dependency
        self.client_context=TestClient(main.app)
        self.client=self.client_context.__enter__()
    def tearDown(self):
        self.client_context.__exit__(None,None,None)
        main.app.dependency_overrides.clear()
        for p in self.patches:p.stop()
        self.engine.dispose()
    def mock_search(self,session,params):
        source=session.scalar(select(Source).where(Source.name=="Adzuna"))
        jobs=[]
        for index, raw in enumerate(FIXTURES,1):
            job=fixture_job(raw,index);session.add(job);session.flush()
            session.add(JobSource(job_id=job.id,source_id=source.id,source_job_id=raw["id"],original_url="https://www.adzuna.de/details/"+raw["id"]))
            jobs.append(job)
        session.commit();return jobs,6
    def perform_search(self):
        with patch("app.search_service.search_adzuna",side_effect=self.mock_search),patch("app.llm_service._openai_analysis",side_effect=AssertionError("No real AI")):
            response=self.client.post('/api/search',json={"keywords":["Bürohilfe"]})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()
    def test_full_flow_search_feedback_history_library(self):
        result=self.perform_search()
        self.assertEqual(len(result['jobs']),6)
        self.assertEqual(sum(job['status']=='excluded' for job in result['jobs']),2)
        self.assertTrue(all(job['distance_km'] is None for job in result['jobs']))
        identity=result['jobs'][0]['id']
        for payload in [{"action":"saved"},{"action":"interested"},{"action":"rejected","reason":"Demasiado teléfono","note":"Revisado por mí"}]:
            self.assertEqual(self.client.put(f'/api/jobs/{identity}/feedback',json=payload).status_code,200)
        self.assertEqual(len(self.client.get('/api/jobs?kind=saved').json()['jobs']),1)
        self.assertEqual(len(self.client.get('/api/jobs?kind=rejected').json()['jobs']),1)
        self.assertEqual(self.client.get('/api/feedback/summary').json()[0]['count'],1)
        history=self.client.get('/api/history').json();self.assertEqual(history[0]['stored'],6)
        self.assertEqual(len(self.client.get('/api/history/'+str(result['search_id'])).json()['jobs']),6)
        with self.factory() as session:self.assertEqual(session.scalar(select(func.count(AnalysisCache.id))),4)
    def test_source_failure_retains_fallback_and_history(self):
        with patch('app.search_service.search_adzuna',side_effect=RuntimeError('Fuente no disponible')):
            response=self.client.post('/api/search',json={"keywords":["Bürohilfe"]})
        self.assertEqual(response.status_code,200)
        data=response.json();self.assertEqual(data['jobs'],[]);self.assertEqual(data['messages'][0]['status'],'failed');self.assertGreater(len(data['external_links']),0)
    def test_new_rejection_reasons_persist(self):
        result=self.perform_search()
        identity=result['jobs'][0]['id']
        for reason in ['No tengo la experiencia necesaria', 'No tiene nada que ver con lo que estoy buscando']:
            response=self.client.put(f'/api/jobs/{identity}/feedback',json={'action':'rejected','reason':reason})
            self.assertEqual(response.status_code,200)
            stored=self.client.get('/api/jobs?kind=rejected').json()['jobs']
            self.assertEqual(stored[0]['feedback']['reason'],reason)
    def test_today_search_and_snapshot_share_local_date(self):
        def today_search(session,params):
            jobs,total=self.mock_search(session,params)
            for offer in jobs:
                offer.date_posted=datetime(2026,10,7,22,10)
            session.commit()
            return jobs,total
        from datetime import timezone
        with patch('app.search_service.search_adzuna',side_effect=today_search),patch('app.filtering.datetime') as clock:
            clock.now.return_value=datetime(2026,10,7,22,30,tzinfo=timezone.utc)
            response=self.client.post('/api/search',json={'keywords':['Bürohilfe'],'max_age_days':0})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['jobs'][0]['date_posted'],'2026-10-08')
        self.assertNotIn('TOO_OLD',[offer['excluded_reason'] for offer in response.json()['jobs']])
    def test_external_only_does_not_call_api_and_expansion_is_visible(self):
        with patch('app.search_service.search_adzuna',side_effect=AssertionError('Must not query')):
            data=self.client.post('/api/search',json={"keywords":["Bürohilfe"],"sources":["Indeed"]}).json()
        self.assertEqual(data['jobs'],[]);self.assertEqual(data['messages'][0]['status'],'external')
        suggestions=self.client.post('/api/keywords/expand',json={"keywords":["Bürohilfe"]}).json()
        self.assertEqual(suggestions['suggestions'][0]['from'],'Bürohilfe')
    def test_local_security_and_input_validation(self):
        self.assertEqual(self.client.get('/').status_code,200)
        self.assertEqual(self.client.get('/static/app.js').status_code,200)
        self.assertEqual(self.client.post('/api/search',json={"keywords":["x"],"radius_km":11}).status_code,422)
        self.assertEqual(self.client.post('/api/search',json={"keywords":["x"]},headers={"Origin":"https://evil.example"}).status_code,403)
        self.assertEqual(self.client.get('/',headers={"Host":"evil.example"}).status_code,400)
        self.assertNotIn('ADZUNA_APP_KEY',self.client.get('/api/settings').text)
    def test_llm_json_and_evidence_validation_cache_and_failure(self):
        job=fixture_job(FIXTURES[5],99)
        analysis=local_analysis(job)
        with self.assertRaises(ValidationError):
            JobAnalysis.model_validate({**analysis.model_dump(),"quereinsteiger":{"value":"yes","origin":"stated","evidence_quote":""}})
        analysis.quereinsteiger.evidence_quote='This quote is invented'
        with self.assertRaises(ValueError):validate_evidence(analysis,job)
        good=local_analysis(job).model_dump()
        response=httpx.Response(200,json={"status":"completed","output":[{"content":[{"type":"output_text","text":json.dumps(good)}]}]},request=httpx.Request('POST','https://api.openai.com/v1/responses'))
        with patch.dict(os.environ,{"OPENAI_API_KEY":"fixture-key"}),patch('app.llm_service.httpx.post',return_value=response) as request:
            self.assertEqual(_openai_analysis(job,'fixture-model').quereinsteiger.value,'yes')
            self.assertIn('UNTRUSTED DATA',request.call_args.kwargs['json']['instructions'])
            self.assertIn('Ignore all previous instructions',request.call_args.kwargs['json']['input'])
        with self.factory() as session:
            session.add(job);session.commit()
            with patch.dict(os.environ,{"OPENAI_API_KEY":"fixture-key"}),patch('app.llm_service._openai_analysis',side_effect=ValueError('Invalid JSON')):
                result=analyze_job(session,job,True)
            self.assertEqual(result['status'],'analysis_failed');self.assertEqual(result['method'],'local')
    def test_existing_database_migration_is_idempotent(self):
        with self.engine.begin() as connection:connection.execute(text("INSERT INTO job_feedback (job_id,liked,updated_at,disposition,saved,interest_conditional) VALUES (999,1,'2026-01-01','interested',1,0)"))
        migrate(self.engine);migrate(self.engine)
        with self.factory() as session:self.assertEqual(session.execute(text('SELECT COUNT(*) FROM job_feedback')).scalar(),1)

class SettingsTests(unittest.TestCase):
    def test_settings_roundtrip_in_temporary_config(self):
        import app.settings_service as service
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'worktmp') as directory:
            root=Path(directory);(root/'config').mkdir()
            (root/'config'/'preferences.yaml').write_text('location: {}',encoding='utf-8')
            (root/'config'/'qualifications.yaml').write_text('{}',encoding='utf-8')
            def load(name):
                import yaml
                return yaml.safe_load((root/'config'/name).read_text(encoding='utf-8')) or {}
            with patch.object(service,'ROOT',root),patch.object(service,'load_yaml',side_effect=load):
                payload=SettingsPayload(radius_km=7,max_age_days=14,hard_rules=DEFAULT_RULES,weights=DEFAULT_WEIGHTS)
                self.assertEqual(service.save_settings(payload)['radius_km'],7)
                payload.hard_rules={**DEFAULT_RULES,'mandatory_qualification':True}
                with self.assertRaises(ValueError):service.save_settings(payload)

if __name__=='__main__':unittest.main()
