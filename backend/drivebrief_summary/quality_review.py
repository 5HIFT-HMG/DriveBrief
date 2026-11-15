"""Supplementary human-review warnings, not approval or a semantic fact checker."""
import re
from .models import Draft
from .segments import split_article
from .factual_relations import compare_claim

QUANTITY = re.compile(r"([+-]?\d+(?:[.,]\d+)*)\s*(억원|만원|조원|원|명|개|곳|대|kg|km|톤|%|킬로미터|미터)")
ORGANIZATION = re.compile(r"[가-힣A-Za-z0-9]+(?:연구소|상인회|전자|은행|협회|의회|시청)")


def diagnostics(article, draft):
    value = Draft.model_validate(draft)
    spans = {s.id: s for s in split_article(article)}
    outputs = {("tts_sentences", i): text for i, text in enumerate(value.tts_sentences)}
    outputs.update({("one_line", 0): value.one_line, ("detail", 0): value.detail})
    rows, used = [], set()
    for link in value.evidence_links:
        claim = outputs[(link.target, link.index)]
        used.update(link.evidence_ids)
        context = "\n".join(spans[i].text for i in link.evidence_ids)
        source_quantities = set(QUANTITY.findall(context))
        warnings = ["semantic_entailment_unverified"]
        if set(QUANTITY.findall(claim))-source_quantities:
            warnings.append("quantity_unit_pair_requires_review")
        if set(ORGANIZATION.findall(claim))-set(ORGANIZATION.findall(context)):
            warnings.append("organization_requires_review")
        from .claim_relations import relation_warnings
        relation = relation_warnings(claim, [spans[i].text for i in link.evidence_ids])
        warnings.extend(relation["warnings"])
        factual = compare_claim(claim, [spans[i].text for i in link.evidence_ids])
        if factual['scope_complete']:
            warnings = [w for w in warnings if w not in ('negation_context_requires_review','certainty_context_requires_review')]
        warnings.extend(factual['warnings'])
        rows.append({"target": link.target, "index": link.index, "claim": claim,
                     "evidence_ids": link.evidence_ids, "source_text": context,
                     "warnings": sorted(set(warnings)), "relation_diagnostics": relation, "factual_diagnostics": factual})
    body = {s.id for s in spans.values() if s.field == "body"}
    return {"diagnostic_version": "human-quality-warnings-v3", "automatic_approval": False,
            "warnings_are_not_error_verdicts": True, "claims": rows,
            "body_spans": len(body), "referenced_body_spans": len(body & used),
            "unreferenced_body_ids": sorted(body-used),
            "coverage_note": "미참조 구간이 곧 생략 오류는 아닙니다. 중요한 제약·시점의 누락 여부를 사람이 확인하세요."}
