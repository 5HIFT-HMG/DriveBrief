import unittest

from drivebrief_api.pipeline_settings import load_config
from drivebrief_api.publish_briefings import LENGTHS, build, publish


def document(fictional=True, count=3):
    return {"schema_version": "approved-briefing-v1", "fictional_only": fictional, "playback_requires_user_action": True,
            "articles": [{"article_id": f"fiction-0{i}", "title": f"가상 기사 {i}", "source": "자체 작성",
                          "published_at": "2026-11-13T00:00:00+00:00", "source_url": None,
                          "tts_sentences": [f"가상 기사 {i}의 첫 문장입니다.", f"가상 기사 {i}의 두 번째 문장입니다."],
                          "one_line": f"가상 한 줄 {i}", "detail": "가상 상세", "mock": True,
                          "validation": {"status": "approved", "approved": True, "review_required": False}}
                         for i in range(1, count + 1)]}


class FakeRemote:
    def __init__(self):
        self.calls = []

    def request(self, path, method="GET", value=None, prefer=None):
        self.calls.append((path, method, value, prefer))


class PublishBriefingsTest(unittest.TestCase):
    def test_real_articles_are_blocked_by_existing_planner_policy(self):
        with self.assertRaisesRegex(ValueError, "real_planning_blocked_by_policy"):
            build(document(fictional=False), load_config())

    def test_plans_every_length_and_upserts_with_namespace(self):
        plans = build(document(), load_config())
        self.assertEqual(set(LENGTHS), set(plans))
        self.assertTrue(all(p["articles"] and p["schema_version"] == "approved-briefing-v1" for p in plans.values()))
        self.assertTrue(all(a["categories"] for a in plans["길게"]["articles"]))
        remote = FakeRemote()
        result = publish(plans, "fictional", remote)
        self.assertEqual(3, len(remote.calls))
        path, method, value, prefer = remote.calls[0]
        self.assertEqual(("published_briefings?on_conflict=length_option", "POST"), (path, method))
        self.assertEqual("fictional", value[0]["namespace"])
        self.assertEqual(64, len(value[0]["revision"]))
        self.assertIn("merge-duplicates", prefer)
        self.assertTrue(all(count > 0 for count in result.values()))

    def test_empty_plan_preserves_existing_published_rows(self):
        plans = build(document(count=0), load_config())
        remote = FakeRemote()
        with self.assertRaisesRegex(ValueError, "empty_plan_not_published"):
            publish(plans, "fictional", remote)
        self.assertEqual([], remote.calls)


if __name__ == "__main__":
    unittest.main()
