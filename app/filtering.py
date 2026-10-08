import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .config import load_yaml
from .models import Job
from .schemas import SearchParams
from .settings_service import preferences

PATTERNS = load_yaml("filter_patterns.yaml")


def _find_evidence(text: str, phrases: list[str]) -> list[str]:
    evidence = []
    for phrase in phrases:
        for match in re.finditer(phrase, text, re.I):
            start = match.start()
            left = max(0, text.rfind(".", 0, start) + 1)
            right = text.find(".", match.end())
            quote = text[left:right if right >= 0 else len(text)].strip()
            preceding = text[max(left, start - 45):start].lower()
            if re.search(r"\b(keine?|ohne|nicht|nie|no)\s+(?:mögliche\s+)?(?:arbeit|schicht|tätigkeit|erforderlich)?\s*$", preceding):
                continue
            # 'C1 not required' and optional requirements are not hard exclusions.
            if re.search(r"(?:nicht erforderlich|nicht zwingend|wünschenswert|von Vorteil)", match.group(), re.I):
                continue
            evidence.append(quote[:1000])
    return evidence


def _group(key: str) -> list[str]:
    value = PATTERNS.get(key, [])
    if isinstance(value, dict):
        return value.get("patterns", [])
    return value


def evaluate_hard_filters(job: Job, params: SearchParams) -> dict:
    """Cheap deterministic checks; unknown/inferred data never triggers exclusion."""
    text = " ".join(part for part in (job.title, job.description_text or "") if part)
    evidence: list[str] = []
    flags: list[str] = []
    reason = None
    rules = preferences()["hard_rules"]

    # API already scopes by postcode and radius. Do not locally exclude approximate centroids.
    if rules["outside_radius"] and job.distance_status == "exact" and job.distance_km is not None and job.distance_km > params.radius_km:
        reason = "OUTSIDE_RADIUS"

    if reason is None and rules["too_old"] and job.date_posted is not None:
        now = datetime.now(timezone.utc)
        posted = job.date_posted.replace(tzinfo=timezone.utc) if job.date_posted.tzinfo is None else job.date_posted
        too_old = (now - posted).total_seconds() > params.max_age_days * 86400
        if params.max_age_days == 0:
            zone = ZoneInfo('Europe/Berlin')
            too_old = posted.astimezone(zone).date() != now.astimezone(zone).date()
        if too_old:
            reason = "TOO_OLD"
    if reason is None and rules["employment_type"] and params.employment_types and job.employment_type != "unknown" and job.employment_type not in params.employment_types:
        reason = "EMPLOYMENT_TYPE"

    rule_checks = [
        ("night_shift", "NIGHT_SHIFT"),
        ("three_shift", "THREE_SHIFT"),
        ("german_too_high", "GERMAN_TOO_HIGH"),
        ("call_center_sales", "CALL_CENTER_SALES"),
    ]
    for key, code in rule_checks:
        hits = _find_evidence(text, _group(key)) if rules[key] else []
        if hits:
            evidence.extend(hits)
            if reason is None:
                reason = code

    qualification_hits = _find_evidence(text, _group("mandatory_qualification"))
    if qualification_hits:
        flags.append("POSSIBLE_QUALIFICATION_MISMATCH")
        evidence.extend(qualification_hits)
        unavailable = load_yaml("qualifications.yaml").get("unavailable", [])
        if rules["mandatory_qualification"] and any(term.casefold() in quote.casefold() for term in unavailable for quote in qualification_hits):
            reason = reason or "MANDATORY_QUALIFICATION"

    return {
        "status": "excluded" if reason else "new",
        "excluded_reason": reason,
        "evidence": list(dict.fromkeys(evidence)),
        "flags": flags,
        "qualification_evidence": qualification_hits,
    }
