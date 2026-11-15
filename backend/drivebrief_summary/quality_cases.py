"""Authored adversarial fixtures. Outcomes are validator coverage, never LLM accuracy."""
import argparse
import copy
import json
from pathlib import Path
from .models import Article
from .providers import MockProvider
from .validation import resolve_draft
from .quality_review import diagnostics
from .errors import SummaryError


def cases():
    article = Article.model_validate({
        "id": "quality-fiction", "title": "[가상] 연구소 실험 계획",
        "body": "가상 새봄연구소는 2026년 11월 13일 연구원 12명이 참여하는 실험 계획을 발표했습니다.\n"
                "가상 실험의 시험비는 300만원이고 임대료는 500만원이며 장비 4대를 추가할 예정입니다.\n"
                "연구소 담당자 김다온은 안전 검사를 마치기 전에는 실험을 시작하지 않는다고 설명했습니다.",
        "source": "DriveBrief 자체 작성 오류 주입 테스트",
        "rights": {"kind": "fictional", "external_llm_allowed": True, "summary_reuse_allowed": True,
                   "basis": "품질 회귀 테스트를 위해 자체 작성한 가상 자료"}})
    baseline = json.loads(MockProvider().generate(article))
    rows = [("control", baseline)]
    def changed(name, index, before, after):
        draft = copy.deepcopy(baseline)
        draft["tts_sentences"][index] = draft["tts_sentences"][index].replace(before, after)
        rows.append((name, draft))
    changed("unsupported_number", 0, "12명", "99명")
    changed("date_tuple_swap", 0, "11월 13일", "13월 11일")
    changed("person_with_role", 2, "김다온", "이새봄")
    changed("untitled_person_confusion", 2, "담당자 김다온은", "이새봄은")
    changed("number_unit_changed", 1, "300만원", "300명")
    changed("organization_changed", 0, "새봄연구소", "다온연구소")
    changed("negation_omitted", 2, "시작하지 않는다고", "시작한다고")
    changed("tentative_to_confirmed", 1, "추가할 예정입니다", "추가를 완료했습니다")
    invented = copy.deepcopy(baseline)
    invented["tts_sentences"][0] += " 지역 축제도 성공적으로 열었습니다."
    rows.append(("invented_event_without_new_number", invented))
    relation = copy.deepcopy(baseline)
    relation["tts_sentences"][1] = relation["tts_sentences"][1].replace("시험비는 300만원", "시험비는 500만원").replace("임대료는 500만원", "임대료는 300만원")
    rows.append(("same_unit_value_relation_swap", relation))
    omission = copy.deepcopy(baseline)
    omission["tts_sentences"] = baseline["tts_sentences"][:1]
    omission["detail"] = omission["tts_sentences"][0]
    first = baseline["evidence_links"][0]["evidence_ids"]
    omission["evidence_links"] = [
        {"target": target, "index": 0, "evidence_ids": first}
        for target in ("tts_sentences", "one_line", "detail")]
    rows.append(("safety_constraint_and_budget_omitted", omission))
    grounding = copy.deepcopy(baseline)
    grounding["evidence_links"][0]["evidence_ids"] = baseline["evidence_links"][1]["evidence_ids"]
    rows.append(("wrong_source_span", grounding))
    return article, rows


def run_cases():
    article, rows = cases()
    output = []
    for name, draft in rows:
        try:
            _, validation, _ = resolve_draft(json.dumps(draft, ensure_ascii=False), article)
            extra = diagnostics(article, draft)
            output.append({"case": name, "core_outcome": "accepted_needs_review",
                           "approved": validation["approved"], "review_flags": validation["review_flags"],
                           "supplementary_warnings": sorted({flag for r in extra["claims"] for flag in r["warnings"]}),
                           "unreferenced_body_spans": len(extra["unreferenced_body_ids"]),
                           "comparison": extra})
        except SummaryError as e:
            output.append({"case": name, "core_outcome": "rejected", "error": e.code, "approved": False})
    return {"fixture_only_not_llm_performance": True, "cases": output}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    report = run_cases()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps({"fixture_cases": len(report["cases"]), "automatic_approvals": 0,
                      "rejected": sum(r["core_outcome"] == "rejected" for r in report["cases"])}))


if __name__ == "__main__":
    main()
