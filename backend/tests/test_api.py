import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from drivebrief_api.app import create_app
from drivebrief_summary.models import Article
from drivebrief_summary.providers import MockProvider
from drivebrief_summary.validation import resolve_draft

ROOT = Path(__file__).resolve().parents[1]


class DemoApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sources = ROOT / "samples/articles.json"
        # Synthetic stored-result fixture; tests never require an ignored real Groq result file.
        article = Article.model_validate(json.loads(self.sources.read_text(encoding="utf-8"))[0])
        raw = MockProvider().generate(article)
        result, validation, links = resolve_draft(raw, article)
        document = {"mode": "groq", "articles": [{
            "article_id": article.id, "result": result.model_dump(), "validation": validation,
            "evidence_links": links,
            "provenance": {"provider": "groq", "mock": False, "approved": False, "review_required": True},
        }]}
        self.result = Path(self.temp.name) / "saved-fixture.json"
        self.result.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    def client(self, result=None, sources=None, enabled=True):
        return TestClient(create_app(result or self.result, sources or self.sources, enabled))

    def get(self, client):
        return client.get("/v1/demo/briefing?allow_unreviewed_fictional=true")

    def modified(self, change):
        document = json.loads(self.result.read_text(encoding="utf-8"))
        change(document)
        path = Path(self.temp.name) / "result.json"
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        return path

    def test_health_and_explicit_opt_in(self):
        self.assertEqual("ok", self.client().get("/healthz").json()["status"])
        self.assertEqual(403, self.client().get("/v1/demo/briefing").status_code)
        self.assertEqual(403, self.get(self.client(enabled=False)).status_code)
        self.assertEqual(422, self.client().post("/v1/briefings").status_code)
        self.assertEqual(405, self.client().get("/v1/briefings").status_code)

    def test_success_whitelists_response_and_preserves_tts(self):
        # Any attempt to use the Groq transport would fail this test before network IO.
        with patch("drivebrief_summary.providers.build_opener", side_effect=AssertionError("network forbidden")):
            response = self.get(self.client())
        self.assertEqual(200, response.status_code)
        data = response.json()
        saved = json.loads(self.result.read_text(encoding="utf-8"))
        source = json.loads(self.sources.read_text(encoding="utf-8"))[0]
        self.assertTrue(data["demo_only"])
        item = data["articles"][0]
        self.assertEqual(source["title"], item["title"])
        self.assertEqual(source["source"], item["source"])
        self.assertEqual(saved["articles"][0]["result"]["tts_sentences"], item["tts_sentences"])
        self.assertFalse(item["validation"]["approved"])
        self.assertNotIn("provenance", item)
        self.assertNotIn("body", item)
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_missing_file_and_invalid_json(self):
        missing = Path(self.temp.name) / "missing.json"
        self.assertEqual(503, self.get(self.client(result=missing)).status_code)
        missing.write_text("{invalid", encoding="utf-8")
        response = self.get(self.client(result=missing))
        self.assertEqual(500, response.status_code)
        self.assertEqual({"code": "demo_data_invalid"}, response.json()["detail"])

    def test_invalid_source_id_and_fictional_permission(self):
        path = self.modified(lambda d: d["articles"][0].update(article_id="unknown"))
        self.assertEqual(500, self.get(self.client(result=path)).status_code)
        source = json.loads(self.sources.read_text(encoding="utf-8"))
        source[0]["rights"]["kind"] = "licensed"
        path = Path(self.temp.name) / "sources.json"
        path.write_text(json.dumps(source), encoding="utf-8")
        self.assertEqual(500, self.get(self.client(sources=path)).status_code)

    def test_tampered_validation_or_model_quote_rejected(self):
        for change in [
            lambda d: d["articles"][0]["validation"].update(approved=True),
            lambda d: d["articles"][0]["result"]["evidence_snippets"][0].update(quote="tampered"),
            lambda d: d["articles"][0]["evidence_links"][0].update(evidence_ids=["unknown"]),
        ]:
            path = self.modified(change)
            self.assertEqual(500, self.get(self.client(result=path)).status_code)

    def test_empty_list_is_explicit(self):
        path = self.modified(lambda d: d.update(articles=[]))
        response = self.get(self.client(result=path))
        self.assertEqual(200, response.status_code)
        self.assertEqual([], response.json()["articles"])
