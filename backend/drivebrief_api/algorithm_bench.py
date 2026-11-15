"""Authored offline stress cases: NOT real LLM accuracy or human approvals."""
import argparse
import copy
import json
import time
import tracemalloc
from pathlib import Path
from datetime import datetime, timezone
from .algorithm_v2 import budget_candidate, prefix_digest
from .pipeline_settings import load_config
from .planning import plan
from .quality import write_json
from drivebrief_summary.quality_cases import run_cases
from drivebrief_summary.claim_relations import relation_warnings

NEW_WARNINGS = {"subject_quantity_conflict_suspected", "organization_person_relation_conflict_suspected",
                "cross_span_quantity_join_requires_review", "multi_span_composition_requires_review",
                "negation_context_requires_review", "certainty_context_requires_review", "condition_context_requires_review"}


def relation_bench():
    fixtures = [
        ("quantity_swap", "시험비는 500만원이고 임대료는 300만원입니다.",
         ["시험비는 300만원이고 임대료는 500만원입니다."], "subject_quantity_conflict_suspected"),
        ("quantity_control", "시험비는 300만원이고 임대료는 500만원입니다.",
         ["시험비는 300만원이고 임대료는 500만원입니다."], None),
        ("role_swap", "새봄연구소 담당자 이새봄은 계획을 설명했습니다.",
         ["새봄연구소 담당자 김다온은 계획을 설명했습니다. 다온은행 담당자 이새봄은 예산을 설명했습니다."],
         "organization_person_relation_conflict_suspected"),
        ("role_control", "새봄연구소 담당자 김다온은 계획을 설명했습니다.",
         ["새봄연구소 담당자 김다온은 계획을 설명했습니다."], None),
        ("negation_omission", "실험을 시작합니다.", ["실험을 시작하지 않습니다."], "negation_context_requires_review"),
        ("certainty_change", "실험 승인을 완료했습니다.", ["실험 승인을 검토할 예정입니다."], "certainty_context_requires_review"),
        ("condition_omission", "경기를 시작합니다.", ["안전 검사 이후에만 경기를 시작합니다."], "condition_context_requires_review"),
        ("mixed_join", "시험비는 300만원이고 참가자는 12명입니다.",
         ["시험비는 300만원입니다.", "다른 실험 참가자는 12명입니다."], "cross_span_quantity_join_requires_review"),
        # Correct composition also warns: explicit false-positive demonstration.
        ("valid_composition_control", "시험비는 300만원이고 참가자는 12명입니다.",
         ["시험비는 300만원입니다.", "같은 실험 참가자는 12명입니다."], None),
        # Parser cannot prove a new action or a paraphrased relation false.
        ("new_event_blindspot", "지역 주민에게 상품을 제공했습니다.", ["지역 실험을 검토 중입니다."], None),
    ]
    output = []
    tracemalloc.start()
    start = time.perf_counter()
    for name, claim, refs, target in fixtures:
        result = relation_warnings(claim, refs)
        output.append(dict(case=name, expected_specific_warning=target,
                           specific_warning_observed=bool(target and target in result["warnings"]),
                           warnings=result["warnings"], findings=result["findings"],
                           entailment_verified=result["entailment_verified"]))
    elapsed = (time.perf_counter()-start)*1000
    _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    existing=run_cases()
    swap=next(r for r in existing["cases"] if r["case"]=="same_unit_value_relation_swap")
    return dict(authored_cases_not_llm_performance=True, new_fixtures=output,
                targeted_error_cases=sum(target is not None for _,_,_,target in fixtures),
                targeted_warnings_observed=sum(r["specific_warning_observed"] for r in output),
                valid_composition_false_warning_demonstrated=bool(next(r for r in output if r["case"]=="valid_composition_control")["warnings"]),
                existing_quantity_swap_old_specific_warning=False,
                existing_quantity_swap_new_warning="subject_quantity_conflict_suspected" in swap["supplementary_warnings"],
                existing_matrix=existing,
                runtime_ms_with_tracemalloc=elapsed, python_alloc_peak_bytes=peak,
                runtime_not_nli_benchmark=True, external_calls=0, automatic_approvals=0)


