import json
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from .adzuna import search_adzuna
from .deduplication import deduplicate_search_results
from .filtering import evaluate_hard_filters
from .llm_service import analyze_job
from .models import JobFeedback, JobSource, Search, SearchResult, Source, SourceRun
from .scoring import score_job
from .settings_service import preferences
from .security import safe_url
from .sources import source_link
from .job_identity import canonical_job_id

logger = logging.getLogger("jobflow")

def feedback_json(session, job_id):
    job_id = canonical_job_id(session, job_id)
    row = session.scalar(select(JobFeedback).where(JobFeedback.job_id == job_id))
    return {"disposition": row.disposition, "saved": row.saved, "reason": row.reason, "note": row.note,
            "interest_note": row.interest_note, "interest_conditional": row.interest_conditional} if row else {
        "disposition": "none", "saved": False, "reason": None, "note": None,
        "interest_note": None, "interest_conditional": False}

def already_reviewed(feedback):
    return feedback['saved'] or feedback['disposition'] in ('interested', 'rejected')

def snapshot(session, job, params, filtering, repost, analysis):
    ranking = score_job(job, params.keywords, filtering["flags"], analysis["analysis"], filtering["status"] == "excluded", filtering.get("qualification_evidence", []))
    links = session.execute(select(JobSource.original_url, Source.name).join(Source, Source.id == JobSource.source_id)
                            .where(JobSource.job_id == job.id)).all()
    urls = [{"name": name, "url": safe_url(url)} for url, name in links if safe_url(url)]
    return {"id": job.id, "title": job.title, "company": job.company_raw, "location": job.location_text,
        "distance_km": job.distance_km if job.distance_status == "exact" else None,
        "distance_estimate_km": job.distance_km if job.distance_status == "approximate" else None,
        "distance_status": job.distance_status,
        "date_posted": ((job.date_posted.replace(tzinfo=timezone.utc) if job.date_posted.tzinfo is None else job.date_posted)
                        .astimezone(ZoneInfo('Europe/Berlin')).date().isoformat()) if job.date_posted else None,
        "date_precision": job.date_precision, "date_updated": job.date_updated.isoformat() if job.date_updated else None,
        "date_posted_at": (job.date_posted.replace(tzinfo=timezone.utc) if job.date_posted.tzinfo is None else job.date_posted).isoformat() if job.date_posted else None,
        "retrieved_at": job.last_seen_at.isoformat() if job.last_seen_at else None,
        "employment_type": job.employment_type, "description": job.description_text,
        "description_is_partial": job.description_is_partial, "urls": urls, "url": urls[0]["url"] if urls else None,
        "found_on_sources": len(set(name for _, name in links)),
        "status": filtering["status"], "excluded_reason": filtering["excluded_reason"],
        "filter_evidence": filtering["evidence"], "flags": filtering["flags"], "possible_repost": repost,
        "analysis": analysis["analysis"], "analysis_method": analysis["method"], "analysis_status": analysis["status"],
        "analysis_warning": analysis["warning"], "analysis_error_code": analysis.get("error_code"), **ranking}

def empty_analysis():
    from .schemas import JobAnalysis
    return {**{name: {"value": "unknown", "origin": "inferred", "evidence_quote": ""}
               for name in JobAnalysis.model_fields if name != "confidence"}, "confidence": "low"}

def result_order(row):
    return (row['status'] == 'excluded',
            {'title': 0, 'description': 1, 'unconfirmed': 2}.get(row.get('relevance', {}).get('level'), 1),
            -(row['score'] or 0))

