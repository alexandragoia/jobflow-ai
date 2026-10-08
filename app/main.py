import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from threading import Lock
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import ROOT, SYNONYMS
from .database import Base, engine, get_session, SessionLocal
from .filtering import evaluate_hard_filters
from .llm_service import analyze_job, daily_usage, AnalysisError, PROMPT_VERSION
from .migrations import migrate, backup_database
from .models import Job, JobFeedback, JobAlias, Search, SearchResult, Source, ApiUsage, AnalysisCache
from .schemas import SearchParams, SettingsPayload, FeedbackPayload, LearningAction, AiPreviewPayload
from .learning import suggestions as learning_suggestions, decide as learning_decide, undo as learning_undo
from .search_service import execute_search, feedback_json, stored_result, snapshot, result_order
from .settings_service import public_settings, save_settings, preferences
from .sources import seed_sources, source_link
from .job_identity import canonical_job_id
from .web_auth import access_response, install_auth, validate_online_config, online_enabled

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("jobflow")
search_lock = Lock()

@asynccontextmanager
async def lifespan(app):
    validate_online_config()
    backup_database(engine)
    Base.metadata.create_all(engine)
    migrate(engine)
    with SessionLocal() as session:
        seed_sources(session)
    yield

app = FastAPI(title="JobFlow AI", version="1.0.0", lifespan=lifespan,
              docs_url=None if online_enabled() else '/docs', redoc_url=None if online_enabled() else '/redoc')
allowed_hosts = ["127.0.0.1", "localhost", "testserver"]
if online_enabled():
    allowed_hosts += [host.strip() for host in os.getenv('JOBFLOW_ALLOWED_HOSTS', '').split(',') if host.strip()]
    if os.getenv('RENDER_EXTERNAL_HOSTNAME'):
        allowed_hosts.append(os.environ['RENDER_EXTERNAL_HOSTNAME'])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
install_auth(app)
app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")

@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    logger.error("request_failed type=%s", type(exc).__name__)
    return JSONResponse({"detail": "La aplicación no pudo completar la operación. Vuelve a intentarlo; tus ofertas guardadas se conservan."}, status_code=500)

