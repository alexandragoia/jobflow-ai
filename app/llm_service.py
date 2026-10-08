import json
import os
import re
import logging
import hashlib
import httpx
from sqlalchemy import select
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pydantic import ValidationError
from .config import ROOT, load_yaml
from .models import AnalysisCache, LlmUsage
from .schemas import JobAnalysis

PROMPT_VERSION = "analysis_v1-" + hashlib.sha256(((ROOT / "prompts" / "analysis_v1.txt").read_text(encoding="utf-8") + (ROOT / "config" / "analysis_patterns.yaml").read_text(encoding="utf-8") + json.dumps(JobAnalysis.model_json_schema(), sort_keys=True)).encode()).hexdigest()[:12]
logger = logging.getLogger("jobflow")


class AnalysisError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def daily_usage(session):
    try:
        limit = int(os.getenv('OPENAI_MAX_CALLS_PER_DAY', '40'))
        if limit < 0:
            raise ValueError()
    except ValueError:
        raise AnalysisError('invalid_configuration', 'El límite local de IA no es válido. Revisa OPENAI_MAX_CALLS_PER_DAY en .env.') from None
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    calls = session.scalars(select(LlmUsage.called_at).where(LlmUsage.called_at >= cutoff).order_by(LlmUsage.called_at)).all()
    next_available = (calls[len(calls) - limit].replace(tzinfo=timezone.utc) + timedelta(days=1)).isoformat() if limit and len(calls) >= limit else None
    return {'used': len(calls), 'limit': limit, 'remaining': max(0, limit - len(calls)),
            'next_available_at': next_available}


def daily_limit_warning(usage):
    text = f"Límite local de IA: {usage['used']} de {usage['limit']} intentos en las últimas 24 horas; incluye los fallidos."
    if usage['next_available_at']:
        available = datetime.fromisoformat(usage['next_available_at']).astimezone(ZoneInfo('Europe/Berlin'))
        text += ' Habrá otro intento disponible el ' + available.strftime('%d/%m/%Y a las %H:%M') + ' (hora de Alemania).'
    elif usage['limit'] == 0:
        text += ' El límite está configurado en cero.'
    return text + ' Se conservan los análisis guardados y se usan datos locales para las demás ofertas.'


def failure_details(exc):
    # Never display arbitrary provider messages, request URLs or Authorization headers.
    if isinstance(exc, AnalysisError):
        return exc.code, str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        status, code = exc.response.status_code, None
        try:
            error = exc.response.json().get('error', {})
            if isinstance(error, dict):
                code = error.get('code')
                if error.get('type') == 'insufficient_quota' and not code:
                    code = 'insufficient_quota'
        except (ValueError, AttributeError):
            pass
        if code in ('credit_balance_exhausted', 'insufficient_quota'):
            return 'no_credit', 'OpenAI indica que no hay saldo o cuota disponible. Revisa la facturación de la API; se usan datos locales.'
        if code in ('project_spend_limit_exceeded', 'organization_spend_limit_exceeded', 'organization_usage_limit_exceeded', 'usage_limit_exceeded'):
            return 'provider_spend_limit', 'Se alcanzó un límite de gasto o uso de OpenAI. Revisa los límites de tu cuenta; se usan datos locales.'
        if status == 429:
            return 'rate_limit', 'OpenAI ha limitado temporalmente la frecuencia de consultas. Espera antes de volver a analizar; se usan datos locales.'
        if status == 401:
            return 'invalid_key', 'OpenAI no acepta la clave configurada. Revisa la clave en .env y reinicia JobFlow; se usan datos locales.'
        if status == 403:
            return 'permissions', 'La clave no tiene permiso para este análisis. Revisa Model capabilities → Request; se usan datos locales.'
        if status == 404:
            return 'model_unavailable', 'El modelo configurado no está disponible para esta cuenta. Revisa OPENAI_MODEL; se usan datos locales.'
        if status >= 500:
            return 'provider_unavailable', 'OpenAI tiene un error temporal. Puedes volver a intentarlo más tarde; se usan datos locales.'
        return 'invalid_request', 'OpenAI rechazó la solicitud de análisis. Revisa la configuración del modelo; se usan datos locales.'
    if isinstance(exc, httpx.TimeoutException):
        return 'timeout', 'OpenAI tardó demasiado en responder. Se usan datos locales; puedes volver a intentarlo más tarde.'
    if isinstance(exc, httpx.RequestError):
        return 'connection', 'No se pudo conectar con OpenAI. Revisa la conexión a Internet; se usan datos locales.'
    if isinstance(exc, (ValidationError, ValueError)):
        return 'invalid_output', 'La respuesta de IA no cumple el formato o la evidencia requerida. Se usan datos locales para evitar mostrar datos no confirmados.'
    return 'analysis_error', 'No se pudo completar el análisis de IA. Se conservan los datos locales disponibles.'

def _quote(text, start, end):
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start)) + 1
    right = text.find(".", end)
    return text[left:right if right >= 0 else len(text)].strip()[:1000]

