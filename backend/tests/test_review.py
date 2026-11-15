import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from drivebrief_api.review import ReviewStore, InputArticle, main
from drivebrief_api.app import create_app
from drivebrief_summary.providers import MockProvider
from drivebrief_summary.errors import SummaryError

ROOT = Path(__file__).resolve().parents[1]


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ReviewStore(Path(self.temp.name) / "review.sqlite3")
        self.cache = Path(self.temp.name) / "summaries.sqlite3"
        self.records = json.loads((ROOT / "samples/pipeline_articles.json").read_text())
        self.provider = MockProvider()

    def generate(self):
        return self.store.generate(self.records, self.provider, self.cache)

    def approve(self, record, edited=None):
        article_id = record["article"]["id"]
        doc = self.store.review_document(article_id)
        self.store.decide(article_id, "test-reviewer", "approved", doc["revision"], edited)

    def test_three_and_cache_no_automatic_approval(self):
        with patch("drivebrief_summary.providers.build_opener", side_effect=AssertionError):
            self.assertTrue(all(r["status"] == "needs_review" for r in self.generate()))
            self.assertEqual(3, self.provider.calls)
            self.assertTrue(all(r["cached"] for r in self.generate()))
            self.assertEqual(3, self.provider.calls)
            self.assertEqual([], self.store.briefing()["articles"])

    def test_approval_and_no_internal_data(self):
        self.generate()
        for r in self.records:
            self.approve(r)
        response = TestClient(create_app(review_store=self.store)).get("/v1/briefings/current")
        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual(3, len(data["articles"]))
        self.assertTrue(all(a["validation"]["approved"] and a["mock"] for a in data["articles"]))
        for key in ("evidence_links", "reviewer", "body", "GROQ_API_KEY", "source_spans"):
            self.assertNotIn(key, response.text)

    def test_reject_excluded_and_stale_revision(self):
        self.generate()
        self.approve(self.records[0])
        article_id = self.records[0]["article"]["id"]
        doc = self.store.review_document(article_id)
        self.store.decide(article_id, "test", "rejected", doc["revision"])
        self.assertEqual([], self.store.briefing()["articles"])
        with self.assertRaises(ValueError):
            self.store.decide(article_id, "test", "approved", "stale")

    def test_edited_approval_revalidates_ids_numbers(self):
        self.generate()
        doc = self.store.review_document(self.records[0]["article"]["id"])
        draft = copy.deepcopy(doc["draft"])
        draft["evidence_links"][0]["evidence_ids"] = ["nonexistent"]
        with self.assertRaises(SummaryError):
            self.approve(self.records[0], draft)
        draft = copy.deepcopy(doc["draft"])
        draft["tts_sentences"][0] += " 999999명입니다."
        with self.assertRaises(SummaryError):
            self.approve(self.records[0], draft)
        # A safe punctuation edit remains reviewable, and approval requires explicit decision.
        draft = copy.deepcopy(doc["draft"])
        draft["tts_sentences"][0] += " "
        self.approve(self.records[0], draft)
        self.assertEqual(1, len(self.store.briefing()["articles"]))

    def test_source_change_revokes_and_tamper_fails_closed(self):
        self.generate()
        self.approve(self.records[0])
        self.records[0]["article"]["title"] += " 수정"
        self.generate()
        self.assertEqual([], self.store.briefing()["articles"])
        self.approve(self.records[0])
        with sqlite3.connect(str(self.store.path)) as db:
            db.execute("UPDATE reviews SET draft=? WHERE id=?", ("{}", self.records[0]["article"]["id"]))
        self.assertEqual(503, TestClient(create_app(review_store=self.store)).get("/v1/briefings/current").status_code)

    def test_failure_isolated_and_rss_denied(self):
        records = copy.deepcopy(self.records)
        records[1]["article"]["rights"]["kind"] = "unverified"
        results = self.store.generate(records, self.provider, self.cache)
        self.assertEqual(["needs_review", "failed", "needs_review"], [r["status"] for r in results])
        self.assertEqual(2, self.provider.calls)
        records[1]["article"]["rights"]["kind"] = "licensed"
        self.assertEqual("failed", self.store.generate([records[1]], self.provider, self.cache)[0]["status"])

    def test_provider_failure_does_not_abort_batch(self):
        original = self.provider.generate
        def generate(article):
            if article.id == self.records[1]["article"]["id"]:
                raise SummaryError("provider_network", "test")
            return original(article)
        self.provider.generate = generate
        self.assertEqual(["needs_review", "failed", "needs_review"], [r["status"] for r in self.generate()])

    def test_empty_store_and_inspection_evidence(self):
        self.assertEqual([], TestClient(create_app(review_store=self.store)).get("/v1/briefings/current").json()["articles"])
        self.assertFalse(self.store.path.exists())  # API never creates review DB
        self.generate()
        doc = self.store.review_document(self.records[0]["article"]["id"])
        self.assertTrue(doc["source_spans"])
        self.assertTrue(doc["result"]["evidence_snippets"])
        self.assertFalse(doc["validation"]["approved"])

    def test_cli_requires_two_external_optins_and_human_confirmation(self):
        import sys
        with patch.object(sys, "argv", ["review", "generate", "--input", str(ROOT / "samples/pipeline_articles.json"), "--provider", "groq"]), patch("drivebrief_summary.providers.build_opener", side_effect=AssertionError):
            self.assertEqual(1, main())
        with patch.object(sys, "argv", ["review", "decide", "--id", "x", "--reviewer", "test", "--decision", "approved", "--revision", "x"]):
            self.assertEqual(1, main())

    def test_same_input_keeps_approval_but_permission_failure_revokes(self):
        self.generate()
        self.approve(self.records[0])
        self.generate()
        self.assertEqual(1, len(self.store.briefing()["articles"]))
        self.records[0]["article"]["rights"]["external_llm_allowed"] = False
        self.assertEqual("failed", self.store.generate([self.records[0]], self.provider, self.cache)[0]["status"])
        self.assertEqual([], self.store.briefing()["articles"])
