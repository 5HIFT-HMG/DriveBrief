"""Bounded Korean relation warnings. Never proves entailment or changes approval."""
import re
from decimal import Decimal
from .quality_review import QUANTITY

# Explicit surface grammar only: no assumption that these cover all Korean relations.
_NUMBER = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_UNIT = r"(?:억\s*원|만\s*원|조\s*원|원|명|개|곳|대|kg|km|톤|%)"
_NOUN = r"[가-힣A-Za-z][가-힣A-Za-z0-9]{1,20}?"
SUBJECT = re.compile(r"(?<![가-힣A-Za-z0-9])(" + _NOUN +
                     r")(?:(?:으로|은|는|이|가|을|를|로)\s*|[:：]\s*|\s+)(" +
                     _NUMBER + r")\s*(" + _UNIT + r")")
_AMOUNT_FIRST = re.compile(r"(?<![\d,.])(" + _NUMBER + r")\s*(" + _UNIT +
                           r")의\s*(" + _NOUN + r")(?=은|는|이|가|을|를|와|과|[\s,.;!?]|$)")
ROLE = re.compile(r"([가-힣A-Za-z0-9]+(?:연구소|은행|협회|전자|상인회))\s*(담당자|대표|소장|책임자)\s*([가-힣]{2,4}?)(?:은|는|이|가)?(?=[\s,.:]|$)")
NEG = re.compile(r"않|못|없|금지|불가|아니")
TENTATIVE = re.compile(r"예정|계획|검토|가능|추정")
CERTAIN = re.compile(r"완료|확정|승인|개최했|열렸")
CONDITION = re.compile(r"전에는|이후에만|경우에만|한해서|조건|단,|제외|미만|이상")


def _quantities(text):
    """Recognize explicit local noun/quantity forms, not arbitrary paraphrase entailment."""
    forward = SUBJECT.findall(text)
    backward = [(subject, number, unit) for number, unit, subject in _AMOUNT_FIRST.findall(text)]
    for subject, number, unit in forward + backward:
        # Exact decimal equivalence only: no rounding or inferred unit conversion.
        value = format(Decimal(number.replace(",", "")), "f")
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        if Decimal(value).is_zero():
            value = "0"
        yield subject, value, re.sub(r"\s+", "", unit)


def relation_warnings(claim, references):
    """Warnings remain human-review-only: omissions/paraphrases may be legitimate."""
    context = "\n".join(references)
    warnings, findings = set(), []
    source = {}
    for subject, number, unit in _quantities(context):
        source.setdefault((subject, unit), set()).add(number)
    for subject, number, unit in _quantities(claim):
        known = source.get((subject, unit))
        if known and number not in known:
            warnings.add("subject_quantity_conflict_suspected")
            findings.append({"kind": "subject_quantity", "subject": subject, "unit": unit,
                             "claim_value": number, "linked_values": sorted(known)})
    roles = {}
    for organization, role, person in ROLE.findall(context):
        roles.setdefault((organization, role), set()).add(person)
    for organization, role, person in ROLE.findall(claim):
        known = roles.get((organization, role))
        if known and person not in known:
            warnings.add("organization_person_relation_conflict_suspected")
            findings.append({"kind": "organization_role", "organization": organization,
                             "role": role, "claim_person": person, "linked_people": sorted(known)})
    if NEG.search(context) and not NEG.search(claim):
        warnings.add("negation_context_requires_review")
    if TENTATIVE.search(context) and CERTAIN.search(claim):
        warnings.add("certainty_context_requires_review")
    if CONDITION.search(context) and not CONDITION.search(claim):
        warnings.add("condition_context_requires_review")
    # Aggregating IDs permits invalid cross-span joins; ID existence is insufficient.
    if len(references) > 1:
        warnings.add("multi_span_composition_requires_review")
        per_span = [set(QUANTITY.findall(s)) for s in references]
        claimed = set(QUANTITY.findall(claim))
        if len(claimed) > 1 and not any(claimed <= values for values in per_span):
            warnings.add("cross_span_quantity_join_requires_review")
    return {"warnings": sorted(warnings), "findings": findings,
            "entailment_verified": False, "automatic_rejection": False}
