from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Source
from urllib.parse import urlencode

PORTALS = {
 "Bundesagentur für Arbeit / Jobsuche": "https://www.arbeitsagentur.de/jobsuche/suche",
 "Indeed": "https://de.indeed.com/", "StepStone": "https://www.stepstone.de/",
 "LinkedIn Jobs": "https://www.linkedin.com/jobs/", "meinestadt.de": "https://jobs.meinestadt.de/dortmund",
 "Stellenanzeigen.de": "https://www.stellenanzeigen.de/", "Jobware": "https://www.jobware.de/",
 "Alloheim": "https://www.alloheim.de/karriere", "Workwise": "https://www.workwise.io/",
 "Hotelcareer": "https://www.hotelcareer.de/", "Interamt": "https://www.interamt.de/",
 "Glassdoor": "https://www.glassdoor.de/", "XING Jobs": "https://www.xing.com/jobs",
 "Jobninja": "https://www.jobninja.com/", "Talent.com": "https://de.talent.com/",
 "Jobted": "https://de.jobted.com/", "Jobeka": "https://de.jobeka.com/",
 "Bebee": "https://de.bebee.com/", "Putzperle": "https://putzperle.de/",
 "Joblift": "https://joblift.de/", "Kimeta": "https://www.kimeta.de/",
 "HeyJobs": "https://www.heyjobs.co/de-de/", "Yourfirm": "https://www.yourfirm.de/",
 "Jooble": "https://de.jooble.org/", "Monster": "https://www.monster.de/",
 "stellenwerk": "https://www.stellenwerk.de/", "Jobvector": "https://www.jobvector.de/",
}

def source_link(name, params=None):
    base = PORTALS.get(name)
    if not base:
        return None
    # Only the BA URL template is prefilled; other links open the real portal search form.
    prefilled = name == "Bundesagentur für Arbeit / Jobsuche" and params is not None
    if prefilled:
        base += "?" + urlencode({"was": " ".join(params.keywords), "wo": "44145", "umkreis": params.radius_km})
    return {"name": name, "url": base, "prefilled": prefilled,
            "label": "Búsqueda externa — no importada", "note": "Comprueba allí el radio y los filtros."}

# Catalog from the original concept. Only Adzuna is an API integration in this MVP.
CATALOG = [
    ("Hotelcareer", "SEARCH_LINK_ONLY"), ("Indeed", "SEARCH_LINK_ONLY"),
    ("StepStone", "SEARCH_LINK_ONLY"), ("Alloheim", "SEARCH_LINK_ONLY"),
    ("LinkedIn Jobs", "SEARCH_LINK_ONLY"), ("Bundesagentur für Arbeit / Jobsuche", "SEARCH_LINK_ONLY"),
    ("Pushnami", "SEARCH_LINK_ONLY"), ("Glassdoor", "SEARCH_LINK_ONLY"),
    ("meinestadt.de", "SEARCH_LINK_ONLY"), ("XING Jobs", "SEARCH_LINK_ONLY"),
    ("Jobninja", "SEARCH_LINK_ONLY"), ("Talent.com", "SEARCH_LINK_ONLY"),
    ("Jobted", "SEARCH_LINK_ONLY"), ("Jobeka", "SEARCH_LINK_ONLY"),
    ("Bebee", "SEARCH_LINK_ONLY"), ("Putzperle", "SEARCH_LINK_ONLY"),
    ("Shift", "SEARCH_LINK_ONLY"), ("Stellenanzeigen.de", "SEARCH_LINK_ONLY"),
    ("Jobware", "SEARCH_LINK_ONLY"), ("Joblift", "SEARCH_LINK_ONLY"),
    ("Kimeta", "SEARCH_LINK_ONLY"), ("HeyJobs", "SEARCH_LINK_ONLY"),
    ("Workwise", "SEARCH_LINK_ONLY"), ("Yourfirm", "SEARCH_LINK_ONLY"),
    ("Jooble", "SEARCH_LINK_ONLY"), ("Monster", "SEARCH_LINK_ONLY"),
    ("Interamt", "SEARCH_LINK_ONLY"), ("Arbeitnow", "UNAVAILABLE"),
    ("stellenwerk", "SEARCH_LINK_ONLY"), ("Jobvector", "SEARCH_LINK_ONLY"),
    ("Adzuna", "API_AVAILABLE"),
]


def seed_sources(session: Session) -> None:
    existing = set(session.scalars(select(Source.name)).all())
    for name, status in CATALOG:
        if name in existing:
            continue
        session.add(Source(
            name=name,
            enabled=(name == "Adzuna" or status == "SEARCH_LINK_ONLY"),
            integration_type="api" if name == "Adzuna" else "search_link",
            status=status,
            notes="MVP source" if name == "Adzuna" else "External search link; not imported",
        ))
    session.commit()
    for name in ("Pushnami", "Shift"):
        row = session.scalar(select(Source).where(Source.name == name))
        if row:
            row.status, row.enabled, row.notes = "UNAVAILABLE", False, "Nombre no identificado como fuente de empleo utilizable."
    session.commit()
