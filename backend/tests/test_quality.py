import copy
import unittest
from datetime import datetime, timezone
from drivebrief_api.quality import sample_pairs, evaluate, ranking_report
from drivebrief_api.pipeline_settings import load_config
from drivebrief_api.selection import metadata
from drivebrief_api.timing_quality import analyze
import hashlib


def items():
    return metadata([dict(url="https://example.test/"+str(i), title=title, source="시험신문",
        category=category, description="가상 공원 행사에 주민이 참여한다.", published_at="2026-11-01T09:00:00+09:00")
        for i, (title, category) in enumerate([("가상 공원 행사 계획", "사회"),
              ("가상 공원 행사 계획", "사회"), ("다른 가상 경제 소식", "경제"), ("스포츠 대회 발표", "스포츠")])])


class MetadataQualityTests(unittest.TestCase):
    def test_unlabeled_never_has_accuracy(self):
        bundle = sample_pairs(items(), load_config(), 6)
        rows = [dict(pair_id=p["pair_id"], source_hash=bundle["source_hash"], human_label="", reviewer="") for p in bundle["pairs"]]
        result = evaluate(bundle, rows)
        self.assertEqual("awaiting_human_labels", result["status"])
        self.assertIsNone(result["models"]["baseline"]["precision"])
        self.assertIsNone(result["models"]["baseline"]["recall"])
        self.assertIsNone(result["models"]["baseline"]["f1"])
        self.assertIn("merged", bundle["sampling"]["strata"])
        self.assertIn("similar_unmerged", bundle["sampling"]["strata"])

    def test_metric_arithmetic_on_authored_fixture_and_stale_labels(self):
        bundle = sample_pairs(items(), load_config(), 6)
        rows = []
        # Synthetic test truth explicitly supplied by the test author, not real RSS gold.
        ids = {i: next(r["article_id"] for r in bundle["items"] if r["source_url"].endswith("/"+str(i))) for i in range(4)}
        for p in bundle["pairs"]:
            truth = {p["left_id"], p["right_id"]} == {ids[0], ids[1]}
            rows.append(dict(pair_id=p["pair_id"], source_hash=bundle["source_hash"],
                             human_label="same_event" if truth else "different_event", reviewer="test-author"))
        result = evaluate(bundle, rows)
        self.assertEqual(1, result["models"]["baseline"]["f1"])
        rows[0]["reviewer"] = ""
        with self.assertRaises(ValueError): evaluate(bundle, rows)
        rows[0]["reviewer"] = "test-author"; rows[0]["source_hash"] = "old"
        with self.assertRaises(ValueError): evaluate(bundle, rows)

    def test_ranking_reports_stale_source_concentration_and_shortage(self):
        cfg = load_config(); variant = copy.deepcopy(cfg)
        variant["weights"] = {"recency": .5, "coverage": .1, "diversity": .15, "interest": .15, "quality": .1}
        report = ranking_report(items(), cfg, datetime(2026,11,13,tzinfo=timezone.utc), ["사회"], candidate_config=variant)
        self.assertTrue(report["baseline"]["shortage"])
        self.assertEqual(len(report["baseline"]["top"]), report["baseline"]["older_than_48h"])
        self.assertEqual(1, report["baseline"]["largest_publisher_share"])
        self.assertTrue(report["human_preference_not_evaluated"])
        self.assertTrue(report["rank_comparison"])


def observation(article, sentence, chars, offset=0):
    return {"schema": "speech-timing-v1", "engine": "pleos-on-device", "locale": "ko-KR", "sdk_version": "test-fixture",
        "attempt_id": article+str(sentence)+str(offset), "article_id": article, "sentence_index": sentence,
        "session_id": "test-session", "length_option": "중간", "session_sentence_count": 6,
        "text_sha256": hashlib.sha256((article+str(sentence)).encode()).hexdigest(),
        "features": dict(characters=chars, hangul=chars-2, spaces=1,digits=1,punctuation=0,latin=0,other=0),
        "outcome": "completed", "startup_ms": 100, "start_to_done_ms": (chars*.12+1)*1000-100,
        "request_to_done_ms": (chars*.12+1)*1000, "requested_monotonic_ms": sentence*10000+offset}


class TimingQualityTests(unittest.TestCase):
    def test_mock_excluded_and_empty_no_calibration(self):
        row = observation("a", 0, 20); row["engine"] = "mock-test"
        report, model = analyze([row], load_config())
        self.assertEqual("no_observed_data", report["status"]); self.assertIsNone(model)

    def test_calibration_and_article_holdout_on_synthetic_numeric_fixture(self):
        records = [observation(a, i, 20+10*j+5*i) for j,a in enumerate(["a","b","c"]) for i in range(2)]
        report, candidate = analyze(records, load_config())
        self.assertIsNotNone(candidate)
        self.assertAlmostEqual(1/.12, candidate["characters_per_second"], places=5)
        self.assertAlmostEqual(1, candidate["sentence_pause_seconds"], places=5)
        self.assertLess(report["candidate_training_fit"]["mae_seconds"], report["baseline"]["mae_seconds"])
        self.assertEqual(3, len(report["leave_one_article_out"]))
        self.assertTrue(all(r["candidate"] is not None for r in report["leave_one_article_out"]))
        self.assertTrue(report["feature_correlations_not_causal"])

    def test_interrupted_incomplete_and_duplicate_records(self):
        row = observation("a",0,20); stopped = dict(row, attempt_id="stop", outcome="stopped")
        report, _ = analyze([row, row, stopped], load_config())
        self.assertEqual(1, report["observations"])
        self.assertEqual("incomplete_or_interrupted_excluded", report["option_runs"][0]["status"])
        corrupt = dict(row, request_to_done_ms=1)
        with self.assertRaises(ValueError): analyze([corrupt], load_config())

    def test_no_fit_uses_frozen_parameters_and_measures_serial_session(self):
        records = [observation("a", i, 20+10*i) for i in range(3)]
        clock = 0
        for r in records:
            r["session_sentence_count"] = 3
            r["requested_monotonic_ms"] = clock
            clock += r["request_to_done_ms"]+100
        cfg = load_config(); cfg["characters_per_second"] = 4
        report, candidate = analyze(records, cfg, calibrate=False)
        self.assertIsNone(candidate)
        self.assertIsNone(report["candidate_coefficients"])
        self.assertEqual([], report["leave_one_article_out"])
        run = report["option_runs"][0]
        self.assertEqual("observed_full_session", run["status"])
        self.assertAlmostEqual((clock-100)/1000, run["observed_elapsed_seconds"])
        self.assertGreater(report["baseline"]["mae_seconds"], 1)

    def test_mixed_sdk_measurements_are_not_pooled(self):
        a, b = observation("a", 0, 20), observation("b", 0, 30)
        b["sdk_version"] = "different-fixture"
        with self.assertRaises(ValueError): analyze([a, b], load_config())
