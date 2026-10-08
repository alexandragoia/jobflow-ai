from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(80), default="job_portal")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    integration_type: Mapped[str] = mapped_column(String(40), default="search_link")
    status: Mapped[str] = mapped_column(String(40), default="SEARCH_LINK_ONLY")
    last_success: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Search(Base):
    __tablename__ = "searches"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    keywords_json: Mapped[str] = mapped_column(Text, default="[]")
    radius_km: Mapped[int] = mapped_column(Integer, default=10)
    max_age_days: Mapped[int] = mapped_column(Integer, default=7)
    total_found: Mapped[int] = mapped_column(Integer, default=0)
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    messages_json: Mapped[str] = mapped_column(Text, default="[]")


class SourceRun(Base):
    __tablename__ = "source_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    search_id: Mapped[int | None] = mapped_column(ForeignKey("searches.id"), nullable=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    jobs_returned: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ApiUsage(Base):
    __tablename__ = "api_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    called_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    endpoint: Mapped[str] = mapped_column(String(120))


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(300))
    company_raw: Mapped[str | None] = mapped_column(String(300), nullable=True)
    company_normalized: Mapped[str | None] = mapped_column(String(300), nullable=True)
    location_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_status: Mapped[str] = mapped_column(String(20), default="unknown")
    date_posted: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    date_updated: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    date_precision: Mapped[str] = mapped_column(String(20), default="unknown")
    employment_type: Mapped[str] = mapped_column(String(40), default="unknown")
    description_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_is_partial: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="new")
    excluded_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    possible_repost: Mapped[bool] = mapped_column(Boolean, default=False)


class JobSource(Base):
    __tablename__ = "job_sources"
    __table_args__ = (UniqueConstraint("source_id", "source_job_id", name="uq_source_job"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    source_job_id: Mapped[str] = mapped_column(String(160))
    original_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    application_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SearchResult(Base):
    __tablename__ = "search_results"
    __table_args__ = (UniqueConstraint("search_id", "job_id", name="uq_search_job"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    search_id: Mapped[int] = mapped_column(ForeignKey("searches.id"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="new")
    excluded_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    filter_evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    possible_repost: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[int] = mapped_column(Integer, default=40)
    score_confidence: Mapped[str] = mapped_column(String(20), default="baja")
    score_factors_json: Mapped[str] = mapped_column(Text, default="[]")
    result_json: Mapped[str] = mapped_column(Text, default="{}")


class JobFeedback(Base):
    __tablename__ = "job_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True, index=True)
    liked: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    disposition: Mapped[str] = mapped_column(String(20), default="none")
    saved: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    interest_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    interest_conditional: Mapped[bool] = mapped_column(Boolean, default=False)


class AnalysisCache(Base):
    __tablename__ = "analysis_cache"
    __table_args__ = (UniqueConstraint("content_hash", "prompt_version", "model_name", name="uq_analysis"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    prompt_version: Mapped[str] = mapped_column(String(40))
    model_name: Mapped[str] = mapped_column(String(120))
    analysis_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SearchCache(Base):
    __tablename__ = "search_cache"
    id: Mapped[int] = mapped_column(primary_key=True)
    query_hash: Mapped[str] = mapped_column(String(64), unique=True)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class LlmUsage(Base):
    __tablename__ = "llm_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    called_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    content_hash: Mapped[str] = mapped_column(String(64))

class JobAlias(Base):
    __tablename__ = "job_aliases"
    alias_job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    canonical_job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)


class LearningDecision(Base):
    __tablename__ = 'learning_decisions'
    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[str] = mapped_column(String(64), unique=True)
    weight_key: Mapped[str] = mapped_column(String(80))
    direction: Mapped[int] = mapped_column(Integer)
    previous_value: Mapped[int] = mapped_column(Integer)
    proposed_value: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20))
    evidence_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
