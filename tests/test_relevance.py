import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.relevance import clean_keyword, provider_terms, relevance
from app.schemas import SearchParams, SettingsPayload
from app.filtering import evaluate_hard_filters
from app.scoring import score_job
from app.search_service import empty_analysis, result_order

KEYWORDS = ['Bürohilfe', 'Bürokraft Quereinsteiger', 'Teamassistenz', 'Pflegehelfer',
    'Alltagsbegleiter', 'Betreuungsassistent', 'Schulbegleiter', 'Sozialassistent',
    'Integrationshelfer', 'Persönliche Assistenz', 'Hauswirtschaftsleitung', 'Haushaltshilfe',
    'Housekeeping Supervisor', 'Hausdame', 'Teamleiter Housekeeping', 'Jobcoach Rumänisch',
    'Rumänischer Sprachmittler', 'Spanischer Sprachmittler', 'KI Quereinsteiger', 'KI Automatisierung']

def job(title, description=''):
    return SimpleNamespace(title=title, description_text=description, employment_type='full_time',
        distance_status='unknown', distance_km=None, date_posted=None, description_is_partial=True)

class RelevanceTests(unittest.TestCase):
    def test_pasted_markdown_list(self):
        values = [r'**\* '+word+'**' for word in KEYWORDS]
        values[-1] = '** * KI Automatisierung ...**'
        self.assertEqual(SearchParams(keywords=values).keywords, KEYWORDS)
        self.assertEqual(clean_keyword('1. Bürohilfe'), 'Bürohilfe')
        self.assertEqual(SearchParams(keywords=['Bürohilfe', 'bürohilfe']).keywords, ['bürohilfe'])

    def test_no_generic_keyword_can_match_an_unrelated_role(self):
        for title in ['Verkäufer Quereinsteiger', 'Teamleiter Produktion', 'Elektriker',
                      'Kindergarten Fachkraft', 'Haustechniker im Hotel', 'Spanischlehrer',
                      'Softwareentwickler Java']:
            with self.subTest(title=title):
                self.assertEqual(relevance(job(title), KEYWORDS)['level'], 'unconfirmed')
        terms = provider_terms(KEYWORDS)
        self.assertNotIn('quereinsteiger', terms)
        self.assertNotIn('teamleiter', terms)
        self.assertNotIn('rumaenischer', terms)

    def test_roles_and_multiword_requirements(self):
        cases = [('Bürohelferin (m/w/d)', 'Bürohilfe'),
            ('Bürokraft (m/w/d)', 'Bürokraft Quereinsteiger'),
            ('Persönlichen Assistenz (m/w/d)', 'Persönliche Assistenz'),
            ('Housekeeping Teamleitung', 'Housekeeping Supervisor'),
            ('Pflegehelferin', 'Pflegehelfer'),
            ('Sprachmittler für Rumänisch', 'Rumänischer Sprachmittler'),
            ('KI Automatisierung', 'KI Automatisierung')]
        for title, keyword in cases:
            with self.subTest(title=title):
                self.assertEqual(relevance(job(title), [keyword])['level'], 'title')
        self.assertEqual(relevance(job('Reinigungskraft Housekeeping'), ['Housekeeping Supervisor'])['level'], 'unconfirmed')
        self.assertEqual(relevance(job('Jobcoach', 'Englisch erforderlich'), ['Jobcoach Rumänisch'])['level'], 'unconfirmed')
        matched = relevance(job('Jobcoach', 'Rumänisch erforderlich'), ['Jobcoach Rumänisch'])
        self.assertEqual(matched['level'], 'description')
        self.assertEqual(relevance(job('Bürohilfe', 'KI Software im Büro'), ['KI Automatisierung'])['level'], 'unconfirmed')

    def test_unrelated_job_cannot_get_strong_score_from_preferences(self):
        scored = score_job(job('Verkäufer Quereinsteiger'), KEYWORDS, [], empty_analysis())
        self.assertLessEqual(scored['score'], 39)
        self.assertEqual(scored['relevance']['level'], 'unconfirmed')
        self.assertIn('Sin coincidencia clara', scored['why_recommended'])

    def test_title_matches_are_prioritized_over_mentions(self):
        rows = [{'status': 'new', 'score': score, 'relevance': {'level': level}}
                for level, score in [('unconfirmed', 39), ('description', 90), ('title', 50)]]
        self.assertEqual(sorted(rows, key=result_order)[0]['relevance']['level'], 'title')

    def test_today_uses_berlin_calendar_date_at_utc_boundary(self):
        # 00:30 on 8 October in Berlin is still 7 October UTC.
        now = datetime(2026, 10, 7, 22, 30, tzinfo=timezone.utc)
        with patch('app.filtering.datetime') as clock:
            clock.now.return_value = now
            offer = job('Bürohilfe')
            offer.date_posted = datetime(2026, 10, 7, 22, 10)
            params = SearchParams(keywords=['Bürohilfe'], max_age_days=0)
            self.assertEqual(evaluate_hard_filters(offer, params)['status'], 'new')
            offer.date_posted = datetime(2026, 10, 7, 21, 59)
            self.assertEqual(evaluate_hard_filters(offer, params)['excluded_reason'], 'TOO_OLD')
            offer.date_posted = None
            self.assertEqual(evaluate_hard_filters(offer, params)['status'], 'new')
        self.assertEqual(SettingsPayload(max_age_days=0, hard_rules={}, weights={}).max_age_days, 0)

if __name__ == '__main__':
    unittest.main()
