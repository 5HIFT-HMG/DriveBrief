import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from drivebrief_api import rss_auto as rss


NOW = datetime(2026, 11, 14, 0, 0, tzinfo=timezone.utc)


def rows(count=30):
    return [dict(url=f"https://fixture.example/{i}", title=f"가상 분야별 소식 코드{i}",
        description=f"가상 기관{i}에서 새로운 운영 소식을 전했습니다. 주민들에게 필요한 주요 정보가 있습니다. 운영 일정은 아직 미정입니다. 자세한 추가 안내를 확인하세요.",
        published_at=(NOW - timedelta(minutes=i+1)).isoformat(),
        category=["경제", "사회", "정치", "IT", "스포츠"][i % 5], source=f"가상 출처{i%3}") for i in range(count)]


class Remote:
    def __init__(self):
        self.current = []
        self.calls = []
        self.news = [dict(row, news_memberships=[{"category":row["category"],"source":row["source"]}]) for row in rows()]
    def request(self, path, method="GET", value=None, prefer=None):
        self.calls.append((path, method, value))
        if path.startswith("news_articles"):
            return self.news
        if method == "POST":
            self.current = copy.deepcopy(value)
        return copy.deepcopy(self.current)


class AutoRssTests(unittest.TestCase):
    def test_25_same_ids_and_order_135_exact_text_no_approval(self):
        source = rows()
        docs = rss.build(source, now=NOW)
        ids = [[a["article_id"] for a in docs[k]["articles"]] for k in rss.OPTIONS]
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(ids[0], ids[2])
        self.assertEqual(25, len(ids[0]))
        self.assertEqual([1, 3, 5], [len(docs[k]["articles"][0]["tts_sentences"]) for k in rss.OPTIONS])
        for document in docs.values():
            self.assertNotIn("target_seconds", document)
            for article in document["articles"]:
                self.assertNotIn("approved", article["validation"])
                self.assertFalse(article["validation"]["human_reviewed"])
                expected = ([rss.short_sentence(article["title"],article["detail"])]
                            if document["length_option"] == "짧게" else
                            rss.source_units(article["title"],article["detail"])[:document["sentence_limit"]])
                self.assertEqual(article["tts_sentences"], expected)

    def test_insufficient_metadata_no_padding_and_url_title_dedup(self):
        data = rows(2)
        data[0]["description"] = ""
        data += [dict(data[0]), dict(data[0],url="https://other.example/same")]
        docs = rss.build(data, now=NOW)
        self.assertEqual(1, len(docs["길게"]["articles"]))
        self.assertNotIn(data[0]["url"], [a["source_url"] for a in docs["길게"]["articles"]])

    def test_rejects_generated_text_bad_date_and_oversize(self):
        document = rss.build(rows(), now=NOW)["중간"]
        bad = copy.deepcopy(document)
        bad["articles"][0]["tts_sentences"][0] = "원문에 없는 사실"
        with self.assertRaises(ValueError):
            rss.RssBriefing.model_validate(bad)
        with self.assertRaises(ValueError):
            rss.build([dict(rows(1)[0],published_at="invalid")], now=NOW)
        with self.assertRaises(ValueError):
            rss.build(rows(), now=NOW, max_articles=26)
        stale = [dict(rows(1)[0],published_at=(NOW-timedelta(days=6)).isoformat())]
        with self.assertRaises(ValueError):
            rss.build(stale, now=NOW)

    def test_one_atomic_write_skip_unchanged_and_no_regroup(self):
        remote = Remote()
        self.assertEqual("published", rss.refresh(remote, now=NOW)["status"])
        posts = [r for r in remote.calls if r[1] == "POST"]
        self.assertEqual(1, len(posts))
        self.assertEqual(3, len(posts[0][2]))
        with patch.object(rss, "group_events", side_effect=AssertionError("Must not regroup unchanged input")):
            self.assertEqual("unchanged", rss.refresh(remote, now=NOW+timedelta(minutes=1))["status"])
        self.assertEqual(1, len([r for r in remote.calls if r[1] == "POST"]))

    def test_dry_run_failure_preserves_and_empty_source(self):
        remote = Remote()
        self.assertEqual("dry_run", rss.refresh(remote, dry_run=True, now=NOW)["status"])
        self.assertFalse(any(r[1] == "POST" for r in remote.calls))
        remote.news = []
        with self.assertRaises(ValueError):
            rss.refresh(remote, now=NOW)
        self.assertFalse(any(r[1] == "POST" for r in remote.calls))

    def test_collection_hook_only_for_production_path_and_never_for_fixture_db(self):
        import os
        import sqlite3
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from drivebrief_api.shared_backend import shared_settings
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(shared_settings, "ROOT", root), patch.object(shared_settings, "locked_upload",
                return_value={"state":"synced","uploaded":0}), patch.dict(os.environ, {"DRIVEBRIEF_RSS_AUTO":"1"}), patch(
                    "subprocess.run", return_value=SimpleNamespace(stdout='{"status":"unchanged"}')) as process:
                with sqlite3.connect(root/"fixture.sqlite3") as db:
                    shared_settings.sync_after_collection(db)
                process.assert_not_called()
                with sqlite3.connect(root/"news.sqlite3") as db:
                    self.assertEqual("unchanged", shared_settings.sync_after_collection(db)["briefing"])
                self.assertEqual(1, process.call_count)
                self.assertIn("drivebrief_api.rss_auto", process.call_args.args[0])

    def test_corrupt_cached_catalog_is_repaired_and_status_checks_all_options(self):
        remote = Remote()
        rss.refresh(remote, now=NOW)
        self.assertTrue(rss.publication_status(remote)["same_article_ids_and_order"])
        broken = remote.current[1]["briefing"]["articles"]
        broken[0], broken[1] = broken[1], broken[0]
        broken[0]["order"], broken[1]["order"] = 1, 2
        self.assertEqual("published", rss.refresh(remote, now=NOW)["status"])
        self.assertEqual(2, len([r for r in remote.calls if r[1] == "POST"]))

    def test_default_publisher_dispatches_to_auto_without_review_store(self):
        from drivebrief_api.publish_briefings import main
        with patch("builtins.print"), patch("drivebrief_api.rss_auto.refresh", return_value={"status":"dry_run"}) as refresh, patch(
                "drivebrief_api.shared_backend.SharedDatabase"), patch("drivebrief_api.rss_review.RssReviewStore") as review:
            self.assertEqual(0, main(["--dry-run"]))
            refresh.assert_called_once()
            review.assert_not_called()

    def test_mismatched_catalog_options_rejected_before_write(self):
        remote = Remote()
        docs = rss.build(rows(), now=NOW)
        docs["중간"]["articles"].reverse()
        with self.assertRaises(ValueError):
            rss.publish(docs, remote)
        self.assertFalse(any(r[1] == "POST" for r in remote.calls))


if __name__ == "__main__":
    unittest.main()
