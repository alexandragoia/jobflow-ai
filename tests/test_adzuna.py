import os
import unittest
from unittest.mock import patch

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.adzuna import normalize_job, search_adzuna
from app.database import Base
from app.models import Job, JobSource
from app.schemas import SearchParams
from app.sources import seed_sources


class AdzunaNormalizationTests(unittest.TestCase):
    def test_normalizes_adzuna_fields_without_inventing_missing_values(self):
        normalized = normalize_job({
            "id": 123,
            "title": "Datenerfassung (m/w/d)",
            "company": {"display_name": "Example GmbH"},
            "location": {"display_name": "Dortmund"},
            "created": "2026-10-07T12:30:00Z",
            "contract_time": "full_time",
            "description": "Extract only",
            "latitude": 51.53,
            "longitude": 7.48,
            "redirect_url": "https://www.adzuna.de/details/123",
        })
        self.assertEqual(normalized["title"], "Datenerfassung (m/w/d)")
        self.assertEqual(normalized["employment_type"], "full_time")
        self.assertTrue(normalized["description_is_partial"])
        self.assertEqual(normalized["distance_status"], "approximate")
        self.assertIsNone(normalized["date_updated"])

    def test_missing_coordinates_and_date_remain_unknown(self):
        normalized = normalize_job({"id": 7, "title": "Bürohilfe"})
        self.assertIsNone(normalized["distance_km"])
        self.assertEqual(normalized["distance_status"], "unknown")
        self.assertIsNone(normalized["date_posted"])
        self.assertEqual(normalized["date_precision"], "unknown")

    def test_search_params_enforce_user_location_radius_and_keyword_limit(self):
        self.assertEqual(SearchParams(keywords=["Bürohilfe"], radius_km=0).radius_km, 0)
        with self.assertRaises(ValueError):
            SearchParams(keywords=["Bürohilfe"], radius_km=11)
        with self.assertRaises(ValueError):
            SearchParams(keywords=[str(i) for i in range(21)])


class AdzunaStorageTests(unittest.TestCase):
    def test_search_saves_job_and_source_link(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        payload = {
            "count": 1,
            "results": [{
                "id": "job-123", "title": "Bürokraft", "company": {"display_name": "Example"},
                "location": {"display_name": "Dortmund"}, "created": "2026-10-07T12:00:00Z",
                "description": "Partial ad text", "redirect_url": "https://www.adzuna.de/details/123",
                "latitude": 51.53, "longitude": 7.48,
            }],
        }
        with Session(engine) as session:
            seed_sources(session)
            with patch.dict(os.environ, {"ADZUNA_APP_ID": "test-id", "ADZUNA_APP_KEY": "test-key"}), \
                    patch("app.adzuna.httpx.get", return_value=httpx.Response(
                        200, json=payload, request=httpx.Request("GET", "https://api.adzuna.com/test")
                    )):
                jobs, total = search_adzuna(session, SearchParams(keywords=["Bürokraft"]))
            self.assertEqual(total, 1)
            self.assertEqual(len(jobs), 1)
            stored = session.scalar(select(Job).where(Job.title == "Bürokraft"))
            link = session.scalar(select(JobSource).where(JobSource.source_job_id == "job-123"))
            self.assertIsNotNone(stored)
            self.assertEqual(link.original_url, "https://www.adzuna.de/details/123")
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
