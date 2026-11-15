from contextlib import ExitStack
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from drivebrief_api import pipeline, real_news
from drivebrief_api.real_news import RealReviewStore
from drivebrief_api.sessions import SessionStore

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class PipelineTests(unittest.TestCase):
    def test_rss_body_three_summaries_review_session_event_onepaper(self):
        crawler = load('test_pipeline_crawler', ROOT / 'news_crawler/news.py')
        body_module = load('test_pipeline_body', ROOT / 'news_crawler/full_text.py')
        sample = json.loads((ROOT / 'backend/samples/pipeline_articles.json').read_text())[0]['article']
        feed = {'url': 'https://fixture.example.org/rss', 'source': sample['source'], 'category': 'IT'}
        article = {'url': 'https://fixture.example.org/a', 'title': sample['title'],
                   'description': '합성 RSS 설명', 'published_at': datetime.now(timezone.utc).isoformat()}
        rights = dict(sample['rights'], kind='licensed', basis='Synthetic fixture only; no real source permission claimed')
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            # collect() imports shared_db dynamically; never let a local fixture reach a configured DB.
            stack.enter_context(patch("urllib.request.urlopen", side_effect=AssertionError("offline_test_network_forbidden")))
            root = Path(folder)
            news_folder = root / 'news_crawler'
            news_folder.mkdir()
            config = news_folder / 'config.json'
            config.write_text(json.dumps({'feeds': [feed], 'body_sources': {'fixture.example.org':
                {'collection_allowed': True, 'rights': rights}}}))
            news_db = news_folder / 'news.sqlite3'
            review_db = root / 'review.sqlite3'
            stack.enter_context(patch.object(pipeline, 'module', side_effect=lambda name, path: crawler if name == 'pipeline_crawler' else body_module))
            stack.enter_context(patch.object(crawler, 'fetch', return_value=(feed, [article], 0, None)))
            stack.enter_context(patch.object(body_module, 'fetch_body', return_value=(sample['body'], 'fixture')))
            result = pipeline.cycle(news_db, config, review_db, 'mock', ('short', 'medium', 'long'))
            self.assertEqual(result['feed_successes'], 1)
            self.assertEqual(result['body_successes'], 1)
            self.assertFalse(result['automatic_approval'])
            reviews = RealReviewStore(review_db)
            self.assertEqual(reviews.briefing()['articles'], [])
            for row in reviews.rows():
                doc = reviews.review_document(row[0])
                reviews.decide(row[0], 'test-fixture-only', 'approved', doc['revision'])
            stack.enter_context(patch.object(real_news, 'ROOT', root))
            stack.enter_context(patch.object(real_news, 'RealReviewStore', return_value=reviews))
            catalog = real_news.current_catalog()
            self.assertEqual(len(catalog), 3)
            for length, count in [('short', 1), ('medium', 2), ('long', 3)]:
                sessions = SessionStore(root / 'sessions.sqlite3')
                session = sessions.create(catalog, ['IT'], length)
                item = session['articles'][0]
                self.assertEqual(len(item['tts_sentences']), count)
                self.assertTrue(item['mock'])
                sessions.record(session['session_id'], dict(event_id=length, article_id=item['article_id'],
                    sequence=0, state='completed', completed_sentences=count, bookmarked=True))
                paper = sessions.onepaper(session['session_id'])['articles'][0]
                self.assertEqual(paper['state'], 'completed')
                self.assertEqual(paper['summary_scope'], 'full_article')
            config.write_text(json.dumps({'body_sources': {}}))
            self.assertEqual(real_news.current_catalog(), [])

    def test_groq_without_configuration_fails_before_collection(self):
        with patch.dict('os.environ', {'GROQ_API_KEY': '', 'DRIVEBRIEF_ALLOW_GROQ': ''}), patch.object(pipeline, 'module') as loader:
            with self.assertRaises(ValueError):
                pipeline.cycle('unused', 'unused', 'unused', 'groq', ('medium',), True)
            loader.assert_not_called()
