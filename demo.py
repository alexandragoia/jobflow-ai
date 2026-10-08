"""Portfolio demo with synthetic jobs, isolated storage and no paid API calls."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'worktmp' / 'demo'
DATA.mkdir(parents=True, exist_ok=True)
os.environ.update({'JOBFLOW_DATA_DIR': str(DATA), 'JOBFLOW_DATABASE_PATH': str(DATA / 'demo.db'),
                   'JOBFLOW_ONLINE': '0', 'JOBFLOW_DEMO': '1',
                   'OPENAI_API_KEY': '', 'ADZUNA_APP_ID': '', 'ADZUNA_APP_KEY': ''})
os.environ.pop('SSLKEYLOGFILE', None)

import uvicorn
from sqlalchemy import select
from app.adzuna import normalize_job
import app.main as main
import app.search_service as service
from app.models import Job, JobSource, Source

ROWS = json.loads((ROOT / 'fixtures' / 'demo_jobs.json').read_text(encoding='utf-8'))


def synthetic_search(session, params):
    source = session.scalar(select(Source).where(Source.name == 'Adzuna'))
    jobs = []
    for index, row in enumerate(ROWS):
        raw = {**row, 'created': (datetime.now(timezone.utc)-timedelta(hours=index*3)).isoformat(),
               'company': {'display_name': 'Empresa ficticia · Demo'},
               'location': {'display_name': 'Dortmund · ubicación de ejemplo'}}
        normalized = normalize_job(raw)
        identity = normalized.pop('source_job_id')
        normalized.pop('original_url')
        job = session.scalar(select(Job).where(Job.content_hash == normalized['content_hash']))
        if job is None:
            job = Job(**normalized)
            session.add(job)
            session.flush()
            session.add(JobSource(job_id=job.id, source_id=source.id, source_job_id=identity, original_url=None))
        else:
            job.date_posted = normalized['date_posted']
            job.last_seen_at = datetime.now(timezone.utc).replace(tzinfo=None)
        jobs.append(job)
    session.commit()
    return jobs, len(jobs)


service.search_adzuna = synthetic_search
if __name__ == '__main__':
    print('JobFlow DEMO: http://127.0.0.1:8799/ · Solo ofertas ficticias, sin consultas de pago.')
    uvicorn.run(main.app, host='127.0.0.1', port=8799, log_level='warning')
