"""Authored quantity/subject regression cases, not actual LLM quality metrics."""
import unittest
from drivebrief_summary.claim_relations import relation_warnings

FLAG = "subject_quantity_conflict_suspected"
SOURCE = "시험비는 300만원이고 임대료는 500만원입니다."
ERRORS = [
    ("particles", SOURCE, "시험비는 500만원이고 임대료는 300만원입니다."),
    ("bare_source", "시험비 300만원, 임대료 500만원", "시험비는 500만원이고 임대료는 300만원입니다."),
    ("bare_claim", SOURCE, "시험비 500만원, 임대료 300만원"),
    ("amount_first", SOURCE, "500만원의 시험비와 300만원의 임대료입니다."),
    ("colon", "시험비: 300만원, 임대료: 500만원", "시험비: 500만원, 임대료: 300만원"),
    ("allocation_particle", SOURCE, "시험비로 500만원을, 임대료로 300만원을 책정했습니다."),
]
NORMAL = [
    ("identical", SOURCE, SOURCE),
    ("clause_order", SOURCE, "임대료는 500만원이고 시험비는 300만원입니다."),
    ("particles", SOURCE, "시험비가 300만원이며 임대료가 500만원입니다."),
    ("bare_source", "시험비 300만원, 임대료 500만원", SOURCE),
    ("bare_claim", SOURCE, "시험비 300만원, 임대료 500만원"),
    ("amount_first", SOURCE, "500만원의 임대료와 300만원의 시험비입니다."),
    ("decimal_notation", SOURCE, "시험비는 300.0만원이고 임대료는 500.00만원입니다."),
    ("thousands_separator", "시험비는 3,000만원이고 임대료는 5,000만원입니다.",
     "임대료는 5000만원이고 시험비는 3000만원입니다."),
    ("unit_spacing", SOURCE, "시험비로 300만 원을, 임대료로 500만 원을 책정했습니다."),
]


class QuantityRelationTests(unittest.TestCase):
    def test_swapped_subject_values_warn(self):
        for name, source, claim in ERRORS:
            with self.subTest(name=name):
                self.assertIn(FLAG, relation_warnings(claim, [source])["warnings"])

    def test_equivalent_rewordings_do_not_warn(self):
        for name, source, claim in NORMAL:
            with self.subTest(name=name):
                self.assertNotIn(FLAG, relation_warnings(claim, [source])["warnings"])

    def test_canonicalization_never_rounds_away_real_changes(self):
        for source, claim in [
            (SOURCE, "시험비는 300.0001만원입니다."),
            ("시험비는 3,000만원입니다.", "시험비는 300만원입니다."),
            ("시험비는 123456789012345678901234567890만원입니다.",
             "시험비는 123456789012345678901234567891만원입니다."),
        ]:
            with self.subTest(claim=claim):
                self.assertIn(FLAG, relation_warnings(claim, [source])["warnings"])

    def test_unrecognized_syntax_is_not_declared_verified(self):
        result = relation_warnings("실험에 들어가는 돈은 오백만 원입니다.", [SOURCE])
        self.assertFalse(result["entailment_verified"])
        self.assertFalse(result["automatic_rejection"])

    def test_review_only_policy_unchanged(self):
        for _, source, claim in ERRORS+NORMAL:
            result = relation_warnings(claim, [source])
            self.assertFalse(result["automatic_rejection"])
            self.assertFalse(result["entailment_verified"])

    @classmethod
    def tearDownClass(cls):
        detected=sum(FLAG in relation_warnings(claim,[source])["warnings"] for _,source,claim in ERRORS)
        false_warnings=sum(FLAG in relation_warnings(claim,[source])["warnings"] for _,source,claim in NORMAL)
        print("authored_quantity_cases: detected=%d/%d normal_warnings=%d/%d" %
              (detected,len(ERRORS),false_warnings,len(NORMAL)))
