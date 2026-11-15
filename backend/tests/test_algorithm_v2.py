import copy
import json
import unittest
from datetime import datetime, timezone
from drivebrief_api.algorithm_v2 import budget_candidate, prefix_digest, normalized_candidate
from drivebrief_api.algorithm_evaluation import ranking_bundle, ranking_metrics, pair_dossier, ranking_identity
from drivebrief_api.quality import sample_pairs
from drivebrief_api.pipeline_settings import load_config
from drivebrief_api.selection import metadata, group_events
from drivebrief_api.planning import plan
from drivebrief_summary.claim_relations import relation_warnings
from drivebrief_summary.quality_cases import run_cases

NOW = datetime(2026, 11, 13, tzinfo=timezone.utc)


def fixture_items():
    return metadata([dict(url="https://example.test/"+str(i),title=title,description=desc,
        source="가상신문"+str(i%2),category=cat,published_at="2026-11-13T09:00:00+09:00")
        for i,(title,desc,cat) in enumerate([
            ("가상 연구소는 안전 실험 계획 발표", "연구소는 안전 검사를 진행한다", "IT"),
            ("가상 연구소 안전 실험 계획 발표", "연구소 안전 검사를 진행한다", "IT"),
            ("가상 연구소 실험 장비 화재 사고", "장비 화재 진화 작업이다", "사회"),
            ("다른 공원 행사 취소", "행사 안전 검토 중", "사회")])])


def document():
    return {"schema_version":"approved-briefing-v1", "fictional_only":True, "articles":[
        dict(article_id=str(i),title="가상 기사 "+str(i),source="자체 자료",source_url=None,
             published_at="2026-11-13T09:00:00+09:00",categories=["IT"],
             tts_sentences=[f"가상 기사 {i} 계획입니다.", f"가상 기사 {i} 조건은 승인 이후입니다.", f"가상 기사 {i} 보충입니다."],
             one_line="자체 작성",detail="가상 실험 요약", validation={"status":"approved","approved":True,"review_required":False})
        for i in range(3)]}


