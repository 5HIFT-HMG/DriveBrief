import unittest
from drivebrief_summary.quality_cases import run_cases
from drivebrief_api.review import ReviewStore
from pathlib import Path
import tempfile


class SummaryQualityTests(unittest.TestCase):
    def test_authored_error_matrix_distinguishes_hard_rejection_and_review(self):
        report = run_cases()
        by_name = {r["case"]: r for r in report["cases"]}
        for name in ("unsupported_number", "date_tuple_swap", "person_with_role", "wrong_source_span"):
            self.assertEqual("rejected", by_name[name]["core_outcome"])
        self.assertIn("quantity_unit_pair_requires_review", by_name["number_unit_changed"]["supplementary_warnings"])
        self.assertIn("organization_requires_review", by_name["organization_changed"]["supplementary_warnings"])
        self.assertIn("polarity_unverified", by_name["negation_omitted"]["review_flags"])
        self.assertIn("certainty_change_suspected", by_name["tentative_to_confirmed"]["review_flags"])
        for name in ("invented_event_without_new_number", "same_unit_value_relation_swap", "untitled_person_confusion"):
            self.assertEqual("accepted_needs_review", by_name[name]["core_outcome"])
            self.assertIn("semantic_entailment_unverified", by_name[name]["supplementary_warnings"])
        self.assertGreater(by_name["safety_constraint_and_budget_omitted"]["unreferenced_body_spans"], 0)
        self.assertTrue(all(r["approved"] is False for r in report["cases"]))

    def test_review_export_adds_comparison_without_altering_approval(self):
        from drivebrief_summary.quality_cases import cases
        from drivebrief_summary.providers import MockProvider
        with tempfile.TemporaryDirectory() as d:
            store = ReviewStore(Path(d)/"review.sqlite3")
            article = cases()[0]
            store.generate([dict(article=article.model_dump(), published_at="2026-11-13T09:00:00+09:00",
                                 origin="own fixture")], MockProvider(), Path(d)/"cache.sqlite3")
            before = store.get(article.id)
            exported = store.review_document(article.id)
            self.assertIn("quality_diagnostics", exported)
            self.assertEqual(before, store.get(article.id))
            self.assertEqual("needs_review", exported["decision"])
            self.assertFalse(exported["quality_diagnostics"]["automatic_approval"])
