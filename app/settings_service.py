import os
from threading import Lock
import yaml
from .config import ROOT, load_yaml, mutable_config_path

DEFAULT_RULES = {key: True for key in ("night_shift", "three_shift", "german_too_high", "outside_radius", "too_old", "call_center_sales", "employment_type")}
DEFAULT_RULES["mandatory_qualification"] = False
DEFAULT_WEIGHTS = {"keyword_title": 12, "keyword_description": 5, "full_time": 10,
    "part_time": -4, "daytime": 12, "two_shift": -5, "office": 12, "data": 12,
    "coordination": 10, "quereinsteiger": 12, "training": 8, "low_contact": 10,
    "high_contact": -18, "hybrid": 10, "remote": 10, "phone_3": -10, "phone_4_5": -22,
    "physical_high": -22, "reception": -18, "cleaning": -22, "warehouse": -20,
    "sales": -18, "weekend": -5, "qualification": -12, "digital": 8, "heavy_german": -12, "quality": 10,
    "required_experience": 0}
_lock = Lock()

def preferences():
    data = load_yaml("preferences.yaml")
    data["hard_rules"] = {**DEFAULT_RULES, **data.get("hard_rules", {})}
    data["weights"] = {**DEFAULT_WEIGHTS, **data.get("weights", {})}
    data.setdefault("ai", {"enabled": False})
    return data

def public_settings():
    data = preferences()
    return {"postcode": "44145", "radius_km": data.get("location", {}).get("radius_km", 10),
        "max_age_days": data.get("location", {}).get("max_job_age_days", 7),
        "default_keywords": data.get('search', {}).get('default_keywords', ['Bürohilfe', 'Bürokraft', 'Datenerfassung', 'Backoffice']),
        "hard_rules": data["hard_rules"], "weights": data["weights"],
        "ai_enabled": data["ai"].get("enabled", False),
        "ai_key_configured": bool(os.getenv("OPENAI_API_KEY")),
        "ai_model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "qualifications_unavailable": load_yaml("qualifications.yaml").get("unavailable", [])}

def save_settings(payload):
    if set(payload.hard_rules) != set(DEFAULT_RULES) or set(payload.weights) != set(DEFAULT_WEIGHTS):
        raise ValueError("Las reglas o los pesos no coinciden con los ajustes de la aplicación.")
    data = preferences()
    data["location"] = {"postcode": "44145", "city": "Dortmund", "radius_km": payload.radius_km,
                        "maximum_radius_km": 10, "max_job_age_days": payload.max_age_days}
    data["hard_rules"], data["weights"] = payload.hard_rules, payload.weights
    if payload.default_keywords is not None:
        data.setdefault('search', {})['default_keywords'] = payload.default_keywords
    data["ai"] = {"enabled": payload.ai_enabled}
    qualifications = load_yaml("qualifications.yaml")
    qualifications["unavailable"] = [s.strip() for s in payload.qualifications_unavailable if s.strip()]
    if payload.hard_rules["mandatory_qualification"] and not qualifications["unavailable"]:
        raise ValueError("Para excluir por titulación, indica primero los requisitos concretos que no cumples.")
    with _lock:
        for name, content in (("preferences.yaml", data), ("qualifications.yaml", qualifications)):
            target = mutable_config_path(name, ROOT)
            temporary = target.with_suffix(target.suffix + '.tmp')
            temporary.write_text(yaml.safe_dump(content, allow_unicode=True, sort_keys=False), encoding="utf-8")
            temporary.replace(target)
    return public_settings()
