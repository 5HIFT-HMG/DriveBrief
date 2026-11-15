from contextlib import closing
from datetime import date
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from fastapi.testclient import TestClient
from drivebrief_api.app import create_app
from drivebrief_api.news_repository import NewsRepository, crawler


class NewsCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "fixture.sqlite3"
        self.config = Path(self.temp.name) / "config.json"
        self.config.write_text(json.dumps({"candidate_limits": {c: 100 for c in crawler.CATEGORIES}}))
        self.db = crawler.connect(self.path)  # schema in isolated test fixture only
        self.addCleanup(self.db.close)
        self.add("https://example.com/a?utm_source=x", "같은 제목", "2020-01-01T01:00:00+09:00", "IT")
        self.add("https://example.com/a", "다른 판본 제목", "2026-11-06T10:00:00+09:00", "IT")
        self.add("https://example.com/b", "같은 제목", "2026-11-06T09:00:00+09:00", "IT")
        self.add("https://example.com/c", "경제 기사", "2026-11-07T10:00:00+09:00", "경제")
        self.db.commit()
        self.repo = NewsRepository(self.path, self.config)
        self.client = TestClient(create_app(news_repository=self.repo))

    def add(self, url, title, published, category):
        self.db.execute("INSERT INTO articles VALUES (?,?,?,?,?,?)", (url, title, "RSS 설명", published, published, published))
        self.db.execute("INSERT INTO memberships VALUES (?,?,?)", (url, category, "테스트 출처"))

    def test_all_history_latest_order_and_alias_dedup(self):
        rows = crawler.get_candidates(self.db)
        self.assertEqual(2, len(rows))
        self.assertEqual("경제 기사", rows[0]["title"])
        self.assertEqual("다른 판본 제목", rows[1]["title"])
        self.add("https://example.com/old", "오래된 별도 기사", "2020-01-02T00:00:00+09:00", "사회")
        self.assertEqual(3, len(crawler.get_candidates(self.db)))

    def test_category_date_and_interest_filters(self):
        self.assertEqual(1, len(crawler.get_candidates(self.db, category="IT")))
        self.assertEqual(1, len(crawler.get_candidates(self.db, day=date(2026, 11, 7))))
        self.assertEqual(2, len(crawler.get_candidates(self.db, category=["IT", "경제"])))
        self.assertEqual([], crawler.get_candidates(self.db, category=[]))

    def test_limits_offset_and_configuration(self):
        self.add("https://example.com/d", "다른 IT 기사", "2026-11-07T09:00:00+09:00", "IT")
        page = crawler.candidate_page(self.db, limit=1)
        self.assertEqual(1, len(page["articles"]))
        self.assertTrue(page["has_more"])
        second = crawler.candidate_page(self.db, limit=1, offset=1)
        self.assertNotEqual(page["articles"][0]["url"], second["articles"][0]["url"])
        capped = crawler.candidate_page(self.db, per_category_limit=1)
        self.assertEqual(2, capped["available_count"])
        self.assertEqual(3, crawler.candidate_page(self.db, per_category_limit=0)["available_count"])

    def test_different_events_with_different_titles_are_not_semantically_merged(self):
        self.add("https://example.com/event1", "AI 행사 개최", "2026-11-07T09:00:00+09:00", "IT")
        self.add("https://example.com/event2", "인공지능 행사 열려", "2026-11-07T08:00:00+09:00", "IT")
        self.assertEqual(4, len(crawler.get_candidates(self.db)))

    def test_api_policy_metadata_and_no_external_calls(self):
        with patch.object(crawler, "fetch", side_effect=AssertionError("collection forbidden")), patch(
                "drivebrief_summary.providers.build_opener", side_effect=AssertionError("LLM forbidden")):
            response = self.client.get("/v1/news?category=IT&limit=20")
        self.assertEqual(200, response.status_code)
        item = response.json()["articles"][0]
        self.assertEqual("rss_description", item["content_level"])
        self.assertEqual("not_available", item["summary_status"])
        self.assertFalse(item["ai_eligible"])
        self.assertNotIn("tts_sentences", item)
        self.assertNotIn("body", item)
        self.assertTrue(item["article_id"].startswith("rss_"))
        self.assertEqual(200, self.client.get("/v1/news?categories=IT&categories=경제").status_code)

    def test_invalid_api_requests(self):
        for query in ["category=wrong", "limit=0", "limit=101", "offset=-1", "date=2026-02-30",
                      "per_category_limit=-1", "category=IT&categories=경제"]:
            self.assertEqual(422, self.client.get("/v1/news?" + query).status_code)

    def test_empty_database_and_missing_database(self):
        self.db.execute("DELETE FROM memberships")
        self.db.execute("DELETE FROM articles")
        self.db.commit()
        self.assertEqual([], self.client.get("/v1/news").json()["articles"])
        missing = Path(self.temp.name) / "missing.sqlite3"
        client = TestClient(create_app(news_repository=NewsRepository(missing, self.config)))
        self.assertEqual(503, client.get("/v1/news").status_code)
        self.assertFalse(missing.exists())

    def test_read_only_does_not_change_schema_or_rows(self):
        before = self.path.read_bytes()
        self.client.get("/v1/news")
        self.assertEqual(before, self.path.read_bytes())
        with closing(crawler.connect_read_only(self.path)) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("DELETE FROM articles")

    def test_old_top_five_selection_is_preserved(self):
        rows = [dict(title=str(i), url="https://example.com/" + str(i), description="", category="IT",
                     published_at="2026-11-07T09:00:00+09:00") for i in range(8)]
        self.assertEqual(5, len(crawler.select_articles(rows, [], 5)["IT"]))

    def test_fetch_timeout_http_and_bad_xml_preserve_existing_rows(self):
        feed = {"url": "https://example.com/rss", "category": "IT", "source": "테스트"}
        count = self.db.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        for error in [TimeoutError(), HTTPError(feed["url"], 503, "failure", {}, io.BytesIO(b""))]:
            with patch.object(crawler, "urlopen", side_effect=error):
                self.assertIsNotNone(crawler.fetch(feed)[3])
        with patch.object(crawler, "urlopen", return_value=io.BytesIO(b"bad xml")):
            self.assertIsNotNone(crawler.fetch(feed)[3])
        with patch.object(crawler, "fetch", return_value=(feed, [], 0, "failure")), patch("sys.stdout", new_callable=io.StringIO):
            crawler.collect(self.db, [feed])
        self.assertEqual(count, self.db.execute("SELECT COUNT(*) FROM articles").fetchone()[0])
