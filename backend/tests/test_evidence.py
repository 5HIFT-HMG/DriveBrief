import json
from pathlib import Path
import unittest

from drivebrief_summary.errors import SummaryError
from drivebrief_summary.models import Article, Draft
from drivebrief_summary.segments import MAX_SPAN, split_article
from drivebrief_summary.validation import resolve_draft


class EvidenceTests(unittest.TestCase):
    def article(self, body):
        return Article(id="test", title="가상 테스트", body=body, source="자체 가상 자료",
                       rights={"kind": "fictional", "external_llm_allowed": True,
                               "summary_reuse_allowed": True, "basis": "자체 작성"})

    def raw(self, article, claim, ids=None):
        if ids is None:
            ids = [span.id for span in split_article(article) if span.field == "body"]
        return Draft(status="ok", reason="", tts_sentences=[claim], one_line=claim, detail=claim,
                     evidence_links=[{"target": field, "index": 0, "evidence_ids": ids}
                                     for field in ("tts_sentences", "one_line", "detail")]).model_dump_json()

    def failure(self, article, claim, code, reason, ids=None):
        with self.assertRaises(SummaryError) as caught:
            resolve_draft(self.raw(article, claim, ids), article)
        self.assertEqual(code, caught.exception.code)
        self.assertIn(reason, str(caught.exception))
        self.assertNotIn(article.body, str(caught.exception))
        self.assertNotIn(claim, str(caught.exception))

    def test_ids_are_stable_and_offsets_reconstruct_exact_original(self):
        article = self.article("가상 첫 문장입니다.\r\n두 번째\t문장입니다. 값은 1.5도입니다.")
        spans = split_article(article)
        self.assertEqual(spans, split_article(article))
        self.assertEqual(len(spans), len({s.id for s in spans}))
        for span in spans:
            self.assertEqual(span.text, getattr(article, span.field)[span.start:span.end])
        self.assertTrue(any("1.5도" in s.text for s in spans))

    def test_revision_and_repeated_text_do_not_reuse_ids(self):
        article = self.article("같은 가상 문장입니다. 같은 가상 문장입니다.")
        old = split_article(article)
        self.assertNotEqual(old[1].id, old[2].id)
        changed = split_article(article.model_copy(update={"body": article.body + " 변경입니다."}))
        self.assertFalse({s.id for s in old} & {s.id for s in changed})

    def test_long_and_unicode_spans_preserve_offsets_and_bounds(self):
        article = self.article(("가상문자🙂" * 300) + "\n\n끝 문장입니다.")
        for span in split_article(article):
            self.assertLessEqual(len(span.text), MAX_SPAN)
            self.assertEqual(span.text, getattr(article, span.field)[span.start:span.end])

    def test_punctuation_paraphrase_uses_python_quote_and_needs_review(self):
        body = "가상 주민 12명이 토론회에 참석했습니다."
        article = self.article(body)
        claim = "가상 토론회에는 주민 12명이 함께했습니다!"
        result, validation, links = resolve_draft(self.raw(article, claim), article)
        self.assertEqual(claim, result.one_line)
        self.assertTrue(all(e.quote == body for e in result.evidence_snippets))
        self.assertEqual("needs_review", validation["status"])
        self.assertFalse(validation["approved"])
        self.assertTrue(validation["review_required"])
        self.assertIn("paraphrase_requires_review", validation["review_flags"])

    def test_even_exact_source_does_not_prove_semantics(self):
        article = self.article("가상 주민들이 모였습니다.")
        _, validation, _ = resolve_draft(self.raw(article, article.body), article)
        self.assertFalse(validation["approved"])
        self.assertEqual("needs_review", validation["status"])

    def test_unknown_or_other_revision_id_rejected(self):
        article = self.article("가상 주민들이 모였습니다.")
        self.failure(article, article.body, "invalid_evidence", "unknown_id", ["not-real"])
        other = split_article(article.model_copy(update={"body": "다른 가상 기사입니다."}))[1].id
        self.failure(article, article.body, "invalid_evidence", "unknown_id", [other])

    def test_arbitrary_llm_quote_or_self_approval_is_rejected(self):
        article = self.article("가상 주민들이 모였습니다.")
        for field, value in [("evidence_snippets", [{"claim": article.body, "quote": article.body}]),
                             ("approved", True)]:
            data = json.loads(self.raw(article, article.body))
            data[field] = value
            with self.assertRaises(SummaryError) as caught:
                resolve_draft(json.dumps(data), article)
            self.assertEqual("invalid_json", caught.exception.code)

    def test_invalid_targets_duplicates_and_missing_links(self):
        article = self.article("가상 주민들이 모였습니다.")
        original = json.loads(self.raw(article, article.body))
        for mutation, reason in [
            (lambda d: d["evidence_links"][0].update(index=99), "invalid_target"),
            (lambda d: d["evidence_links"].append(d["evidence_links"][0]), "duplicate_target"),
            (lambda d: d["evidence_links"][0]["evidence_ids"].append(d["evidence_links"][0]["evidence_ids"][0]), "duplicate_id"),
        ]:
            data = json.loads(json.dumps(original))
            mutation(data)
            with self.assertRaises(SummaryError) as caught:
                resolve_draft(json.dumps(data), article)
            self.assertIn(reason, str(caught.exception))
        original["evidence_links"].pop()
        with self.assertRaises(SummaryError) as caught:
            resolve_draft(json.dumps(original), article)
        self.assertEqual("missing_evidence", caught.exception.code)

    def test_number_elsewhere_in_article_does_not_support_claim(self):
        article = self.article("가상 행사에는 주민 12명이 참석했습니다. 별도 행사의 정원은 99명입니다.")
        first = [s for s in split_article(article) if s.field == "body"][0]
        self.failure(article, "가상 행사에는 99명이 참석했습니다.", "unsupported_number",
                     "number_not_in_linked_evidence", [first.id])

    def test_rearranged_date_with_same_numbers_rejected(self):
        article = self.article("가상 행사는 2026년 11월 12일 열렸습니다.")
        self.failure(article, "가상 행사는 2026년 12월 11일 열렸습니다.",
                     "unsupported_date", "date_not_in_linked_evidence")

    def test_equivalent_date_notation_still_requires_review(self):
        article = self.article("가상 행사는 2026년 11월 12일 열렸습니다.")
        _, validation, _ = resolve_draft(self.raw(article, "가상 행사 날짜는 2026-11-12입니다."), article)
        self.assertEqual("needs_review", validation["status"])
        self.assertFalse(validation["approved"])

    def test_recognized_person_change_rejected(self):
        article = self.article("가상 대표 김다온은 행사를 발표했습니다.")
        self.failure(article, "가상 대표 이새봄은 행사를 발표했습니다.",
                     "unsupported_person", "person_not_in_linked_evidence")

    def test_person_particle_paraphrase_does_not_change_name(self):
        article = self.article("가상 대표 김다온은 행사를 발표했습니다.")
        _, validation, _ = resolve_draft(self.raw(article, "가상 대표 김다온이 행사를 알렸습니다."), article)
        self.assertFalse(validation["approved"])

    def test_unrelated_exact_sentence_rejected(self):
        article = self.article("가상 공원이 문을 열었습니다. 가상 도서관은 쉬었습니다.")
        spans = [s for s in split_article(article) if s.field == "body"]
        self.failure(article, spans[0].text, "invalid_evidence", "unrelated_exact_source", [spans[1].id])

    def test_unverifiable_new_event_is_not_approved(self):
        article = self.article("가상 공원이 문을 열었습니다.")
        _, validation, _ = resolve_draft(self.raw(article, "가상 대표가 선거에서 이겼습니다."), article)
        self.assertEqual("needs_review", validation["status"])
        self.assertFalse(validation["approved"])

    def test_negation_change_is_held_for_review(self):
        article = self.article("가상 사업은 승인되지 않았습니다.")
        _, validation, _ = resolve_draft(self.raw(article, "가상 사업은 승인됐습니다."), article)
        self.assertIn("polarity_unverified", validation["review_flags"])
        self.assertFalse(validation["approved"])

    def test_tentative_to_certain_is_not_approved(self):
        article = self.article("가상 행사를 열 계획입니다.")
        _, validation, _ = resolve_draft(self.raw(article, "가상 행사가 열렸습니다."), article)
        self.assertIn("certainty_change_suspected", validation["review_flags"])
        self.assertFalse(validation["approved"])

    def test_wire_schema_is_strict_and_only_accepts_id_links(self):
        schema = Draft.model_json_schema()
        def check(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertFalse(node["additionalProperties"])
                    self.assertEqual(set(node["required"]), set(node["properties"]))
                for child in node.values():
                    check(child)
            elif isinstance(node, list):
                for child in node:
                    check(child)
        check(schema)
        self.assertIn("evidence_links", schema["properties"])
        self.assertNotIn("evidence_snippets", schema["properties"])

    def test_public_shape_keeps_claim_quote_and_all_fields(self):
        article = self.article("가상 공원이 문을 열었습니다.")
        result, _, _ = resolve_draft(self.raw(article, "가상 공원의 문이 열렸습니다."), article)
        self.assertEqual({"status", "reason", "tts_sentences", "one_line", "detail", "evidence_snippets"},
                         set(result.model_dump()))
        self.assertEqual({"claim", "quote"}, set(result.evidence_snippets[0].model_dump()))
