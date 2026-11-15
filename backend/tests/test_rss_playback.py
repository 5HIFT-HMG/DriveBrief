"""Synthetic fixtures only; no network and no approval of actual RSS."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from drivebrief_api.pipeline_settings import load_config
from drivebrief_api.private_preview import preview_input, build_preview, read_recent
from drivebrief_api.pipeline_models import PlannedResponse
from drivebrief_api.planning import plan
from drivebrief_api.publish_briefings import publish, build, main
from drivebrief_api.rss_review import RssReviewStore, permissions
from tests.test_publish_briefings import FakeRemote


def rows():
    return [dict(url="https://example.test/a", title="가상 다온시 도서관 운영 안내",
                 description="다온시 도서관은 오후에 운영합니다. 이용 시간은 변동될 수 있습니다.",
                 published_at="2026-11-13T00:00:00+00:00", category="사회", source="가상 출처")]


class RssPlaybackTest(unittest.TestCase):
    def test_private_preview_retains_text_and_never_approves_or_publishes(self):
        plans = build_preview(rows(), load_config())
        for document in plans.values():
            self.assertFalse(document["publication_allowed"])
            self.assertEqual("needs_review", document["articles"][0]["validation"]["status"])
            self.assertFalse(document["articles"][0]["validation"]["approved"])
            original = preview_input(rows())["articles"][0]["tts_sentences"]
            spoken = document["articles"][0]["tts_sentences"]
            self.assertEqual(original[:len(spoken)], spoken)
            with self.assertRaises(ValueError):
                PlannedResponse.model_validate(document)
        remote = FakeRemote()
        with self.assertRaises(ValueError):
            publish(plans, "real", remote)
        self.assertEqual([], remote.calls)
        with self.assertRaises(ValueError):
            plan(preview_input(rows()), "중간", [], load_config())

    def test_preview_limits_missing_fields_and_empty_data(self):
        self.assertEqual([], build_preview([], load_config())["중간"]["articles"])
        missing = rows()
        missing[0]["published_at"] = "unknown"
        self.assertEqual([], preview_input(missing)["articles"])
        long = rows()
        long[0]["description"] = "가" * 351 + ". 다음 문장입니다."
        self.assertEqual([long[0]["title"]], preview_input(long)["articles"][0]["tts_sentences"])
        with self.assertRaises(ValueError):
            read_recent(FakeRemote(), 201)

    def test_private_cli_cannot_publish(self):
        with patch("builtins.print"), patch("drivebrief_api.shared_backend.SharedDatabase") as remote:
            self.assertEqual(2, main(["--private-rss-preview"]))
            remote.assert_not_called()

    def test_read_recent_only_uses_bounded_get(self):
        class Remote:
            def request(self, path, method="GET"):
                self.path, self.method = path, method
                return [dict(rows()[0], news_memberships=[{"category": "사회", "source": "가상 출처"}])]
        remote = Remote()
        flattened, count = read_recent(remote, 10)
        self.assertEqual((1, 1, "GET"), (count, len(flattened), remote.method))
        self.assertIn("limit=10", remote.path)

    def test_permission_review_revision_revocation_and_no_llm(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = Path(directory) / "policy.json"
            grant = dict(source="가상 출처", article_host="example.test", tts_allowed=True, reuse_allowed=True,
                         basis="Synthetic fixture only; not a real permission grant", confirmed_by="test reviewer",
                         confirmed_at="2026-01-01T00:00:00+00:00")
            policy.write_text(json.dumps({"sources": [grant]}))
            store = RssReviewStore(Path(directory) / "reviews.sqlite3", policy)
            self.assertEqual([{"status": "needs_review"}], store.prepare(rows()))
            self.assertEqual([], store.briefing()["articles"])
            article_id = store.rows()[0][0]
            review = store.review_document(article_id)
            store.decide(article_id, "synthetic-test-reviewer", "approved", review["revision"])
            document = store.briefing()
            self.assertEqual(1, len(document["articles"]))
            self.assertFalse(document["fictional_only"])
            plans = build(document, load_config())
            remote = FakeRemote()
            publish(plans, "real", remote)
            self.assertEqual(3, len(remote.calls))
            with self.assertRaisesRegex(ValueError, "rss_llm_generation_forbidden"):
                store.generate(None, None, None)
            # Removing permission immediately blocks an old approval.
            policy.write_text('{"sources":[]}')
            with self.assertRaisesRegex(ValueError, "rss_permission_changed"):
                store.briefing()
            self.assertEqual([{"status": "blocked"}], store.prepare(rows()))
            self.assertEqual("needs_review", store.rows()[0][4])

    def test_policy_missing_or_unconfirmed_never_prepares(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = Path(directory) / "missing.json"
            store = RssReviewStore(Path(directory) / "reviews.sqlite3", policy)
            with self.assertRaisesRegex(ValueError, "rss_policy_missing"):
                store.prepare(rows())
            self.assertFalse(store.path.exists())
            policy.write_text('{"sources":[]}')
            self.assertEqual([{"status": "blocked"}], store.prepare(rows()))
            self.assertFalse(store.path.exists())


if __name__ == "__main__":
    unittest.main()
