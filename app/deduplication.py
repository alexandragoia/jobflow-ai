from difflib import SequenceMatcher
import re

from .models import Job
from .models import JobSource
from sqlalchemy import select
from .job_identity import preserve_duplicate_feedback


def _clean(value: str | None) -> str:
    return re.sub(r"[^\w]+", " ", (value or "").casefold()).strip()


def _description_similarity(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _clean(a), _clean(b)).ratio()


def deduplicate_search_results(jobs: list[Job], session=None) -> tuple[list[Job], dict[int, bool]]:
    """Remove exact repeats from a search and flag, but do not merge, likely reposts."""
    unique: list[Job] = []
    seen_ids: set[int] = set()
    possible_repost: dict[int, bool] = {job.id: True for job in jobs if getattr(job, "possible_repost", False)}
    for job in jobs:
        if job.id in seen_ids:
            continue
        seen_ids.add(job.id)
        unique.append(job)

    merged = []
    for current in unique:
        duplicate = False
        if session and current.company_normalized and current.location_text and current.date_posted:
            candidates = session.scalars(select(Job).where(Job.id != current.id, Job.company_normalized == current.company_normalized)).all()
            for past in candidates:
                if past.date_posted and past.date_posted.date() < current.date_posted.date() and _clean(past.title) == _clean(current.title) and _clean(past.location_text) == _clean(current.location_text) and _description_similarity(past.description_text, current.description_text) >= 0.78:
                    current.possible_repost = True
                    possible_repost[current.id] = True
                    break
        for earlier in merged:
            same_core = (
                bool(current.company_raw and earlier.company_raw and current.location_text and earlier.location_text)
                and
                _clean(current.title) == _clean(earlier.title)
                and _clean(current.company_normalized or current.company_raw) == _clean(earlier.company_normalized or earlier.company_raw)
                and _clean(current.location_text) == _clean(earlier.location_text)
            )
            similarity = _description_similarity(current.description_text, earlier.description_text)
            same_date = current.date_posted and earlier.date_posted and current.date_posted.date() == earlier.date_posted.date()
            if same_core and same_date and similarity >= 0.9:
                if session:
                    preserve_duplicate_feedback(session, current.id, earlier.id)
                    for link in session.scalars(select(JobSource).where(JobSource.job_id == current.id)):
                        link.job_id = earlier.id
                    session.flush()
                duplicate = True
                break
            if same_core and current.date_posted and earlier.date_posted and not same_date and similarity >= 0.78:
                possible_repost[current.id] = True
                possible_repost[earlier.id] = True
        if not duplicate:
            merged.append(current)
    return merged, possible_repost
