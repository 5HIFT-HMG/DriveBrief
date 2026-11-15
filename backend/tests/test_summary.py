import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from pydantic import ValidationError
from drivebrief_summary.errors import SummaryError
from drivebrief_summary.models import Article
from drivebrief_summary.providers import GroqProvider, MockProvider, Settings, NoRedirect
from drivebrief_summary.service import Summarizer, validate_summary

SAMPLES = Path(__file__).resolve().parents[1] / "samples" / "articles.json"


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name) / "cache.sqlite3"
        self.articles = [Article.model_validate(a) for a in json.loads(SAMPLES.read_text(encoding="utf-8"))]
        self.provider = MockProvider()
        self.service = Summarizer(self.provider, self.cache)

    def assert_error(self, code, function):
        with self.assertRaises(SummaryError) as caught:
            function()
        self.assertEqual(code, caught.exception.code)
        return str(caught.exception)

    def raw(self):
        return json.loads(self.provider.generate(self.articles[0]))

    def test_ten_samples_and_cache_hits(self):
        self.assertEqual(10, len(self.articles))
        first = [self.service.summarize(a) for a in self.articles]
        self.assertEqual(9, self.provider.calls)
        self.assertEqual(9, sum(r["result"]["status"] == "ok" for r in first))
        self.assertEqual("insufficient", first[-1]["result"]["status"])
        self.assertEqual([], first[-1]["result"]["tts_sentences"])
        second = [self.service.summarize(a) for a in self.articles]
        self.assertEqual(9, self.provider.calls)
        self.assertTrue(all(r["provenance"]["cached"] for r in second))
        self.assertTrue(all(r["provenance"]["mock"] and r["provenance"]["review_required"] for r in first))
        self.assertEqual(9, sum(r["validation"]["status"] == "needs_review" for r in first))
        self.assertTrue(all(not r["validation"]["approved"] and not r["provenance"]["approved"] for r in second))
        self.assertEqual(first[0]["result"], second[0]["result"])
        self.assertEqual(first[0]["validation"], second[0]["validation"])

    def test_permission_gate_precedes_cache_and_provider(self):
        article = self.articles[0]
        self.service.summarize(article)
        for rights in [
            article.rights.model_copy(update={"external_llm_allowed": False}),
            article.rights.model_copy(update={"summary_reuse_allowed": False}),
            article.rights.model_copy(update={"kind": "unverified"}),
            article.rights.model_copy(update={"basis": "  "}),
        ]:
            self.assert_error("permission_denied", lambda: self.service.summarize(article.model_copy(update={"rights": rights})))
        self.assertEqual(1, self.provider.calls)

    def test_source_model_prompt_and_provider_invalidate_cache(self):
        article = self.articles[0]
        first = self.service.summarize(article)
        modified = article.model_copy(update={"body": article.body + "\n가상 추가 의견은 아직 공개되지 않았습니다."})
        second = self.service.summarize(modified)
        self.assertNotEqual(first["provenance"]["cache_key"], second["provenance"]["cache_key"])
        self.provider.settings = replace(self.provider.settings, model="mock-version-2")
        third = self.service.summarize(article)
        self.assertNotEqual(first["provenance"]["cache_key"], third["provenance"]["cache_key"])
        with patch("drivebrief_summary.service.SYSTEM_PROMPT", "changed prompt"):
            fourth = self.service.summarize(article)
        self.assertNotEqual(third["provenance"]["cache_key"], fourth["provenance"]["cache_key"])
        self.provider.name = "other-provider"
        fifth = self.service.summarize(article)
        self.assertNotEqual(third["provenance"]["cache_key"], fifth["provenance"]["cache_key"])

    def test_concurrent_identical_requests_call_provider_once(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.service.summarize(self.articles[0]), range(4)))
        self.assertEqual(1, self.provider.calls)
        self.assertEqual(3, sum(r["provenance"]["cached"] for r in results))

    def test_invalid_json_and_extra_fields_rejected(self):
        for raw in ['not JSON', '{"status":"ok"}']:
            self.assert_error("invalid_json", lambda: validate_summary(raw, self.articles[0]))
        data = self.raw()
        data["unexpected"] = "extra"
        self.assert_error("invalid_json", lambda: validate_summary(json.dumps(data), self.articles[0]))

    def test_missing_and_fabricated_evidence_rejected(self):
        data = self.raw()
        data["evidence_links"][0]["evidence_ids"] = ["nonexistent-id"]
        self.assert_error("invalid_evidence", lambda: validate_summary(json.dumps(data), self.articles[0]))
        data = self.raw()
        data["evidence_links"] = data["evidence_links"][:1]
        self.assert_error("missing_evidence", lambda: validate_summary(json.dumps(data), self.articles[0]))

    def test_new_number_rejected_even_with_real_quote(self):
        data = self.raw()
        old = data["one_line"]
        new = old + " 참여 상점은 999곳입니다."
        data["one_line"] = new
        # IDs remain real, but cannot legitimize a new numeric fact.
        self.assert_error("unsupported_number", lambda: validate_summary(json.dumps(data), self.articles[0]))

    def test_insufficient_cannot_contain_fabricated_summary(self):
        data = {"status": "insufficient", "reason": "정보 부족",
                "tts_sentences": ["만든 문장"], "one_line": "", "detail": "", "evidence_links": []}
        self.assert_error("invalid_json", lambda: validate_summary(json.dumps(data), self.articles[0]))

    def test_bad_provider_output_is_not_cached(self):
        with patch.object(self.provider, "generate", return_value="not json") as generate:
            for _ in range(2):
                self.assert_error("invalid_json", lambda: self.service.summarize(self.articles[0]))
            self.assertEqual(2, generate.call_count)

    def test_corrupt_cache_fails_without_recalling_provider(self):
        report = self.service.summarize(self.articles[0])
        with sqlite3.connect(str(self.cache)) as db:
            db.execute("UPDATE summaries SET result='broken' WHERE cache_key=?",
                       (report["provenance"]["cache_key"],))
        self.assert_error("cache_corrupt", lambda: self.service.summarize(self.articles[0]))
        self.assertEqual(1, self.provider.calls)

    def test_input_strict_types(self):
        data = self.articles[0].model_dump()
        data["rights"]["external_llm_allowed"] = "true"
        with self.assertRaises(ValidationError):
            Article.model_validate(data)

    def test_missing_key_never_opens_network(self):
        provider = GroqProvider(Settings())
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}), patch("drivebrief_summary.providers.build_opener") as opener:
            self.assert_error("missing_api_key", lambda: provider.generate(self.articles[0]))
            opener.assert_not_called()

    def test_provider_schema_request_and_response(self):
        response = json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": self.provider.generate(self.articles[0])}}]}).encode()
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-placeholder"}), patch("drivebrief_summary.providers.build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(response)
            content = GroqProvider(Settings()).generate(self.articles[0])
            validate_summary(content, self.articles[0])
            request = opener.return_value.open.call_args.args[0]
            payload = json.loads(request.data)
            schema = payload["response_format"]["json_schema"]
            self.assertTrue(schema["strict"])
            self.assertFalse(schema["schema"]["additionalProperties"])
            self.assertEqual("openai/gpt-oss-20b", payload["model"])
            self.assertNotIn("rights", payload["messages"][1]["content"])
            request_input = json.loads(payload["messages"][1]["content"])
            self.assertEqual({"article_title", "source_spans"}, set(request_input))
            self.assertIn("evidence_links", schema["schema"]["properties"])
            self.assertNotIn("evidence_snippets", schema["schema"]["properties"])
            for span in request_input["source_spans"]:
                self.assertEqual(span["text"], getattr(self.articles[0], span["field"])[span["start"]:span["end"]])

    def test_provider_http_and_network_errors_are_sanitized(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-placeholder"}), patch("drivebrief_summary.providers.build_opener") as opener:
            opener.return_value.open.side_effect = HTTPError("url", 429, "sensitive-body", {}, None)
            message = self.assert_error("provider_http", lambda: GroqProvider(Settings()).generate(self.articles[0]))
            self.assertNotIn("sensitive", message)
            opener.return_value.open.side_effect = URLError("sensitive-error")
            message = self.assert_error("provider_network", lambda: GroqProvider(Settings()).generate(self.articles[0]))
            self.assertNotIn("sensitive", message)

    def test_truncated_response_rejected(self):
        response = json.dumps({"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}).encode()
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-placeholder"}), patch("drivebrief_summary.providers.build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(response)
            self.assert_error("provider_token_limit", lambda: GroqProvider(Settings()).generate(self.articles[0]))

    def test_bad_endpoint_and_redirect_rejected(self):
        for url in ["http://example.com", "https://user:password@example.com", "https://example.com?token=value"]:
            self.assert_error("config", lambda: Settings(base_url=url))
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.invalid"))

    def test_cli_batch_rights_gate_and_no_overwrite(self):
        from drivebrief_summary.cli import main
        source = Path(self.temp.name) / "input.json"
        target = Path(self.temp.name) / "output.json"
        articles = [a.model_dump() for a in self.articles]
        articles[1]["rights"]["external_llm_allowed"] = False
        source.write_text(json.dumps(articles), encoding="utf-8")
        argv = ["summary", "--input", str(source), "--output", str(target)]
        with patch("sys.argv", argv), patch("sys.stderr", new_callable=io.StringIO), patch.object(MockProvider, "generate") as generate:
            self.assertEqual(1, main())
            generate.assert_not_called()
        target.write_text("preserved", encoding="utf-8")
        source.write_text(json.dumps([self.articles[0].model_dump()]), encoding="utf-8")
        with patch("sys.argv", argv), patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(1, main())
        self.assertEqual("preserved", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