@app.middleware("http")
async def local_security(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method in ("POST", "PUT", "DELETE") and origin:
        parsed = urlsplit(origin)
        if parsed.scheme not in ("http", "https") or parsed.netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Esta acción debe realizarse desde la página de JobFlow."}, status_code=403)
    if request.method in ('POST', 'PUT', 'DELETE') and request.headers.get('sec-fetch-site') == 'cross-site':
        return JSONResponse({'detail': 'Esta acción debe realizarse desde JobFlow.'}, status_code=403)
    denied = access_response(request)
    response = denied if denied is not None else await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    return response

@app.get("/")
def home():
    return FileResponse(ROOT / "frontend" / "index.html")

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0", "postcode": "44145"}

@app.get("/api/settings")
def settings():
    return public_settings()

@app.put("/api/settings")
def update_settings(payload: SettingsPayload):
    if not search_lock.acquire(blocking=False):
        raise HTTPException(409, "Espera a que termine la búsqueda o el análisis antes de cambiar los ajustes.")
    try:
        return save_settings(payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    finally:
        search_lock.release()

@app.get("/api/sources")
def sources(session: Session = Depends(get_session)):
    return [{"name": s.name, "status": s.status, "integration_type": s.integration_type, "enabled": s.enabled,
        "last_success": s.last_success.isoformat() if s.last_success else None, "last_error": s.last_error,
        "notes": s.notes, "external_link": source_link(s.name)} for s in session.scalars(select(Source).order_by(Source.name))]

@app.post("/api/keywords/expand")
def expand_keywords(params: SearchParams):
    present = {k.casefold() for k in params.keywords}
    suggestions = []
    for keyword in params.keywords:
        for key, values in SYNONYMS.items():
            if keyword.casefold() == key.casefold():
                for value in values:
                    if value.casefold() not in present and len(present) < 20:
                        suggestions.append({"term": value, "from": keyword})
                        present.add(value.casefold())
    return {"original": params.keywords, "suggestions": suggestions}

@app.post("/api/search")
def search(params: SearchParams, session: Session = Depends(get_session)):
    names = set(session.scalars(select(Source.name).where(Source.enabled == True)).all())
    if not params.sources or any(name not in names for name in params.sources):
        raise HTTPException(422, "Selecciona una fuente disponible.")
    params.sources = list(dict.fromkeys(params.sources))
    if not search_lock.acquire(blocking=False):
        raise HTTPException(409, "Ya hay una búsqueda o análisis en curso. Espera a que termine.")
    try:
        return execute_search(session, params)
    finally:
        search_lock.release()

@app.get("/api/history")
def history(session: Session = Depends(get_session)):
    rows = session.scalars(select(Search).order_by(Search.id.desc()).limit(100)).all()
    return [{"id": row.id, "created_at": row.created_at.isoformat(), "keywords": json.loads(row.keywords_json),
        "radius_km": row.radius_km, "max_age_days": row.max_age_days, "total_estimated": row.total_found,
        "stored": session.scalar(select(func.count(SearchResult.id)).where(SearchResult.search_id == row.id)) or 0} for row in rows]

@app.get("/api/history/{search_id}")
def history_results(search_id: int, session: Session = Depends(get_session)):
    search = session.get(Search, search_id)
    if not search:
        raise HTTPException(404, "No se encontró esa búsqueda.")
    jobs = [stored_result(session, row) for row in session.scalars(select(SearchResult).where(SearchResult.search_id == search_id))]
    jobs = [job for job in jobs if job]
    jobs.sort(key=result_order)
    params = SearchParams.model_validate_json(search.params_json) if search.params_json != "{}" else SearchParams(keywords=json.loads(search.keywords_json))
    return {"search_id": search_id, "jobs": jobs, "total_estimated": search.total_found,
        "messages": json.loads(search.messages_json), "external_links": [source_link(name, params) for name in ("Bundesagentur für Arbeit / Jobsuche", "Indeed", "StepStone")]}

@app.put("/api/jobs/{job_id}/feedback")
def feedback(job_id: int, payload: dict, session: Session = Depends(get_session)):
    job_id = canonical_job_id(session, job_id)
    if "liked" in payload and isinstance(payload["liked"], bool):
        payload = {"action": "interested" if payload["liked"] else "rejected"}
    try:
        data = FeedbackPayload.model_validate(payload)
    except ValidationError:
        raise HTTPException(422, "La valoración no es válida.") from None
    if not session.get(Job, job_id):
        raise HTTPException(404, "No se encontró esa oferta.")
    row = session.scalar(select(JobFeedback).where(JobFeedback.job_id == job_id))
    if row is None:
        row = JobFeedback(job_id=job_id, liked=False, disposition="none", saved=False)
        session.add(row)
    if data.interest_note is not None or data.interest_conditional is not None:
        if data.action not in ('saved', 'interested'):
            raise HTTPException(422, 'La explicación de interés solo se guarda con Me interesa o Guardar.')
        interest_note = data.interest_note.strip() if data.interest_note is not None else row.interest_note
        conditional = data.interest_conditional if data.interest_conditional is not None else bool(row.interest_conditional)
        if conditional and not interest_note:
            raise HTTPException(422, 'Explica la condición por la que te interesa esta oferta.')
        row.interest_note, row.interest_conditional = interest_note or None, conditional
    if data.action in ("saved", "unsaved"):
        row.saved = data.action == "saved"
    elif data.action == "clear":
        row.disposition, row.reason, row.note = "none", None, None
    else:
        row.disposition, row.liked = data.action, data.action == "interested"
        row.reason = data.reason if data.action == "rejected" else None
        row.note = data.note if data.action == "rejected" else None
    if not row.saved and row.disposition != 'interested':
        row.interest_note, row.interest_conditional = None, False
    row.updated_at = datetime.utcnow()
    session.commit()
    logger.info("feedback job=%s action=%s", job_id, data.action)
    return feedback_json(session, job_id)

@app.get("/api/jobs")
def library(kind: str = "saved", session: Session = Depends(get_session)):
    if kind not in ("saved", "interested", "rejected"):
        raise HTTPException(422, "Vista desconocida.")
    query = select(JobFeedback).where(JobFeedback.saved == True) if kind == "saved" else select(JobFeedback).where(JobFeedback.disposition == kind)
    jobs = []
    for feedback in session.scalars(query.order_by(JobFeedback.updated_at.desc()).limit(200)):
        identities = [feedback.job_id, *session.scalars(select(JobAlias.alias_job_id).where(JobAlias.canonical_job_id == feedback.job_id))]
        row = session.scalar(select(SearchResult).where(SearchResult.job_id.in_(identities)).order_by(SearchResult.id.desc()))
        if row:
            result = stored_result(session, row)
            if result:
                jobs.append(result)
    counts = {'saved': 0, 'interested': 0, 'rejected': 0}
    for saved, disposition, total in session.execute(
            select(JobFeedback.saved, JobFeedback.disposition, func.count(JobFeedback.id))
            .group_by(JobFeedback.saved, JobFeedback.disposition)):
        if saved:
            counts['saved'] += total
        if disposition in ('interested', 'rejected'):
            counts[disposition] += total
    return {"jobs": jobs, "counts": counts}

@app.get("/api/feedback/summary")
def feedback_summary(session: Session = Depends(get_session)):
    return [{"reason": reason or "Sin motivo", "count": count} for reason, count in session.execute(
        select(JobFeedback.reason, func.count(JobFeedback.id)).where(JobFeedback.disposition == "rejected").group_by(JobFeedback.reason))]

@app.get('/api/learning')
def learning(session: Session = Depends(get_session)):
    return learning_suggestions(session)


@app.get('/api/ai/status')
def ai_status(session: Session = Depends(get_session)):
    try:
        return daily_usage(session)
    except AnalysisError as exc:
        raise HTTPException(422, str(exc)) from None


@app.post('/api/learning/{proposal_id}')
def decide_learning(proposal_id: str, payload: LearningAction, session: Session = Depends(get_session)):
    if not search_lock.acquire(blocking=False):
        raise HTTPException(409, 'Espera a que termine la búsqueda antes de aplicar preferencias.')
    try:
        return learning_decide(session, proposal_id, payload.action)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    finally:
        search_lock.release()


@app.post('/api/learning/decisions/{decision_id}/undo')
def undo_learning(decision_id: int, session: Session = Depends(get_session)):
    if not search_lock.acquire(blocking=False):
        raise HTTPException(409, 'Espera a que termine la búsqueda antes de deshacer preferencias.')
    try:
        return learning_undo(session, decision_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    finally:
        search_lock.release()


def latest_job_result(session, job_id):
    identities = [job_id, *session.scalars(select(JobAlias.alias_job_id).where(JobAlias.canonical_job_id == job_id))]
    return session.scalar(select(SearchResult).where(SearchResult.job_id.in_(identities)).order_by(SearchResult.id.desc()))


@app.post('/api/ai/preview')
def preview_ai(payload: AiPreviewPayload, session: Session = Depends(get_session)):
    if not preferences()['ai'].get('enabled', False) or not os.getenv('OPENAI_API_KEY'):
        raise HTTPException(422, 'Activa la IA en Ajustes y configura tu clave antes de analizar.')
    try:
        usage = daily_usage(session)
    except AnalysisError as exc:
        raise HTTPException(422, str(exc)) from None
    cached, fresh, skipped = [], [], 0
    for identity in dict.fromkeys(canonical_job_id(session, identity) for identity in payload.job_ids):
        job = session.get(Job, identity)
        saved = latest_job_result(session, identity)
        if not job or not saved:
            skipped += 1
            continue
        search = session.get(Search, saved.search_id)
        params = SearchParams.model_validate_json(search.params_json) if search.params_json != '{}' else SearchParams(keywords=json.loads(search.keywords_json))
        if evaluate_hard_filters(job, params)['status'] == 'excluded':
            skipped += 1
            continue
        analysis = session.scalar(select(AnalysisCache.id).where(
            AnalysisCache.content_hash == job.content_hash, AnalysisCache.prompt_version == PROMPT_VERSION,
            AnalysisCache.model_name == os.getenv('OPENAI_MODEL', 'gpt-4o-mini')))
        (cached if analysis is not None else fresh).append(identity)
    allowed = fresh[:usage['remaining']]
    return {'job_ids': cached + allowed, 'cached': len(cached), 'new_calls': len(allowed),
            'blocked': len(fresh)-len(allowed), 'skipped': skipped, 'usage': usage}


@app.post("/api/jobs/{job_id}/analyze")
def analyze(job_id: int, session: Session = Depends(get_session)):
    job_id = canonical_job_id(session, job_id)
    if not preferences()["ai"].get("enabled", False):
        raise HTTPException(422, "Activa la IA en Ajustes y configura tu clave local antes de analizar.")
    job = session.get(Job, job_id)
    saved = latest_job_result(session, job_id)
    if job is None or saved is None:
        raise HTTPException(404, "No se encontró la oferta.")
    search = session.get(Search, saved.search_id)
    params = SearchParams.model_validate_json(search.params_json) if search.params_json != "{}" else SearchParams(keywords=json.loads(search.keywords_json))
    filtering = evaluate_hard_filters(job, params)
    if filtering["status"] == "excluded":
        raise HTTPException(409, "Las ofertas excluidas no se envían a la IA.")
    if not search_lock.acquire(blocking=False):
        raise HTTPException(409, "Hay una búsqueda o análisis en curso.")
    try:
        result = snapshot(session, job, params, filtering, saved.possible_repost, analyze_job(session, job, True))
        saved.result_json = json.dumps(result, ensure_ascii=False)
        saved.score, saved.score_confidence = result["score"], result["confidence"]
        saved.score_factors_json = json.dumps(result["factors"], ensure_ascii=False)
        session.commit()
        result["feedback"] = feedback_json(session, job_id)
        return result
    finally:
        search_lock.release()
