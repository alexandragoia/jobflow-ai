import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from app.database import Base
from app.models import AnalysisCache, LlmUsage
from app.llm_service import (AnalysisError, PROMPT_VERSION, analyze_job, daily_usage,
                             daily_limit_warning, failure_details, local_analysis)


class AiDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.job = SimpleNamespace(id=1, content_hash='example', title='Bürohilfe',
                                   description_text='Teilzeit.', description_is_partial=True)
        self.env = patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-key',
                                          'OPENAI_MODEL': 'fixture-model', 'OPENAI_MAX_CALLS_PER_DAY': '2'})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.session.close()
        self.engine.dispose()

    def fill_limit(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        self.session.add_all([LlmUsage(content_hash='old', called_at=now-timedelta(hours=25)),
                              LlmUsage(content_hash='one', called_at=now-timedelta(hours=23)),
                              LlmUsage(content_hash='two', called_at=now-timedelta(hours=1))])
        self.session.commit()
        return now

    def test_local_limit_blocks_network_and_does_not_count_again(self):
        now = self.fill_limit()
        usage = daily_usage(self.session)
        self.assertEqual((usage['used'], usage['remaining']), (2, 0))
        self.assertEqual(datetime.fromisoformat(usage['next_available_at']),
                         (now+timedelta(hours=1)).replace(tzinfo=timezone.utc))
        self.assertIn('hora de Alemania', daily_limit_warning(usage))
        with patch('app.llm_service.httpx.post') as request:
            result = analyze_job(self.session, self.job, True)
            request.assert_not_called()
        self.assertEqual(result['status'], 'daily_limit')
        self.assertEqual(result['error_code'], 'daily_limit')
        self.assertEqual(self.session.scalar(select(func.count(LlmUsage.id))), 3)

    def test_cache_reusable_at_limit(self):
        self.fill_limit()
        self.session.add(AnalysisCache(content_hash=self.job.content_hash, prompt_version=PROMPT_VERSION,
                                       model_name='fixture-model', analysis_json=local_analysis(self.job).model_dump_json()))
        self.session.commit()
        with patch('app.llm_service.httpx.post') as request:
            result = analyze_job(self.session, self.job, True)
            request.assert_not_called()
        self.assertEqual((result['status'], result['method']), ('cached', 'openai'))

    def test_failed_attempt_counted_with_specific_reason(self):
        with patch('app.llm_service._openai_analysis', side_effect=AnalysisError('invalid_evidence', 'Cita inválida.')):
            result = analyze_job(self.session, self.job, True)
        self.assertEqual(result['error_code'], 'invalid_evidence')
        self.assertEqual(daily_usage(self.session)['used'], 1)

    def test_provider_errors_are_classified_without_leaking_messages(self):
        for status, provider_code, expected in [(429, 'credit_balance_exhausted', 'no_credit'),
                                                (429, None, 'rate_limit'), (401, None, 'invalid_key'),
                                                (403, None, 'permissions'), (503, None, 'provider_unavailable')]:
            response = httpx.Response(status, json={'error': {'code': provider_code, 'message': 'SECRET'}},
                                      request=httpx.Request('POST', 'https://example.invalid/SECRET'))
            with self.assertRaises(httpx.HTTPStatusError) as raised:
                response.raise_for_status()
            code, message = failure_details(raised.exception)
            self.assertEqual(code, expected)
            self.assertNotIn('SECRET', message)

    def test_reduced_and_zero_limit(self):
        now = self.fill_limit()
        with patch.dict(os.environ, {'OPENAI_MAX_CALLS_PER_DAY': '1'}):
            self.assertEqual(datetime.fromisoformat(daily_usage(self.session)['next_available_at']),
                             (now+timedelta(hours=23)).replace(tzinfo=timezone.utc))
        with patch.dict(os.environ, {'OPENAI_MAX_CALLS_PER_DAY': '0'}):
            usage = daily_usage(self.session)
            self.assertEqual(usage['remaining'], 0)
            self.assertIsNone(usage['next_available_at'])
        with patch.dict(os.environ, {'OPENAI_MAX_CALLS_PER_DAY': '-1'}):
            with self.assertRaises(AnalysisError):
                daily_usage(self.session)
