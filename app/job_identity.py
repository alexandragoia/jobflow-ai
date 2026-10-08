from sqlalchemy import select
from .models import JobAlias, JobFeedback

def canonical_job_id(session, job_id):
    visited = set()
    while job_id not in visited:
        visited.add(job_id)
        alias = session.get(JobAlias, job_id)
        if alias is None:
            break
        job_id = alias.canonical_job_id
    return job_id

def preserve_duplicate_feedback(session, duplicate_id, retained_id):
    alias = session.get(JobAlias, duplicate_id)
    if alias is None:
        session.add(JobAlias(alias_job_id=duplicate_id, canonical_job_id=retained_id))
    else:
        alias.canonical_job_id = retained_id
    for child in session.scalars(select(JobAlias).where(JobAlias.canonical_job_id == duplicate_id)):
        child.canonical_job_id = retained_id
    old = session.scalar(select(JobFeedback).where(JobFeedback.job_id == duplicate_id))
    target = session.scalar(select(JobFeedback).where(JobFeedback.job_id == retained_id))
    if old is None:
        return
    if target is None:
        old.job_id = retained_id
        return
    target.saved = target.saved or old.saved
    if old.interest_note and (not target.interest_note or old.updated_at > target.updated_at):
        target.interest_note = old.interest_note
    target.interest_conditional = bool(target.interest_conditional or old.interest_conditional)
    if old.disposition != "none" and (target.disposition == "none" or old.updated_at > target.updated_at):
        target.disposition, target.liked, target.reason, target.note = old.disposition, old.liked, old.reason, old.note
    target.updated_at = max(target.updated_at, old.updated_at)
    session.delete(old)
