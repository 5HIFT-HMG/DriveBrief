import re
from pydantic import ValidationError
from .errors import SummaryError
from .models import Article, Draft, Evidence, Summary
from .segments import split_article
from .factual_relations import compare_claim

VALIDATION_VERSION = "grounding-v3-id-review"
# Deliberately conservative detectors, NOT a semantic/NLP fact verifier.
PERSON = re.compile(r"(?:연구소장|조합장|담당자|책임자|대표|관장|의장|소장)\s*([가-힣]{2,4}?)(?:은|는|이|가|을|를)?(?=[\s,.:]|$)")
DATE = re.compile(r"(\d{4})\s*(?:년\s*|[-/.])(\d{1,2})\s*(?:월\s*|[-/.])(\d{1,2})\s*일?")
MONTH_DAY = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")
NUMBER = re.compile(r"[+-]?\d+(?:[.,]\d+)*")
NEGATION = re.compile(r"않|아니|없|못|미정|미확정|취소|보류|불가")
TENTATIVE = re.compile(r"예정|계획|검토|가능|미정|확정되지|추정")
CERTAIN = re.compile(r"완료|확정됐|확정했|승인됐|승인했|열렸|개최했|개최됐")


def normalize_space(text):
    return re.sub(r"[ \t\r\n]+", " ", text).strip()


def resolve_draft(raw: str, article: Article):
    try:
        draft = Draft.model_validate_json(raw)
    except (ValidationError, ValueError):
        raise SummaryError("invalid_json", "LLM draft failed JSON/schema validation") from None
    fields = draft.model_dump(exclude={"evidence_links"})
    if draft.status == "insufficient":
        return Summary(**fields, evidence_snippets=[]), {
            "status": "insufficient", "approved": False, "review_required": True,
            "checks": [], "review_flags": ["source_insufficient"]}, []
    spans = {span.id: span for span in split_article(article)}
    outputs = {("tts_sentences", i): text for i, text in enumerate(draft.tts_sentences)}
    outputs[("one_line", 0)] = draft.one_line
    outputs[("detail", 0)] = draft.detail
    linked = {}
    for index, link in enumerate(draft.evidence_links):
        target = (link.target, link.index)
        if target not in outputs:
            raise SummaryError("invalid_evidence", f"reason=invalid_target; link_index={index}")
        if target in linked:
            raise SummaryError("invalid_evidence", f"reason=duplicate_target; link_index={index}")
        if len(set(link.evidence_ids)) != len(link.evidence_ids):
            raise SummaryError("invalid_evidence", f"reason=duplicate_id; link_index={index}")
        if any(span_id not in spans for span_id in link.evidence_ids):
            raise SummaryError("invalid_evidence", f"reason=unknown_id; link_index={index}")
        linked[target] = [spans[span_id] for span_id in link.evidence_ids]
    if set(linked) != set(outputs):
        raise SummaryError("missing_evidence", f"reason=uncovered_output; missing_count={len(set(outputs) - set(linked))}")
    evidence = []
    # No draft is automatically approved, including extractive/mock drafts.
    flags = {"semantic_entailment_unverified", "context_and_coverage_review"}
    source_all = [normalize_space(span.text) for span in spans.values()]
    for index, (target, claim) in enumerate(outputs.items()):
        references = linked[target]
        context = "\n".join(span.text for span in references)
        def numeric_text(text):
            # Date notation may change, but date tuples below must still be identical.
            return DATE.sub(lambda m: " ".join(str(int(part)) for part in m.groups()), text)
        claim_numbers = set(NUMBER.findall(numeric_text(claim)))
        if claim_numbers - set(NUMBER.findall(numeric_text(context))):
            raise SummaryError("unsupported_number", f"reason=number_not_in_linked_evidence; output_index={index}")
        # Compare date tuples, not unordered numbers (11/12 != 12/11).
        dates = {tuple(map(int, parts)) for parts in DATE.findall(claim)}
        source_dates = {tuple(map(int, parts)) for parts in DATE.findall(context)}
        short_dates = {tuple(map(int, parts)) for parts in MONTH_DAY.findall(claim)}
        source_short = {tuple(map(int, parts)) for parts in MONTH_DAY.findall(context)}
        source_short |= {(m, d) for _, m, d in source_dates}
        if dates - source_dates or short_dates - source_short:
            raise SummaryError("unsupported_date", f"reason=date_not_in_linked_evidence; output_index={index}")
        people = set(PERSON.findall(claim))
        if any(person not in context for person in people):
            raise SummaryError("unsupported_person", f"reason=person_not_in_linked_evidence; output_index={index}")
        # Supplement review warnings without changing approval or rejection policy.
        # False positives are possible; no model retry or silent repair is attempted.
        claim_review = compare_claim(claim, [span.text for span in references])
        flags.update(claim_review['warnings'])
        if claim_review['scope_complete']:
            if 'predicate_polarity_conflict_suspected' in claim_review['warnings']:
                flags.add('polarity_unverified')
            if 'certainty_overstatement_suspected' in claim_review['warnings']:
                flags.add('certainty_change_suspected')
        else:
            if bool(NEGATION.search(claim)) != bool(NEGATION.search(context)):
                flags.add('polarity_unverified')
            if TENTATIVE.search(context) and CERTAIN.search(claim):
                flags.add('certainty_change_suspected')
        normalized = normalize_space(claim)
        local = [normalize_space(span.text) for span in references]
        if normalized in source_all and normalized not in local:
            raise SummaryError("invalid_evidence", f"reason=unrelated_exact_source; output_index={index}")
        if not any(normalized == quote for quote in local):
            flags.add("paraphrase_requires_review")
        # Textual overlap and an ID's existence never prove entailment or relevance.
        evidence.extend(Evidence(claim=claim, quote=span.text) for span in references)
    return Summary(**fields, evidence_snippets=evidence), {
        "status": "needs_review", "approved": False, "review_required": True,
        "checks": ["schema", "id_resolution", "target_coverage", "linked_numbers",
                   "recognized_dates", "recognized_person_patterns"],
        "review_flags": sorted(flags),
    }, [link.model_dump() for link in draft.evidence_links]
