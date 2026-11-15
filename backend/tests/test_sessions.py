import copy
import json
from pathlib import Path
import tempfile
import unittest
from drivebrief_api.sessions import SessionStore, select_articles
from drivebrief_api.real_news import RealReviewStore, RealArticle
from drivebrief_api.review import InputArticle, ReviewStore
from drivebrief_summary.providers import MockProvider


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SessionStore(Path(self.temp.name) / 'sessions.sqlite3')
        self.article = dict(article_id='a', title='기사 제목', category='IT', source='시험', source_url='https://example.org/a', published_at='2026-11-13T10:00:00+09:00', tts_sentences=['문장 하나.', '문장 둘.', '문장 셋.'], one_line='한 줄', detail='전체 상세 요약', mock=True, validation={'approved': True})

    def test_length_filter_dedup_budget(self):
        duplicate = dict(self.article, article_id='duplicate')
        unapproved = dict(self.article, article_id='blocked', title='다른 기사', validation={'approved': False})
        for length, count in [('short', 1), ('medium', 2), ('long', 3)]:
            rows, seconds = select_articles([self.article, duplicate, unapproved], ['IT'], length)
            self.assertEqual(len(rows), 1)
            self.assertEqual(len(rows[0]['tts_sentences']), count)
            self.assertGreater(seconds, 0)
        self.assertEqual(select_articles([self.article], ['경제'], 'medium')[0], [])
        long = dict(self.article, tts_sentences=['긴 문장입니다. ' * 100])
        self.assertEqual(select_articles([long], ['IT'], 'short', 30)[0], [])

    def test_session_snapshot_idempotence_and_onepaper(self):
        session = self.store.create([self.article], ['IT'], 'medium')
        sid = session['session_id']
        self.article['detail'] = '나중에 변경'
        event = dict(event_id='one', article_id='a', sequence=0, state='interrupted', completed_sentences=1, bookmarked=True)
        self.assertFalse(self.store.record(sid, event)['duplicate'])
        self.assertTrue(self.store.record(sid, event)['duplicate'])
        with self.assertRaises(ValueError):
            self.store.record(sid, dict(event, bookmarked=False))
        paper = self.store.onepaper(sid)['articles'][0]
        self.assertEqual(paper['state'], 'interrupted')
        self.assertTrue(paper['bookmarked'])
        self.assertEqual(paper['detail'], '전체 상세 요약')
        self.assertEqual(paper['summary_scope'], 'full_article')
        with self.assertRaises(ValueError):
            self.store.record(sid, dict(event, event_id='bad', sequence=1, state='completed'))
        self.store.record(sid, dict(event, event_id='two', sequence=1, state='completed', completed_sentences=2))
        self.assertEqual(self.store.onepaper(sid)['articles'][0]['state'], 'completed')
        with self.assertRaises(ValueError):
            self.store.record(sid, dict(event, event_id='stale'))
        with self.assertRaises(ValueError):
            self.store.record(sid, dict(event, event_id='foreign', article_id='other'))
        with self.assertRaises(LookupError):
            self.store.onepaper('unknown')

    def test_unplayed_does_not_claim_listening(self):
        sid = self.store.create([self.article], ['IT'], 'long')['session_id']
        item = self.store.onepaper(sid)['articles'][0]
        self.assertEqual(item['state'], 'unplayed')
        self.assertEqual(item['completed_sentences'], 0)
        event = dict(event_id='bookmark', article_id='a', sequence=0, state='unplayed', completed_sentences=0, bookmarked=True)
        self.store.record(sid, event)
        item = self.store.onepaper(sid)['articles'][0]
        self.assertEqual(item['state'], 'unplayed')
        self.assertTrue(item['bookmarked'])

    def test_licensed_review_reuses_existing_checks_and_revokes_changed_source(self):
        record = json.loads(Path('samples/pipeline_articles.json').read_text())[0]
        with self.assertRaises(ValueError):
            RealArticle.model_validate(dict(record, category='IT')).checked()
        record['article']['rights']['kind'] = 'licensed'
        with self.assertRaises(ValueError):
            InputArticle.model_validate(record).checked()
        record['category'] = 'IT'
        store = RealReviewStore(Path(self.temp.name) / 'reviews.sqlite3')
        cache = Path(self.temp.name) / 'cache.sqlite3'
        self.assertEqual(store.generate([record], MockProvider(), cache)[0]['status'], 'needs_review')
        doc = store.review_document(record['article']['id'])
        store.decide(record['article']['id'], 'test-fixture-reviewer', 'approved', doc['revision'])
        result = store.briefing()
        self.assertFalse(result['fictional_only'])
        self.assertTrue(result['articles'][0]['mock'])
        self.assertEqual(result['articles'][0]['category'], 'IT')
        record['article']['rights']['external_llm_allowed'] = False
        self.assertEqual(store.generate([record], MockProvider(), cache)[0]['status'], 'failed')
        self.assertEqual(store.briefing()['articles'], [])

class LengthGenerationTests(unittest.TestCase):
    def test_length_variants_generate_independent_cached_summaries(self):
        from drivebrief_summary.models import Article
        from drivebrief_summary.service import Summarizer
        article = Article.model_validate(json.loads(Path('samples/pipeline_articles.json').read_text())[0]['article'])
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / 'summary.sqlite3'
            for length, count in [('short', 1), ('medium', 2), ('long', 3)]:
                provider = MockProvider(length)
                service = Summarizer(provider, cache)
                first = service.summarize(article)
                second = service.summarize(article)
                self.assertEqual(len(first['result']['tts_sentences']), count)
                self.assertFalse(first['provenance']['cached'])
                self.assertTrue(second['provenance']['cached'])
                self.assertEqual(provider.calls, 1)
                self.assertFalse(first['validation']['approved'])

    def test_catalog_does_not_substitute_other_length(self):
        article = dict(article_id='a', title='제목', category='IT', published_at='2026-11-13',
                       tts_sentences=['문장'], summary_length='short', validation={'approved': True})
        self.assertEqual(select_articles([article], ['IT'], 'long')[0], [])