def planning_fixture():
    # No store/API ingestion: these approved flags simulate reviewed input for a unit experiment.
    return {"schema_version":"approved-briefing-v1","fictional_only":True,"articles":[
        dict(article_id="lab-"+str(i),title="자체 작성 실험 "+str(i),source="가상 편성 실험",
             published_at="2026-11-13T09:00:00+09:00",source_url=None,categories=[cat],
             validation={"status":"approved","approved":True,"review_required":False},
             tts_sentences=[f"가상 실험 {i}의 참가자를 모집할 예정입니다.",
                            f"가상 실험 {i}은 안전 검사를 통과한 경우에만 시작합니다.",
                            f"가상 실험 {i}의 자세한 일정은 이후 안내합니다."],
             one_line="가상 실험 참가자 모집과 안전 조건",detail="안전 검사 전에는 시작하지 않는 가상 편성용 자료")
        for i,cat in enumerate(["IT","사회","경제"])]}


def planning_bench():
    doc=planning_fixture();cfg=load_config();now=datetime(2026,11,13,tzinfo=timezone.utc)
    constraints={a["article_id"]:dict(minimum_prefix=2, reviewer="authored-fixture-simulation",
                                    approved_text_hash=prefix_digest(a)) for a in doc["articles"]}
    rows=[]
    for option in cfg["length_seconds"]:
        baseline=plan(doc,option,[],cfg,now)
        start=time.perf_counter()
        candidate=budget_candidate(doc,option,[],cfg,now,constraints=constraints)
        elapsed=(time.perf_counter()-start)*1000
        def report(result):
            articles=result["articles"]
            return {"article_count":len(articles),"sentence_count":sum(len(a["tts_sentences"]) for a in articles),
                    "estimated_seconds":result["estimated_seconds"],
                    "unused_seconds":round(cfg["length_seconds"][option]-result["estimated_seconds"],3),
                    "fixture_required_context_missing_articles":sum(len(a["tts_sentences"])<2 for a in articles),
                    "prefix_lengths":{a["article_id"]:len(a["tts_sentences"]) for a in articles},
                    "full_summary_preserved":all(a["detail"]==next(x for x in doc["articles"] if x["article_id"]==a["article_id"])["detail"] for a in articles)}
        rows.append(dict(option=option,baseline=report(baseline),candidate=report(candidate),candidate_ms=elapsed))
    return {"fixture_simulated_approval_not_service_data":True,"minimum_prefix_is_authored_test_annotation":True,
            "semantic_quality_not_measured":True,"options":rows}


def grouping_bench():
    from .selection import metadata, group_events
    from .algorithm_v2 import normalized_candidate
    cfg = load_config()
    a = dict(url="https://example.test/a", title="가상연구소는 서울공원에서 로봇실험을 진행",
             description="가상연구소는 서울공원에서 로봇실험을 진행합니다",
             source="자체A",category="IT",published_at="2026-11-13T09:00:00+09:00")
    b = dict(a,url="https://example.test/b", title="가상연구소 서울공원 로봇실험 진행",
             description="가상연구소 서울공원 로봇실험 진행합니다",source="자체B")
    fixtures = [("particle_variant_same_event",b,True),
                ("different_day_not_same_event",dict(b,published_at="2026-11-10T09:00:00+09:00"),False),
                ("different_location",dict(b,title=b["title"].replace("서울공원","부산공원")),False),
                ("different_action",dict(b,title="가상연구소 신제품 출시 행사",description="새로운 제품 출시입니다"),False),
                ("title_number_conflict",dict(b,title=b["title"]+" 20명"),False)]
    # Give both sides explicit conflicting quantities for the numeric negative case.
    output=[]
    for name,right,truth in fixtures:
        left=dict(a,title=a["title"]+" 10명") if name=="title_number_conflict" else a
        items=metadata([left,right])
        old=len(group_events(items,cfg))==1
        new=len(normalized_candidate(items,cfg))==1
        output.append(dict(case=name,authored_truth=truth,baseline_same=old,candidate_same=new))
    return {"authored_fixture_not_rss_accuracy":True,"cases":output,
            "baseline_correct":sum(r["authored_truth"]==r["baseline_same"] for r in output),
            "candidate_correct":sum(r["authored_truth"]==r["candidate_same"] for r in output)}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    result={"summary":relation_bench(),"planning":planning_bench(),"grouping":grouping_bench()}
    write_json(args.output,result)
    print(json.dumps({"summary_targeted":result["summary"]["targeted_error_cases"],
                      "warnings_observed":result["summary"]["targeted_warnings_observed"],
                      "planning":result["planning"],"grouping":result["grouping"]},ensure_ascii=False))


if __name__=="__main__":
    main()
