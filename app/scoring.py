from .settings_service import preferences
from .relevance import relevance
from .experience import required_experience_quotes

LABELS = {"keyword_title": "Coincidencia en el título", "keyword_description": "Coincidencia en el extracto",
 "full_time": "Jornada completa", "part_time": "Jornada parcial", "daytime": "Horario diurno",
 "two_shift": "Dos turnos", "office": "Tareas de oficina", "data": "Trabajo con datos",
 "coordination": "Coordinación y administración", "quereinsteiger": "Acepta cambio de sector",
 "training": "Ofrece formación o incorporación guiada", "low_contact": "Poco contacto con clientes",
 "high_contact": "Contacto constante con clientes", "hybrid": "Trabajo híbrido", "remote": "Teletrabajo",
 "phone_3": "Uso frecuente del teléfono", "phone_4_5": "Teléfono como actividad principal",
 "physical_high": "Exigencia física alta", "reception": "Recepción", "cleaning": "Limpieza como tarea",
 "warehouse": "Trabajo de almacén", "sales": "Ventas", "weekend": "Trabajo en fin de semana",
 "qualification": "Requisito de titulación pendiente de revisar", "digital": "Herramientas digitales",
 "heavy_german": "Requisito de alemán avanzado", "quality": "Control de calidad",
 "required_experience": "Experiencia previa explícitamente requerida"}

def score_job(job, keywords, flags, analysis, excluded=False, qualification_evidence=None):
    weights = preferences()["weights"]
    factors = []
    unknowns = []
    score = 50

    def add(key, quote, origin="stated"):
        nonlocal score
        points = weights[key]
        if origin == "inferred":
            points = round(points / 2)
        score += points
        factors.append({"label": LABELS[key], "impact": points, "evidence": quote, "origin": origin})

    matching = relevance(job, keywords)
    title_hits = matching['matched_keywords'] if matching['level'] == 'title' else []
    description_hits = matching['matched_keywords'] if matching['level'] == 'description' else []
    if title_hits:
        add("keyword_title", job.title)
    elif description_hits:
        add("keyword_description", ", ".join(description_hits))
    if job.employment_type in ("full_time", "part_time"):
        add(job.employment_type, "Dato de jornada proporcionado por Adzuna")
    else:
        unknowns.append("Jornada")
    if job.distance_status != "exact":
        unknowns.append("Distancia fiable")
    if not job.date_posted:
        unknowns.append("Fecha de publicación")

    checks = [("shift_type", {"daytime": "daytime", "two_shift": "two_shift"}),
        ("task_category", {k: k for k in ("office", "data", "coordination", "quality", "reception", "cleaning", "warehouse", "sales")}),
        ("quereinsteiger", {"yes": "quereinsteiger"}), ("training_provided", {"yes": "training"}),
        ("customer_contact", {"none": "low_contact", "low": "low_contact", "high": "high_contact"}),
        ("remote_type", {"hybrid": "hybrid", "remote": "remote"}),
        ("phone_intensity", {3: "phone_3", 4: "phone_4_5", 5: "phone_4_5"}),
        ("physical_demand", {"high": "physical_high"}), ("weekend_work", {"yes": "weekend"}),
        ("digital_tools", {"yes": "digital"}), ("language_level", {"C1": "heavy_german", "C2": "heavy_german"})]
    for field, mapping in checks:
        value = analysis[field]
        if value["value"] == "unknown":
            unknowns.append(field)
        elif value["value"] in mapping:
            add(mapping[value["value"]], value["evidence_quote"], value["origin"])
    if "POSSIBLE_QUALIFICATION_MISMATCH" in flags:
        add("qualification", "; ".join(qualification_evidence or []))
    experience = required_experience_quotes(job)
    if experience:
        add('required_experience', '; '.join(experience))
    for field in ("education_requirement", "working_hours", "main_tasks_summary"):
        if analysis[field]["value"] == "unknown":
            unknowns.append(field)
    confidence = analysis["confidence"]
    if job.description_is_partial or len(unknowns) >= 6:
        confidence = "low"
    elif unknowns and confidence == "high":
        confidence = "medium"
    positives = [f["label"] for f in factors if f["impact"] > 0]
    concerns = [f["label"] for f in factors if f["impact"] < 0]
    bounded = max(0, min(100, score))
    if matching['level'] == 'unconfirmed':
        bounded = min(bounded, 39)
        confidence = 'low'
        concerns.append('Sin coincidencia clara con los puestos buscados')
        factors.append({'label': 'Límite por falta de coincidencia con la búsqueda', 'impact': bounded - score,
                        'evidence': matching['explanation'], 'origin': 'inferred'})
    band = next(label for limit, label in [(90, "Excelente"), (75, "Fuerte"), (60, "Posible"), (40, "Débil"), (0, "Poco ajuste")] if bounded >= limit)
    explanation = "Coincide con: " + "; ".join(positives[:3]) + "." if positives else "Faltan datos para recomendar esta oferta con seguridad."
    if concerns:
        explanation += " Conviene revisar: " + concerns[0].lower() + "."
    if matching['level'] == 'unconfirmed':
        explanation = matching['explanation'] + ' Revisa el anuncio completo antes de decidir.'
    return {"score": None if excluded else bounded, "band": "Excluida" if excluded else band,
        "confidence": confidence, "why_recommended": "Excluida por un filtro activo." if excluded else explanation,
        "concerns": concerns, "matched_positives": positives, "unknowns": unknowns,
        "factors": factors, "method": "weighted_rules", "relevance": matching}