class AlgorithmCandidateTests(unittest.TestCase):
    def test_authored_grouping_cases_and_time_guard(self):
        from drivebrief_api.algorithm_bench import grouping_bench
        report = grouping_bench()
        cases = {r["case"]: r for r in report["cases"]}
        self.assertTrue(cases["particle_variant_same_event"]["candidate_same"])
        self.assertFalse(cases["different_day_not_same_event"]["candidate_same"])
        self.assertFalse(cases["different_location"]["candidate_same"])
        self.assertFalse(cases["title_number_conflict"]["candidate_same"])

    def test_group_normalization_only_experimental_and_deterministic(self):
        items = fixture_items(); original = copy.deepcopy(items); cfg = load_config()
        candidate = normalized_candidate(items,cfg)
        self.assertEqual(original, items)
        self.assertEqual(candidate, normalized_candidate(list(reversed(items)),cfg))
        # Same corporation, distinct event must not be joined on this authored fixture.
        groups = [{r["source_url"] for r in g["members"]} for g in candidate]
        self.assertFalse(any("https://example.test/0" in g and "https://example.test/2" in g for g in groups))

    def test_pair_labels_still_required_and_candidate_not_truth(self):
        bundle = sample_pairs(fixture_items(),load_config(),6)
        report = pair_dossier(bundle,[])
        self.assertEqual(0, report["human_labels"])
        self.assertIsNone(report["candidate"]["f1"])
        self.assertFalse(report["candidate_default_enabled"])
        with self.assertRaises(ValueError):
            pair_dossier(bundle,[dict(pair_id=bundle["pairs"][0]["pair_id"],source_hash="changed",human_label="same_event")])

    def test_rank_metrics_need_complete_explicit_human_pool(self):
        bundle = ranking_bundle(fixture_items(),load_config(),NOW,["IT"],k=3)
        labels = [dict(group_id=r["group_id"],pool_hash=bundle["pool_hash"],relevance="",reviewer="")
                  for r in bundle["review_pool"]]
        self.assertEqual({},ranking_metrics(bundle,labels)["models"])
        # Authored unit-test grades only; not real RSS human labels.
        for i,row in enumerate(labels):
            row.update(relevance=str(i%4),reviewer="fixture-author")
        metrics = ranking_metrics(bundle,labels)
        for model in metrics["models"].values():
            self.assertGreaterEqual(model["ndcg_at_k"],0); self.assertLessEqual(model["ndcg_at_k"],1)
        labels[0]["pool_hash"]="stale"
        with self.assertRaises(ValueError): ranking_metrics(bundle,labels)

    def test_rank_context_change_invalidates_old_grades(self):
        bundle = ranking_bundle(fixture_items(),load_config(),NOW,["IT"],k=3)
        changed = copy.deepcopy(bundle); changed["interests"] = ["사회"]
        with self.assertRaises(ValueError): ranking_metrics(changed,[])
        changed = copy.deepcopy(bundle); changed["as_of"] = "2026-11-14T00:00:00+00:00"
        with self.assertRaises(ValueError): ranking_metrics(changed,[])

    def test_rank_metrics_known_ndcg_and_no_relevant_edge(self):
        bundle = {"k":2,"as_of":NOW.isoformat(),"interests":[],"review_pool":[{"group_id":"a"},{"group_id":"b"}],
                  "models":{"best":[{"group_id":"a"},{"group_id":"b"}],
                            "reverse":[{"group_id":"b"},{"group_id":"a"}]}}
        from drivebrief_api.quality import fingerprint
        bundle["pool_hash"]=ranking_identity(bundle["review_pool"],bundle["as_of"],bundle["interests"],bundle["k"])
        labels=[dict(group_id=gid,pool_hash=bundle["pool_hash"],relevance=grade,reviewer="fixture")
                for gid,grade in [("a","3"),("b","0")]]
        result=ranking_metrics(bundle,labels)
        self.assertEqual(1,result["models"]["best"]["ndcg_at_k"])
        self.assertLess(result["models"]["reverse"]["ndcg_at_k"],1)
        for row in labels: row["relevance"]="0"
        self.assertIsNone(ranking_metrics(bundle,labels)["models"]["best"]["ndcg_at_k"])

    def test_budget_preserves_approved_prefix_and_bounds(self):
        doc=document(); before=copy.deepcopy(doc); cfg=load_config()
        for option in cfg["length_seconds"]:
            result=budget_candidate(doc,option,[],cfg,NOW)
            self.assertLessEqual(result["estimated_seconds"],result["target_seconds"])
            sentences=[]
            for row in result["articles"]:
                original=next(a for a in doc["articles"] if a["article_id"]==row["article_id"])
                self.assertEqual(original["tts_sentences"][:len(row["tts_sentences"])],row["tts_sentences"])
                sentences+=row["tts_sentences"]
            self.assertEqual(len(sentences),len(set(sentences)))
        self.assertEqual(before,doc)

    def test_required_context_bound_to_reviewed_text_revision(self):
        doc=document();cfg=load_config()
        constraints={a["article_id"]:dict(minimum_prefix=2,reviewer="fixture-author",
                         approved_text_hash=prefix_digest(a)) for a in doc["articles"]}
        result=budget_candidate(doc,"짧게",[],cfg,NOW,constraints=constraints)
        self.assertTrue(result["articles"])
        self.assertTrue(all(len(a["tts_sentences"])>=2 for a in result["articles"]))
        doc["articles"][0]["tts_sentences"][0]+=" 수정"
        with self.assertRaises(ValueError): budget_candidate(doc,"짧게",[],cfg,NOW,constraints=constraints)

    def test_unapproved_empty_duplicate_and_infeasible(self):
        cfg=load_config();doc=document()
        doc["articles"][0]["validation"]["approved"]=False
        with self.assertRaises(ValueError): budget_candidate(doc,"중간",[],cfg,NOW)
        doc=document();cfg["length_seconds"]["짧게"]=1
        self.assertEqual([],budget_candidate(doc,"짧게",[],cfg,NOW)["articles"])
        self.assertEqual([],budget_candidate(dict(doc,articles=[]),"중간",[],cfg,NOW)["articles"])
        doc["articles"][1]["tts_sentences"][0]=doc["articles"][0]["tts_sentences"][0]
        result=budget_candidate(doc,"길게",[],cfg,NOW)
        texts=[s for a in result["articles"] for s in a["tts_sentences"]]
        self.assertEqual(len(texts),len(set(texts)))


class RelationTests(unittest.TestCase):
    def test_known_quantity_target_swap_now_warns(self):
        report=run_cases()
        row=next(r for r in report["cases"] if r["case"]=="same_unit_value_relation_swap")
        self.assertIn("subject_quantity_conflict_suspected",row["supplementary_warnings"])
        self.assertEqual("accepted_needs_review",row["core_outcome"])
        self.assertFalse(row["approved"])

    def test_role_relation_swap_and_correct_control(self):
        source=["새봄연구소 담당자 김다온은 시험을 설명했습니다. 다온은행 담당자 이새봄은 예산을 설명했습니다."]
        wrong=relation_warnings("새봄연구소 담당자 이새봄은 시험을 설명했습니다.",source)
        self.assertIn("organization_person_relation_conflict_suspected",wrong["warnings"])
        correct=relation_warnings("새봄연구소 담당자 김다온은 시험을 설명했습니다.",source)
        self.assertNotIn("organization_person_relation_conflict_suspected",correct["warnings"])

    def test_multi_span_join_and_negation_condition(self):
        result=relation_warnings("시험비는 300만원이고 참가자는 12명입니다.",
                                 ["시험비는 300만원입니다.","참가자는 12명이며 승인 전에는 시작하지 않습니다."])
        self.assertIn("cross_span_quantity_join_requires_review",result["warnings"])
        self.assertIn("condition_context_requires_review",result["warnings"])
        self.assertIn("negation_context_requires_review",result["warnings"])
        self.assertFalse(result["automatic_rejection"])

    def test_ambiguous_and_paraphrase_not_falsely_declared_verified(self):
        # No parser coverage for paraphrased subject relation: must remain review-only.
        result=relation_warnings("모든 일이 성공했습니다.",["가상 행사는 검토 단계입니다."])
        self.assertFalse(result["entailment_verified"])
        self.assertFalse(result["automatic_rejection"])
