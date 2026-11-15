import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from fastapi.testclient import TestClient
from drivebrief_api.app import create_app
from drivebrief_api.pipeline_settings import load_config
from drivebrief_api.planning import plan, estimate
from drivebrief_api.summary_inputs import selected_inputs
from drivebrief_api.review import ReviewStore
from drivebrief_summary.providers import MockProvider
from drivebrief_summary.errors import SummaryError

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 13, tzinfo=timezone.utc)


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ReviewStore(Path(self.tmp.name)/"review.sqlite3")
        self.records = json.loads((ROOT/"samples/pipeline_articles.json").read_text())
        self.cfg = load_config()
        self.provider = MockProvider()
        self.store.generate(self.records, self.provider, Path(self.tmp.name)/"cache.sqlite3")
        for r in self.records:
            doc = self.store.review_document(r["article"]["id"])
            self.store.decide(r["article"]["id"], "test-only-reviewer", "approved", doc["revision"])
        self.document = self.store.briefing()

    def test_options_prefixes_time_and_no_text_changes(self):
        original = {a["article_id"]: a for a in self.document["articles"]}
        for option in ("짧게", "중간", "길게"):
            result = plan(self.document, option, [], self.cfg, NOW)
            self.assertLessEqual(result["estimated_seconds"], result["target_seconds"])
            self.assertAlmostEqual(result["estimated_seconds"]-result["target_seconds"], result["delta_seconds"])
            for a in result["articles"]:
                source = original[a["article_id"]]
                self.assertEqual(source["tts_sentences"][:len(a["tts_sentences"])], a["tts_sentences"])
                self.assertEqual(source["detail"], a["detail"])
                self.assertEqual(list(range(len(a["tts_sentences"]))), a["sentence_indices"])
            self.assertEqual("development_placeholder_not_team_policy", result["policy_status"])

    def test_empty_shortage_oversized_and_repeats(self):
        empty = dict(self.document, articles=[])
        self.assertEqual([], plan(empty, "중간", [], self.cfg, NOW)["articles"])
        cfg = copy.deepcopy(self.cfg); cfg["length_seconds"]["짧게"] = 1
        self.assertEqual("no_fitting_approved_articles", plan(self.document, "짧게", [], cfg, NOW)["status"])
        result = plan(self.document, "길게", [], self.cfg, NOW)
        self.assertTrue(result["shortage"])
        sentences = [s for a in result["articles"] for s in a["tts_sentences"]]
        self.assertEqual(len(sentences), len(set(sentences)))

    def test_estimate_and_determinism(self):
        self.assertAlmostEqual(10/self.cfg["characters_per_second"]+self.cfg["sentence_pause_seconds"], estimate("가"*10, self.cfg))
        a = plan(self.document, "중간", ["사회"], self.cfg, NOW, {"fiction-02": ["사회"]})
        b = plan(dict(self.document, articles=list(reversed(self.document["articles"]))), "중간", ["사회"], self.cfg, NOW, {"fiction-02": ["사회"]})
        self.assertEqual(a, b)
        self.assertEqual("fiction-02", a["articles"][0]["article_id"])

    def test_unapproved_and_real_news_blocked(self):
        doc = copy.deepcopy(self.document)
        doc["articles"][0]["validation"]["approved"] = False
        with self.assertRaises(ValueError): plan(doc, "중간", [], self.cfg, NOW)
        records = copy.deepcopy(self.records)
        records[0]["article"]["rights"]["kind"] = "unverified"
        with self.assertRaises((SummaryError, ValueError)):
            selected_inputs(["fiction-01"], records)
        with self.assertRaises(ValueError): selected_inputs(["rss_no_body"], self.records)
        with self.assertRaises(ValueError): selected_inputs(["fiction-01", "fiction-01"], self.records)
        self.assertEqual(3, len(selected_inputs([r["article"]["id"] for r in self.records], self.records)))

    def test_api_compatibility_and_validation(self):
        client = TestClient(create_app(review_store=self.store))
        current = client.get("/v1/briefings/current")
        self.assertEqual(200, current.status_code)
        self.assertNotIn("briefing_id", current.json())
        response = client.get("/v1/briefings/plan?length=짧게&categories=사회")
        self.assertEqual(200, response.status_code)
        self.assertEqual("짧게", response.json()["length_option"])
        self.assertEqual("approved-briefing-v1", response.json()["schema_version"])
        self.assertEqual(422, client.get("/v1/briefings/plan?length=10").status_code)
        self.assertEqual(422, client.get("/v1/briefings/plan?categories=unknown").status_code)

    def test_configuration_invalid_rejected(self):
        for mutate in (lambda c: c["length_seconds"].update({"짧게": -1}),
                       lambda c: c["weights"].update({"recency": 9}),
                       lambda c: c.update(characters_per_second=float("nan"))):
            cfg = copy.deepcopy(self.cfg); mutate(cfg)
            file = Path(self.tmp.name)/"bad.json"; file.write_text(json.dumps(cfg))
            with self.assertRaises(ValueError): load_config(file)

    def test_rank_pool_is_not_limited_to_legacy_first_ten(self):
        from unittest.mock import patch
        added = []
        for i in range(11):
            record = copy.deepcopy(self.records[0])
            record["article"]["id"] = "rank-%02d" % i
            record["article"]["title"] = "자체 시험 추가 뉴스 %d" % i
            added.append(record)
        self.store.generate(added, self.provider, Path(self.tmp.name)/"extra.sqlite3")
        for record in added:
            doc = self.store.review_document(record["article"]["id"])
            self.store.decide(record["article"]["id"], "test-only", "approved", doc["revision"])
        self.assertEqual(10, len(self.store.briefing()["articles"]))
        self.assertEqual(14, len(self.store.briefing(limit=None)["articles"]))
        category_file = Path(self.tmp.name)/"categories.json"
        category_file.write_text(json.dumps({"rank-10": ["IT"]}))
        with patch("drivebrief_api.planning.SAMPLE_CATEGORIES", category_file):
            response = TestClient(create_app(review_store=self.store)).get("/v1/briefings/plan?length=중간&categories=IT")
        self.assertEqual(200, response.status_code)
        self.assertEqual("rank-10", response.json()["articles"][0]["article_id"])