def execute_search(session, params):
    logger.info("search_started radius=%s age=%s", params.radius_km, params.max_age_days)
    search = Search(keywords_json=json.dumps(params.keywords, ensure_ascii=False), radius_km=params.radius_km,
                    max_age_days=params.max_age_days, params_json=params.model_dump_json())
    session.add(search)
    session.commit()
    search_id = search.id
    messages, jobs, total = [], [], 0
    external = []
    catalog = {s.name: s for s in session.scalars(select(Source)).all()}
    for name in params.sources:
        source = catalog[name]
        if name != "Adzuna":
            link = source_link(name, params)
            if link:
                external.append(link)
            messages.append({"source": name, "status": "external", "message": "Búsqueda externa; ofertas no importadas."})
            continue
        run = SourceRun(search_id=search_id, source_id=source.id)
        session.add(run)
        session.commit()
        run_id = run.id
        started = datetime.utcnow()
        try:
            fetched, count = search_adzuna(session, params)
            jobs.extend(fetched)
            total += count
            run.ok, run.jobs_returned = True, len(fetched)
            messages.append({"source": name, "status": "ok", "message": f"{len(fetched)} ofertas recibidas; máximo 50 por búsqueda. Se prioriza la coincidencia con el título."})
            logger.info("source_queried source=%s jobs=%s", name, len(fetched))
        except Exception as exc:
            session.rollback()
            run = session.get(SourceRun, run_id)
            run.ok, run.error_message = False, type(exc).__name__
            source = session.get(Source, source.id)
            source.last_error = type(exc).__name__
            # Display only deliberate connector messages, never arbitrary exception/request text.
            text = str(exc) if type(exc) is RuntimeError else "Error temporal al consultar la fuente."
            messages.append({"source": name, "status": "failed", "message": text})
            logger.warning("source_failed source=%s type=%s", name, type(exc).__name__)
        run.duration_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
        session.commit()
    raw_count = len(jobs)
    jobs, reposts = deduplicate_search_results(jobs, session)
    logger.info("duplicates_merged count=%s", raw_count - len(jobs))
    use_ai = params.use_ai and preferences()["ai"].get("enabled", False)
    if params.use_ai and not use_ai:
        messages.append({"source": "IA", "status": "info", "message": "Activa el análisis de IA en Ajustes para usarlo. Se aplican reglas locales."})
    output = []
    reviewed_count = 0
    for job in jobs:
        feedback = feedback_json(session, job.id)
        if already_reviewed(feedback):
            reviewed_count += 1
            continue
        filtering = evaluate_hard_filters(job, params)
        analysis = analyze_job(session, job, use_ai) if filtering["status"] != "excluded" else {
            "analysis": empty_analysis(), "method": "none", "status": "skipped", "warning": None}
        row = snapshot(session, job, params, filtering, reposts.get(job.id, False), analysis)
        saved = SearchResult(search_id=search_id, job_id=job.id, status=row["status"], excluded_reason=row["excluded_reason"],
            filter_evidence_json=json.dumps(row["filter_evidence"], ensure_ascii=False), possible_repost=row["possible_repost"],
            score=row["score"] if row["score"] is not None else 0, score_confidence=row["confidence"],
            score_factors_json=json.dumps(row["factors"], ensure_ascii=False), result_json=json.dumps(row, ensure_ascii=False))
        session.add(saved)
        row["feedback"] = feedback
        output.append(row)
        if row["status"] == "excluded":
            logger.info("job_excluded job=%s reason=%s", job.id, row["excluded_reason"])
    limited = [row for row in output if row['analysis_status'] == 'daily_limit']
    if limited:
        messages.append({'source': 'IA', 'status': 'info',
                         'message': f"{len(limited)} ofertas analizadas con reglas locales. " + limited[0]['analysis_warning']})
    if reviewed_count:
        messages.append({'source': 'Mis ofertas', 'status': 'info',
                         'message': f'{reviewed_count} ofertas ya guardadas o valoradas no se repiten. Puedes revisarlas en Mis ofertas.'})
    search = session.get(Search, search_id)
    search.total_found, search.messages_json = total, json.dumps(messages, ensure_ascii=False)
    session.commit()
    output.sort(key=result_order)
    # Always offer verified portal links even when the automatic source fails.
    if not external:
        external = [source_link(name, params) for name in ("Bundesagentur für Arbeit / Jobsuche", "Indeed", "StepStone")]
    return {"search_id": search_id, "jobs": output, "total_estimated": total, "source": "Adzuna",
            "messages": messages, "external_links": [x for x in external if x],
            "already_reviewed_count": reviewed_count}

def stored_result(session, row):
    result = json.loads(row.result_json)
    if not result:
        from .models import Job
        from .schemas import SearchParams
        job, search = session.get(Job, row.job_id), session.get(Search, row.search_id)
        if not job or not search:
            return None
        params = SearchParams(keywords=json.loads(search.keywords_json), radius_km=search.radius_km, max_age_days=search.max_age_days)
        filtering = evaluate_hard_filters(job, params)
        filtering["status"], filtering["excluded_reason"] = row.status, row.excluded_reason
        analysis = analyze_job(session, job, False) if row.status != "excluded" else {
            "analysis": empty_analysis(), "method": "none", "status": "skipped", "warning": None}
        result = snapshot(session, job, params, filtering, row.possible_repost, analysis)
    result["id"] = canonical_job_id(session, row.job_id)
    result["feedback"] = feedback_json(session, row.job_id)
    return result