def local_analysis(job):
    values = {key: {"value": "unknown", "origin": "inferred", "evidence_quote": ""}
              for key in JobAnalysis.model_fields if key != "confidence"}
    # Local extraction deliberately uses description duties rather than inferring from the title.
    text = job.description_text or ""
    for field, choices in load_yaml("analysis_patterns.yaml").items():
        found = False
        for value, patterns in choices.items():
            for pattern in patterns:
                match = re.search(pattern, text, re.I)
                if match:
                    preceding = text[max(0, match.start()-25):match.start()]
                    if re.search(r"\b(?:keine?|ohne|nicht)\s*$", preceding, re.I):
                        continue
                    quote = _quote(text, match.start(), match.end())
                    origin = "stated"
                    if field == "task_category" and value in ("cleaning", "warehouse", "reception", "sales") and not re.search(r"Hauptaufgabe|hauptsächlich|Schwerpunkt|überwiegend", quote, re.I):
                        origin = "inferred"
                    values[field] = {"value": value, "origin": origin, "evidence_quote": quote}
                    found = True
                    break
            if found:
                break
    hours = re.search(r"\b\d{1,2}:\d{2}\s*[–-]\s*\d{1,2}:\d{2}\b", text)
    if hours:
        values["working_hours"] = {"value": hours.group(), "origin": "stated", "evidence_quote": hours.group()}
    values["confidence"] = "low" if job.description_is_partial else "medium"
    return JobAnalysis.model_validate(values)

def validate_evidence(analysis, job):
    text = " ".join((job.title or "", job.description_text or ""))
    normalized = re.sub(r"\s+", " ", text)
    for key, field in analysis:
        if key == "confidence":
            continue
        if field.evidence_quote and re.sub(r"\s+", " ", field.evidence_quote) not in normalized:
            raise AnalysisError('invalid_evidence', 'La IA devolvió una cita que no coincide con el anuncio. Se usan datos locales para evitar mostrar datos no confirmados.')
    if job.description_is_partial:
        analysis.confidence = "low"
    return analysis

def _openai_analysis(job, model):
    schema = JobAnalysis.model_json_schema()
    response = httpx.post("https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        json={"model": model, "store": False,
              "instructions": (ROOT / "prompts" / "analysis_v1.txt").read_text(encoding="utf-8"),
              "input": json.dumps({"job_text": "\n".join((job.title or "", job.description_text or "")),
                                    "description_is_partial": job.description_is_partial}, ensure_ascii=False),
              "text": {"format": {"type": "json_schema", "name": "job_analysis", "strict": True, "schema": schema}},
              "max_output_tokens": 4000}, timeout=45)
    response.raise_for_status()
    result = response.json()
    if result.get("status") != "completed":
        raise AnalysisError('incomplete_output', 'OpenAI devolvió un análisis incompleto. Se usan datos locales; puedes volver a intentarlo más tarde.')
    if any(part.get('type') == 'refusal' for item in result.get('output', []) for part in item.get('content', [])):
        raise AnalysisError('refusal', 'OpenAI no realizó el análisis de este extracto. Se usan los datos locales disponibles.')
    output = "".join(part.get("text", "") for item in result.get("output", [])
                     for part in item.get("content", []) if part.get("type") == "output_text")
    return validate_evidence(JobAnalysis.model_validate_json(output), job)

def analyze_job(session, job, use_ai=False):
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini") if use_ai else "local_rules_v1"
    if use_ai and not os.getenv("OPENAI_API_KEY"):
        return {"analysis": local_analysis(job).model_dump(), "method": "local", "status": "not_configured",
                "warning": "Falta la clave de OpenAI; se muestran datos explícitos detectados localmente."}
    cached = session.scalar(select(AnalysisCache).where(AnalysisCache.content_hash == job.content_hash,
        AnalysisCache.prompt_version == PROMPT_VERSION, AnalysisCache.model_name == model))
    if cached:
        return {"analysis": json.loads(cached.analysis_json), "method": "openai" if use_ai else "local", "status": "cached", "warning": None}
    try:
        if use_ai:
            usage = daily_usage(session)
            if not usage['remaining']:
                return {'analysis': local_analysis(job).model_dump(), 'method': 'local', 'status': 'daily_limit',
                        'warning': daily_limit_warning(usage), 'error_code': 'daily_limit'}
            session.add(LlmUsage(content_hash=job.content_hash))
            session.commit()
        analysis = _openai_analysis(job, model) if use_ai else local_analysis(job)
    except Exception as exc:
        code, warning = failure_details(exc)
        logger.warning("analysis_failed job=%s code=%s type=%s", job.id, code, type(exc).__name__)
        return {"analysis": local_analysis(job).model_dump(), "method": "local", "status": "analysis_failed",
                "warning": warning, 'error_code': code}
    session.add(AnalysisCache(content_hash=job.content_hash, prompt_version=PROMPT_VERSION, model_name=model,
                              analysis_json=analysis.model_dump_json()))
    session.flush()
    logger.info("analysis_run job=%s method=%s", job.id, model)
    return {"analysis": analysis.model_dump(), "method": "openai" if use_ai else "local", "status": "ok", "warning": None}
