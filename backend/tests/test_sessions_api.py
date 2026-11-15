from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from drivebrief_api.app import create_app
from drivebrief_api.sessions import SessionStore


class SessionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.article = dict(article_id='a', title='테스트', category='IT', source='합성 테스트',
            source_url='https://example.org/a', published_at='2026-11-13T10:00:00+09:00',
            tts_sentences=['합성 문장입니다.'], one_line='합성 한 줄', detail='합성 상세', mock=True,
            summary_length='short', validation={'status': 'approved', 'approved': True, 'review_required': False})
        store = SessionStore(Path(self.temp.name) / 'session.sqlite3')
        self.client = TestClient(create_app(session_store=store, briefing_catalog=lambda: [self.article]))

    def test_request_event_and_onepaper(self):
        response = self.client.post('/v1/briefings', json={'categories': ['IT'], 'length': 'short'})
        self.assertEqual(response.status_code, 201)
        session = response.json()
        sid = session['session_id']
        self.assertTrue(session['articles'][0]['mock'])
        event = dict(event_id='e1', article_id='a', sequence=0, state='completed', completed_sentences=1, bookmarked=True)
        url = f'/v1/sessions/{sid}/events'
        self.assertEqual(self.client.post(url, json=event).status_code, 200)
        self.assertTrue(self.client.post(url, json=event).json()['duplicate'])
        self.assertEqual(self.client.post(url, json=dict(event, bookmarked=False)).status_code, 409)
        paper = self.client.get(f'/v1/sessions/{sid}/onepaper')
        self.assertEqual(paper.status_code, 200)
        self.assertEqual(paper.json()['articles'][0]['state'], 'completed')
        self.assertNotIn('body', paper.json()['articles'][0])

    def test_strict_requests_and_unknown_session(self):
        for payload in [{'categories': []}, {'categories': ['IT'], 'length': '10'},
                        {'categories': ['IT'], 'budget_seconds': True}, {'categories': ['IT'], 'extra': 1}]:
            self.assertEqual(self.client.post('/v1/briefings', json=payload).status_code, 422)
        self.assertEqual(self.client.get('/v1/sessions/missing/onepaper').status_code, 404)

    def test_does_not_substitute_other_length(self):
        response = self.client.post('/v1/briefings', json={'categories': ['IT'], 'length': 'long'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['articles'], [])
