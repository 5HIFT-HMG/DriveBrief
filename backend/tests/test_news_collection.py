from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from drivebrief_api.app import create_app
from drivebrief_api.news_collector import NewsCollector
from drivebrief_api.news_repository import NewsRepository, crawler


class NewsCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.config = root / 'config.json'
        self.feed = {'url': 'https://example.com/rss', 'category': 'IT', 'source': 'fixture'}
        self.config.write_text(json.dumps({'feeds': [self.feed]}))
        self.repo = NewsRepository(root / 'news.sqlite3', self.config)

    def article(self, name):
        return {'url': 'https://example.com/' + name, 'title': name, 'description': 'fixture',
                'published_at': datetime.now(timezone.utc).isoformat()}

    def test_collection_updates_the_database_used_by_api_and_retains_data_on_failure(self):
        collector = NewsCollector(self.repo)
        with patch.object(crawler, 'fetch', return_value=(self.feed, [self.article('first')], 0, None)):
            self.assertEqual(collector.collect_once(), 1)
        with patch.object(crawler, 'fetch', return_value=(self.feed, [self.article('second')], 0, None)):
            self.assertEqual(collector.collect_once(), 1)
        client = TestClient(create_app(news_repository=self.repo))
        self.assertEqual(client.get('/v1/news?category=IT').json()['total_candidates'], 2)
        with patch.object(crawler, 'fetch', return_value=(self.feed, [], 0, 'fixture failure')):
            self.assertEqual(collector.collect_once(), 0)
        status = client.get('/v1/news/status').json()
        self.assertTrue(status['database_available'])
        self.assertEqual(status['article_count'], 2)
        self.assertEqual(status['failed_feed_count'], 1)
        self.assertIsNotNone(status['last_success_at'])

    def test_api_lifespan_starts_collection_and_stops_it(self):
        api = create_app(news_repository=self.repo, collect_news=True)
        with patch.object(crawler, 'fetch', return_value=(self.feed, [self.article('startup')], 0, None)):
            with TestClient(api) as client:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    status = client.get('/v1/news/status').json()
                    if status['article_count'] == 1:
                        break
                    time.sleep(.01)
                self.assertEqual(status['article_count'], 1)
                self.assertTrue(status['collector_running'])
                self.assertFalse(status['stale'])
                self.assertEqual(status['interval_seconds'], 300)
        self.assertFalse(api.state.news_collector.running)
        self.assertFalse(api.state.news_collector.thread.is_alive())

    def test_old_success_is_stale_and_failed_cycle_can_recover(self):
        collector = NewsCollector(self.repo)
        with patch.object(crawler, 'fetch', return_value=(self.feed, [self.article('old')], 0, None)):
            collector.collect_once()
        old = (datetime.now(timezone.utc) - timedelta(days=6)).isoformat()
        with crawler.connect(self.repo.db_path) as db:
            db.execute('UPDATE feed_status SET last_success=?', (old,))
        self.assertTrue(self.repo.collection_status()['stale'])
        with patch.object(crawler, 'fetch', return_value=(self.feed, [], 0, 'offline')):
            collector.collect_once()
        self.assertTrue(self.repo.collection_status()['stale'])
        with patch.object(crawler, 'fetch', return_value=(self.feed, [self.article('new')], 0, None)):
            collector.collect_once()
        status = self.repo.collection_status()
        self.assertFalse(status['stale'])
        self.assertEqual(status['article_count'], 2)
        self.assertEqual(status['failed_feed_count'], 0)

    def test_missing_database_and_too_frequent_collection(self):
        self.assertTrue(self.repo.collection_status()['stale'])
        self.assertFalse(self.repo.collection_status()['database_available'])
        with self.assertRaises(ValueError):
            NewsCollector(self.repo, 1)

    def test_worker_retries_next_cycle_after_failure(self):
        collector = NewsCollector(self.repo)
        with patch.object(collector, 'collect_once', side_effect=[OSError('offline'), 1]) as collect:
            with patch.object(collector.stop_event, 'wait', side_effect=[False, True]) as wait:
                collector.run()
        self.assertEqual(collect.call_count, 2)
        self.assertEqual(wait.call_args_list[0].args, (300,))
        self.assertIsNone(collector.last_error)
