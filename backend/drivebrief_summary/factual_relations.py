"""Bounded proposition warnings; no entailment proof or automatic decision."""
import re

_ACTION = re.compile(r"(?<![가-힣])(시행|도입|시작|추가|인수|매각|지원|공개|승인|개최|중단)(?=하|합|했|한|할|되|됐|된|될|을|를|은|는|이|가|에|\s|$)")
_CLAUSE = re.compile(r"[.!?。;\n]+|\s+(?:하지만|그러나|반면|다만)\s+")
_NOUN = r"[가-힣A-Za-z][가-힣A-Za-z0-9_-]{0,30}?"
_SUBJECT = re.compile(r"(?<![가-힣A-Za-z0-9_-])(" + _NOUN + r")(?:은|는|이|가)(?=\s)")
_OBJECT = re.compile(r"(?<![가-힣A-Za-z0-9_-])(" + _NOUN + r")(?:을|를)(?=\s)")
_AGENT = re.compile(r"(?<![가-힣A-Za-z0-9_-])(" + _NOUN + r")(?:에게|에\s*의해|에)(?=\s)")
_NEGATIVE = re.compile(r"않|못|없|불가|금지|아니|안\s*(?:하|했)")
_TENTATIVE = re.compile(r"예정|계획|검토|가능|추정|논의|미정|확정되지")
_ASSERTED = re.compile(r"완료|확정(?:했|됐|되었|이다)|승인(?:했|됐)|^(?:했|하였|한다|합니다|됐|되었|된다)")
_AMBIGUOUS = re.compile(r"않.{0,16}아니|없.{0,16}아니|않.{0,16}없|사실이\s*아니|주장|여부|인용")


def propositions(text):
    result = []
    for clause in _CLAUSE.split(text):
        matches = list(_ACTION.finditer(clause))
        for index, match in enumerate(matches):
            prefix = clause[:match.start()]
            end = matches[index + 1].start() if index + 1 < len(matches) else len(clause)
            tail = clause[match.end():end][:100]
            subjects, objects = _SUBJECT.findall(prefix), _OBJECT.findall(prefix)
            actor = subjects[0] if len(subjects) == 1 else None
            target = objects[0] if len(objects) == 1 else None
            if re.match(r"(?:됐|되었|된|된다)", tail):
                agents = _AGENT.findall(prefix)
                target, actor = actor, agents[0] if len(agents) == 1 else None
            ambiguous = bool(_AMBIGUOUS.search(tail)) or len(subjects) > 1 or len(objects) > 1
            negative = bool(_NEGATIVE.search(tail))
            tentative = bool(_TENTATIVE.search(tail))
            if re.search(r"검토(?:를)?\s*(?:마친|거친|끝에|후)", tail) and re.search(r"확정|완료", tail):
                tentative = False
            result.append(dict(action=match.group(1), actor=actor, target=target,
                               negative=negative, tentative=tentative,
                               asserted=bool(_ASSERTED.search(tail)), ambiguous=ambiguous))
    return result


def compare_claim(claim, references):
    claims = propositions(claim)
    sources = [item for text in references for item in propositions(text)]
    warnings, findings = set(), []
    complete = bool(claims)
    for item in claims:
        if item['ambiguous']:
            complete = False
            continue
        same_action = [s for s in sources if s['action'] == item['action'] and not s['ambiguous']]
        def compatible(source):
            pairs = [(item[key], source[key]) for key in ('actor','target')]
            return all(a == b for a,b in pairs if a and b) and (any(a and b for a,b in pairs) or len(same_action) == 1)
        aligned = [s for s in same_action if compatible(s)]
        if not aligned:
            complete = False
            if item['actor'] and item['target'] and item['actor'] != item['target']:
                swapped = [s for s in same_action if s['actor'] == item['target'] and s['target'] == item['actor']]
                other_event = [s for s in sources if not s['ambiguous'] and s['actor'] == item['actor']
                               and s['target'] == item['target'] and s['action'] != item['action']]
                if swapped:
                    warnings.add('actor_object_reversal_suspected')
                    findings.append(dict(kind='actor_object_reversal',claim=item,linked=swapped))
                elif other_event:
                    warnings.add('linked_event_mismatch_suspected')
                    findings.append(dict(kind='linked_event_mismatch',claim=item,linked=other_event))
            continue
        polarities = {s['negative'] for s in aligned}
        if len(polarities) != 1:
            complete = False
            continue
        if item['negative'] not in polarities:
            warnings.add('predicate_polarity_conflict_suspected')
            findings.append(dict(kind='predicate_polarity',claim=item,linked=aligned))
        elif all(s['tentative'] for s in aligned) and item['asserted'] and not item['tentative']:
            warnings.add('certainty_overstatement_suspected')
            findings.append(dict(kind='certainty_overstatement',claim=item,linked=aligned))
    return dict(version='bounded-claim-review-v1',warnings=sorted(warnings),findings=findings,
                scope_complete=complete,entailment_verified=False,automatic_rejection=False,automatic_approval=False)
