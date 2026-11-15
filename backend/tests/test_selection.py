import copy
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from fastapi.testclient import TestClient
from drivebrief_api.pipeline_settings import load_config
from drivebrief_api.selection import metadata, group_events, rank_groups, balanced_select
from drivebrief_api.candidates import candidates
from drivebrief_api.app import create_app

NOW = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)


def row(i, title="삼성전자 부산 반도체 공장 착공 소식", source="가상일보", category="IT", date="2026-11-13T09:00:00+00:00"):
    return dict(url="https://example.test/" + str(i), title=title,
                description="삼성전자 부산 반도체 공장 착공 행사가 개최됐다. 지역 시설 공사를 시작했다.",
                published_at=date, source=source, category=category)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config()

    def test_exact_ids_memberships_preserved(self):
        rows = [row(1), row(1, source="다른일보"), row(2, title="  삼성전자 부산 반도체 공장 착공 소식  ")]
        items = metadata(rows)
        self.assertEqual(2, len(items))
        groups = group_events(items, self.cfg)
        self.assertEqual(1, len(groups))
        self.assertEqual(2, len(groups[0]["members"]))
        self.assertEqual(2, len(items[0]["sources"]) if items[0]["source_url"].endswith("/1") else len(items[1]["sources"]))

    def test_same_event_and_unrelated_not_merged(self):
        rows = [row(1), row(2, "삼성전자 부산 반도체 공장 착공 행사", "다른일보"),
                row(3, "삼성전자 부산 반도체 실적 매출 발표", "다른일보")]
        groups = group_events(metadata(rows), self.cfg)
        self.assertEqual([1, 2], sorted(len(g["members"]) for g in groups))
        self.assertTrue(any(g["reasons"] for g in groups if len(g["members"]) == 2))

    def test_numbers_time_missing_description_guard(self):
        for a, b in [
            (row(1, "삼성전자 부산 12명 반도체 공장 착공"), row(2, "삼성전자 부산 30명 반도체 공장 착공")),
            (row(1), row(2, "삼성전자 부산 반도체 공장 착공 행사", date="2026-11-01T09:00:00+00:00")),
            (row(1), dict(row(2, "삼성전자 부산 반도체 공장 착공 행사"), description=""))]:
            self.assertEqual(2, len(group_events(metadata([a, b]), self.cfg)))

    def test_deterministic_and_source_diversity_not_feed_spam(self):
        rows = [row(1), row(2, "삼성전자 부산 반도체 공장 착공 행사", "새일보")]
        a = candidates(rows=rows, interests=["IT"], as_of=NOW, config=self.cfg)
        b = candidates(rows=list(reversed(rows)), interests=["IT"], as_of=NOW, config=self.cfg)
        self.assertEqual(a, b)
        single = candidates(rows=[row(1)], as_of=NOW, config=self.cfg)["articles"][0]
        self.assertGreater(a["articles"][0]["score_components"]["diversity"], single["score_components"]["diversity"])
        aliases = metadata([row(1, source="전자신문 IT"), row(1, source="전자신문 SW·AI")])
        scores = rank_groups(group_events(aliases, self.cfg), [], NOW, self.cfg)
        self.assertAlmostEqual(.2/3, scores[0]["score_components"]["diversity"], places=5)

    def test_balance_interest_fallback_and_component_sum(self):
        ranked = []
        for i, cat in enumerate(["IT", "IT", "IT", "경제", "스포츠"]):
            ranked.append(dict(group_id=str(i), importance_score=.9 if cat == "IT" else .85, categories=[cat]))
        selected = balanced_select(ranked, ["IT", "경제"], 5, .15)
        self.assertEqual(["IT", "경제"], [r["selection_reason"]["balance_category"] for r in selected[:2]])
        self.assertTrue(selected[-1]["selection_reason"]["fallback"])
        data = candidates(rows=[row(1)], as_of=NOW, config=self.cfg)["articles"][0]
        self.assertAlmostEqual(data["importance_score"], sum(data["score_components"].values()))

    def test_invalid_date_no_future_recency_and_empty(self):
        for date in ("bad", None, "2030-01-01T00:00:00+00:00"):
            result = candidates(rows=[row(1, date=date)], as_of=NOW, config=self.cfg)["articles"][0]
            self.assertEqual(0, result["score_components"]["recency"])
            self.assertFalse(result["ai_eligible"])
        self.assertEqual([], candidates(rows=[], as_of=NOW, config=self.cfg)["articles"])

    def test_api_validation_and_missing_db_no_create(self):
        from drivebrief_api.news_repository import NewsRepository
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "missing.sqlite3"
            client = TestClient(create_app(news_repository=NewsRepository(path)))
            self.assertEqual(503, client.get("/v1/news/candidates").status_code)
            self.assertFalse(path.exists())
            for query in ("limit=0", "categories=unknown", "as_of=2026-11-13", "as_of=bad"):
                self.assertEqual(422, client.get("/v1/news/candidates?" + query).status_code)

    def test_conflicting_place_company_and_person_do_not_merge(self):
        for left, right in [
            ("삼성전자 부산 반도체 공장 착공 행사", "삼성전자 수원 반도체 공장 착공 행사"),
            ("삼성전자 부산 반도체 공장 착공 행사", "가상전자 부산 반도체 공장 착공 행사"),
            ("대표 김다온 부산 반도체 공장 착공 행사", "대표 이새봄 부산 반도체 공장 착공 행사")]:
            self.assertEqual(2, len(group_events(metadata([row(1, left), row(2, right)]), self.cfg)))
