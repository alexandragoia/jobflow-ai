from enum import StrEnum
from typing import Generic, Literal, TypeVar
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .relevance import clean_keyword

class EmploymentType(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    MINIJOB = "minijob"
    UNKNOWN = "unknown"

class JobStatus(StrEnum):
    NEW = "new"
    EXCLUDED = "excluded"
    EXPIRED = "expired"

class SourceStatus(StrEnum):
    API_AVAILABLE = "API_AVAILABLE"
    SEARCH_LINK_ONLY = "SEARCH_LINK_ONLY"
    UNAVAILABLE = "UNAVAILABLE"
    FEED_AVAILABLE = "FEED_AVAILABLE"
    PARTNER_ACCESS_REQUIRED = "PARTNER_ACCESS_REQUIRED"
    MANUAL = "MANUAL"
    ACCESS_REQUIRED = "ACCESS_REQUIRED"
    PENDING = "PENDING"


class SearchParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keywords: list[str] = Field(min_length=1, max_length=20)
    radius_km: int = Field(default=10, ge=0, le=10, strict=True)
    max_age_days: int = Field(default=7, ge=0, le=30, strict=True)
    employment_types: list[EmploymentType] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=lambda: ["Adzuna"], max_length=32)
    use_ai: bool = False

    @field_validator("keywords")
    @classmethod
    def clean_keywords(cls, values: list[str]) -> list[str]:
        cleaned = list({clean_keyword(value).casefold(): clean_keyword(value) for value in values if clean_keyword(value)}.values())
        if not cleaned or any(len(word) > 100 for word in cleaned):
            raise ValueError("Introduce al menos una palabra clave.")
        if len(cleaned) > 20:
            raise ValueError("Puedes usar como máximo 20 palabras clave.")
        return cleaned

T = TypeVar("T")

class Evidence(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid")
    value: T
    origin: Literal["stated", "inferred"]
    evidence_quote: str

    @field_validator("value", mode="before")
    @classmethod
    def meaningful_value(cls, value):
        if isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
            raise ValueError("Usa unknown para datos ausentes.")
        return value

    @model_validator(mode="after")
    def stated_needs_quote(self):
        if self.origin == "stated" and (not self.evidence_quote.strip() or self.value == "unknown"):
            raise ValueError("Un hecho explícito necesita una cita y un valor conocido.")
        return self

class JobAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shift_type: Evidence[Literal["daytime", "two_shift", "three_shift", "night", "flexible", "unknown"]]
    working_hours: Evidence[str]
    phone_intensity: Evidence[Literal[0, 1, 2, 3, 4, 5, "unknown"]]
    customer_contact: Evidence[Literal["none", "low", "medium", "high", "unknown"]]
    physical_demand: Evidence[Literal["low", "medium", "high", "unknown"]]
    education_requirement: Evidence[Literal["mandatory", "preferred", "optional", "none", "unknown"]]
    quereinsteiger: Evidence[Literal["yes", "no", "unknown"]]
    training_provided: Evidence[Literal["yes", "no", "unknown"]]
    language_level: Evidence[Literal["A1", "A2", "B1", "B2", "C1", "C2", "unknown"]]
    remote_type: Evidence[Literal["onsite", "hybrid", "remote", "unknown"]]
    main_tasks_summary: Evidence[str]
    weekend_work: Evidence[Literal["yes", "no", "unknown"]]
    task_category: Evidence[Literal["office", "data", "coordination", "quality", "care", "cleaning", "warehouse", "reception", "sales", "other", "unknown"]]
    digital_tools: Evidence[Literal["yes", "no", "unknown"]]
    confidence: Literal["high", "medium", "low"]

class AiPreviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_ids: list[int] = Field(min_length=1, max_length=50)


class SettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    radius_km: int = Field(10, ge=0, le=10, strict=True)
    max_age_days: int = Field(7, ge=0, le=30, strict=True)
    default_keywords: list[str] | None = Field(default=None, min_length=1, max_length=20)
    hard_rules: dict[str, bool]
    weights: dict[str, int]
    ai_enabled: bool = False
    qualifications_unavailable: list[str] = Field(default_factory=list, max_length=30)

    @field_validator('default_keywords')
    @classmethod
    def validate_default_keywords(cls, values):
        return SearchParams.clean_keywords(values) if values is not None else None

    @field_validator("weights")
    @classmethod
    def validate_weights(cls, weights):
        if any(not -40 <= v <= 40 for v in weights.values()):
            raise ValueError("Cada peso debe estar entre -40 y 40.")
        return weights

class FeedbackPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["interested", "rejected", "saved", "unsaved", "clear"]
    reason: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=1000)
    interest_note: str | None = Field(default=None, max_length=1000)
    interest_conditional: bool | None = None


class LearningAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['accept', 'dismiss']
