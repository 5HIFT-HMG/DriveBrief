import json
import unittest
from drivebrief_summary.factual_cases import cases,evaluate
from drivebrief_summary.factual_relations import compare_claim
from drivebrief_summary.models import Article
from drivebrief_summary.segments import split_article
from drivebrief_summary.validation import resolve_draft


class FactualRelationTests(unittest.TestCase):
    def test_explicit_distortions_receive_scoped_warnings(self):
        expected={'negation':'predicate_polarity_conflict_suspected','certainty':'certainty_overstatement_suspected',
                  'actor':'actor_object_reversal_suspected','grounding':'linked_event_mismatch_suspected'}
        for row in cases():
            if row['error'] and not row['unsupported']:
                with self.subTest(case=row['id']):
                    self.assertIn(expected[row['category']],compare_claim(row['claim'],row['references'])['warnings'])

    def test_normal_rewordings_are_not_new_error_verdicts(self):
        for row in cases():
            if not row['error']:
                with self.subTest(case=row['id']):
                    self.assertEqual([],compare_claim(row['claim'],row['references'])['warnings'])

    def test_unknown_and_complex_semantics_are_never_declared_verified(self):
        for row in cases():
            result=compare_claim(row['claim'],row['references'])
            self.assertFalse(result['entailment_verified'])
            self.assertFalse(result['automatic_approval'])
            self.assertFalse(result['automatic_rejection'])
        report=evaluate()
        self.assertLess(report['metrics']['candidate']['false_positive_rate'],report['metrics']['baseline']['false_positive_rate'])
        self.assertGreater(report['metrics']['candidate']['detection_rate'],report['metrics']['baseline']['detection_rate'])
        self.assertIn('causal_invention',report['metrics']['candidate']['missed_ids'])
        self.assertFalse(report['independent_holdout'])

    def article(self,body):
        return Article(id='factual-fixture',title='자체 작성 가상 기사',body=body,source='테스트',
                       rights={'kind':'fictional','external_llm_allowed':True,'summary_reuse_allowed':True,'basis':'자체 회귀 자료'})

    def draft(self,claim,ids):
        return json.dumps(dict(status='ok',reason='',tts_sentences=[claim],one_line=claim,detail=claim,
            evidence_links=[dict(target=target,index=0,evidence_ids=ids) for target in ('tts_sentences','one_line','detail')]),ensure_ascii=False)

    def test_existing_evidence_id_is_not_treated_as_entailment(self):
        article=self.article('가온사는 바다사를 지원했다. 가온사는 바다사를 인수했다.')
        spans=[span for span in split_article(article) if span.field=='body']
        claim='가온사는 바다사를 인수했습니다.'
        _,bad,_=resolve_draft(self.draft(claim,[spans[0].id]),article)
        self.assertIn('linked_event_mismatch_suspected',bad['review_flags'])
        summary,good,_=resolve_draft(self.draft(claim,[spans[1].id]),article)
        self.assertNotIn('linked_event_mismatch_suspected',good['review_flags'])
        self.assertEqual(summary.tts_sentences,[claim])
        self.assertEqual(good['status'],'needs_review')
        self.assertFalse(good['approved'])

    def test_unrelated_negation_is_not_attached_to_correct_positive_claim(self):
        article=self.article('새봄시는 야간버스를 도입한다. 가온사는 지원금을 공개하지 않는다.')
        ids=[span.id for span in split_article(article) if span.field=='body']
        _,validation,_=resolve_draft(self.draft('새봄시는 야간버스를 도입합니다.',ids),article)
        self.assertNotIn('polarity_unverified',validation['review_flags'])
        self.assertFalse(validation['approved'])

    def test_opposing_aligned_sources_remain_ambiguous(self):
        result=compare_claim('가온사는 바다사를 인수했다.',[
            '가온사는 바다사를 인수하지 않았다.','가온사는 바다사를 인수했다.'])
        self.assertFalse(result['scope_complete'])
        self.assertFalse(result['entailment_verified'])
