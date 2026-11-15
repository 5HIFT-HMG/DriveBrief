import copy
import unittest
from drivebrief_api.timing_holdout import compare
from drivebrief_api.pipeline_settings import load_config
from test_quality import observation


class TimingHoldoutTests(unittest.TestCase):
    def fixture(self):
        training=[observation("train",i,20+i*10) for i in range(3)]
        test=[observation("test",i,20+i*10) for i in range(3)]
        clock=0
        for row in test:
            row["session_id"]="unseen"
            row["session_sentence_count"]=3
            row["requested_monotonic_ms"]=clock
            clock+=row["request_to_done_ms"]+10
        return training,test

    def test_disjoint_hashes_and_frozen_coefficients(self):
        train,test=self.fixture()
        baseline=load_config(); candidate=dict(baseline,characters_per_second=1/.12,sentence_pause_seconds=1)
        report=compare(train,test,baseline,candidate)
        self.assertEqual(3,report["unseen_sentences"])
        self.assertFalse(report["fit_on_test"])
        self.assertAlmostEqual(0,report["candidate"]["mae_seconds"])
        self.assertEqual("observed_full_session",report["sessions"][0]["status"])
        self.assertGreater(report["baseline"]["rmse_seconds"],0)

    def test_overlap_unknown_environment_and_pause_rejected_or_excluded(self):
        train,test=self.fixture();cfg=load_config()
        test[0]["text_sha256"]=train[0]["text_sha256"]
        with self.assertRaises(ValueError):compare(train,test,cfg,cfg)
        train,test=self.fixture()
        for row in test:row["sdk_version"]="different"
        with self.assertRaises(ValueError):compare(train,test,cfg,cfg)
        train,test=self.fixture();test[-1]["requested_monotonic_ms"]+=10000
        report=compare(train,test,cfg,cfg)
        self.assertEqual("pause_or_clock_discontinuity_excluded",report["sessions"][0]["status"])
