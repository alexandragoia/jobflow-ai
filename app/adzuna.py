import hashlib
import os
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from math import atan2, cos, radians, sin, sqrt

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import load_yaml
from .models import ApiUsage, Job, JobSource, Source, SearchCache
from .schemas import SearchParams
from .security import safe_url, canonical_url
from .source_base import BaseJobSource, RawJob, SourceHealth
from .relevance import provider_terms

API_ROOT = "https://api.adzuna.com/v1/api/jobs/de/search/1"
ORIGIN = load_yaml("origin.yaml")


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance; approximate because postcode/job coordinates are centroids."""
    earth_radius_km = 6371.0088
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = max(0, min(1, sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2))
    return 2 * earth_radius_km * atan2(sqrt(a), sqrt(1 - a))


def parse_datetime(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def normalize_job(raw: dict) -> dict:
    title = raw.get("title")
    title = title.strip()[:300] if isinstance(title, str) and title.strip() else "Sin título"
    company_data = raw.get("company") or {}
    company = company_data.get("display_name") if isinstance(company_data, dict) else None
    company = company.strip()[:300] if isinstance(company, str) and company.strip() else None
    location_data = raw.get("location") or {}
    location = location_data.get("display_name") if isinstance(location_data, dict) else None
    location = location[:500] if isinstance(location, str) else None
    description = raw.get("description")
    description = description[:20000] if isinstance(description, str) and description else None
    identity_text = "|".join((title.casefold(), (company or "").casefold(), (location or "").casefold(), (description or "").casefold()))
    content_hash = hashlib.sha256(identity_text.encode("utf-8")).hexdigest()

    lat, lon = raw.get("latitude"), raw.get("longitude")
    try:
        lat, lon = float(lat), float(lon)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            lat, lon = None, None
    except (TypeError, ValueError):
        lat, lon = None, None
    km = None
    distance_status = "unknown"
    if lat is not None and lon is not None and ORIGIN.get("latitude") is not None:
        km = round(distance_km(ORIGIN["latitude"], ORIGIN["longitude"], float(lat), float(lon)), 1)
        distance_status = "approximate"

    posted = parse_datetime(raw.get("created"))
    contract_time = (raw.get("contract_time") or "").lower()
    employment_type = {"full_time": "full_time", "part_time": "part_time", "minijob": "minijob"}.get(contract_time, "unknown")
    # Only explicit wording identifies a Minijob; part-time alone does not.
    for text, pattern in ((title, r'\bmini[\s-]?jobs?\b'),
                          (description or '', r'\b(?:auf|als|in)\s+(?:einem?\s+)?mini[\s-]?job(?:[\s-]?basis)?\b|\bmini[\s-]?job[\s-]?basis\b')):
        for match in re.finditer(pattern, text, re.I):
            if not re.search(r'\b(?:kein(?:e|en|em|er)?|nicht|ohne)\s*$', text[max(0, match.start()-30):match.start()], re.I):
                employment_type = 'minijob'
                break
    return {
        "content_hash": content_hash,
        "title": title,
        "company_raw": company,
        "company_normalized": company.casefold() if company else None,
        "location_text": location,
        "latitude": float(lat) if lat is not None else None,
        "longitude": float(lon) if lon is not None else None,
        "distance_km": km,
        "distance_status": distance_status,
        "date_posted": posted,
        "date_updated": None,
        "date_precision": "day" if posted else "unknown",
        "employment_type": employment_type,
        "description_text": description,
        "description_is_partial": True,
        "status": "new",
        "excluded_reason": None,
        "original_url": safe_url(raw.get("redirect_url")),
        "source_job_id": str(raw.get("id", "")),
    }


def _check_daily_limit(session: Session, source_id: int) -> None:
    # Stay below Adzuna's published 250-calls-per-day default cap.
    today = datetime.utcnow().date()
    used = session.scalar(select(func.count(ApiUsage.id)).where(
        ApiUsage.source_id == source_id,
        func.date(ApiUsage.called_at) == today.isoformat(),
    )) or 0
    if used >= 240:
        raise RuntimeError("Límite local: ya se hicieron 240 consultas de Adzuna hoy.")
    for minutes, cap, label in ((1, 20, "minuto"), (7*24*60, 950, "semana"), (31*24*60, 2400, "mes")):
        count = session.scalar(select(func.count(ApiUsage.id)).where(ApiUsage.source_id == source_id,
            ApiUsage.called_at >= datetime.utcnow() - timedelta(minutes=minutes))) or 0
        if count >= cap:
            raise RuntimeError(f"Se alcanzó el límite local de consultas por {label}. Prueba más tarde.")


def fetch_adzuna_payload(session: Session, search_params: SearchParams) -> dict:
    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise RuntimeError("Faltan las claves de Adzuna en el archivo .env local.")

    source = session.scalar(select(Source).where(Source.name == "Adzuna"))
    if source is None:
        raise RuntimeError("No se encontró Adzuna en el catálogo de fuentes.")

    api_params = {
        "app_id": app_id,
        "app_key": app_key,
        "where": ORIGIN["postcode"],
        "distance": search_params.radius_km,
        "max_days_old": max(1, search_params.max_age_days),
        "what_or": " ".join(provider_terms(search_params.keywords)),
        "results_per_page": 50,
        "content-type": "application/json",
    }
    query = {k: v for k, v in api_params.items() if k not in ("app_id", "app_key")}
    query_hash = hashlib.sha256(json.dumps(query, sort_keys=True).encode()).hexdigest()
    cache = session.scalar(select(SearchCache).where(SearchCache.query_hash == query_hash))
    if cache and cache.created_at >= datetime.utcnow() - timedelta(minutes=15):
        payload = json.loads(cache.payload_json)
        logging.getLogger("jobflow").info("source_cache_hit source=Adzuna")
    else:
        _check_daily_limit(session, source.id)
        session.add(ApiUsage(source_id=source.id, endpoint="jobs/de/search/1"))
        session.commit()  # Count failed attempts too; never store credentials or request URLs.
        try:
            response = httpx.get(API_ROOT, params=api_params, timeout=20)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("results", []), list):
                raise ValueError("Invalid response")
        except (httpx.HTTPError, ValueError) as exc:
            source.last_error = type(exc).__name__
            session.commit()
            raise RuntimeError("No se pudo consultar Adzuna; revisa la conexión y el estado de tus claves.") from None
        if cache is None:
            cache = SearchCache(query_hash=query_hash, payload_json="{}")
            session.add(cache)
        cache.payload_json = json.dumps(payload, ensure_ascii=False)
        cache.created_at = datetime.utcnow()
    return payload


class AdzunaSource(BaseJobSource):
    name = "Adzuna"

    def __init__(self, session):
        self.session = session

    def health(self):
        return SourceHealth(name=self.name, configured=bool(os.getenv("ADZUNA_APP_ID") and os.getenv("ADZUNA_APP_KEY")), status="API_AVAILABLE")

    def search(self, params):
        payload = fetch_adzuna_payload(self.session, params)
        rows = payload.get("results", [])[:50]
        try:
            self.total_estimated = max(0, int(payload.get("count", len(rows))))
        except (TypeError, ValueError):
            self.total_estimated = len(rows)
        return [RawJob(source=self.name, payload=row) for row in rows if isinstance(row, dict)]


def search_adzuna(session: Session, search_params: SearchParams) -> tuple[list[Job], int]:
    connector = AdzunaSource(session)
    raw_jobs = [job.payload for job in connector.search(search_params)]
    source = session.scalar(select(Source).where(Source.name == "Adzuna"))

    source.last_success = datetime.utcnow()
    source.last_error = None

    saved: list[Job] = []
    for raw in raw_jobs[:50]:
        if not isinstance(raw, dict):
            continue
        normalized = normalize_job(raw)
        source_job_id = normalized.pop("source_job_id") or "hash-" + normalized["content_hash"]
        original_url = normalized.pop("original_url")
        link = session.scalar(select(JobSource).where(JobSource.source_id == source.id, JobSource.source_job_id == source_job_id)) if source_job_id else None
        job = session.get(Job, link.job_id) if link else None
        if job is None and original_url:
            existing_links = session.scalars(select(JobSource).where(JobSource.original_url.is_not(None))).all()
            match = next((l for l in existing_links if canonical_url(l.original_url) == canonical_url(original_url)), None)
            if match:
                job = session.get(Job, match.job_id)
        if job is None:
            job = session.scalar(select(Job).where(Job.content_hash == normalized["content_hash"]))
        if job is None:
            job = Job(**normalized)
            session.add(job)
            session.flush()
        else:
            if not link and job.date_posted and normalized["date_posted"] and job.date_posted.date() != normalized["date_posted"].date():
                job.possible_repost = True
            for key, value in normalized.items():
                if key not in ("status", "excluded_reason"):
                    setattr(job, key, value)
        if link is None:
            session.add(JobSource(job_id=job.id, source_id=source.id, source_job_id=source_job_id,
                                  original_url=original_url))
        else:
            link.original_url = original_url
            link.retrieved_at = datetime.utcnow()
        job.last_seen_at = datetime.utcnow()
        session.flush()
        saved.append(job)
    session.commit()
    return saved, connector.total_estimated
