"""Authored regression matrix; warning coverage, never measured LLM accuracy."""
import argparse
import hashlib
import json
from .factual_relations import compare_claim
from .validation import NEGATION, TENTATIVE, CERTAIN
from .claim_relations import relation_warnings


def cases():
    rows = []
    def add(name, category, error, source, claim, unsupported=False):
        rows.append(dict(id=name,category=category,error=error,references=source if isinstance(source,list) else [source],
                         claim=claim,unsupported=unsupported))
    add('negation_removed','negation',True,'새봄시는 야간버스를 도입하지 않는다.','새봄시는 야간버스를 도입한다.')
    add('negation_inserted','negation',True,'가온사는 지원금을 공개했다.','가온사는 지원금을 공개하지 않았다.')
    add('inability_removed','negation',True,'가온사는 지원금을 공개할 수 없다.','가온사는 지원금을 공개한다.')
    add('different_event_negation','negation',True,['새봄시는 야간버스를 도입하지 않는다.','새봄시는 안내문을 공개한다.'],
        '새봄시는 야간버스를 도입한다. 안내문을 공개하지 않는다.')
    add('tentative_to_present','certainty',True,'새봄시는 야간버스를 도입할 예정이다.','새봄시는 야간버스를 도입한다.')
    add('considering_to_completed','certainty',True,'가온사는 바다사를 인수하는 방안을 검토 중이다.','가온사는 바다사를 인수했다.')
    add('possibility_to_confirmed','certainty',True,'새봄시는 지원금을 추가할 가능성이 있다.','새봄시는 지원금 추가를 확정했다.')
    add('plan_to_completed','certainty',True,'가온사는 지원금을 공개할 계획이다.','가온사는 지원금을 공개했다.')
    add('acquirer_swap','actor',True,'가온사가 바다사를 인수했다.','바다사가 가온사를 인수했다.')
    add('seller_swap','actor',True,'가온사는 바다사를 매각했다.','바다사는 가온사를 매각했다.')
    add('supporter_swap','actor',True,'새봄시는 가온사를 지원한다.','가온사는 새봄시를 지원한다.')
    add('passive_swap','actor',True,'바다사는 가온사에 인수됐다.','가온사는 바다사에 인수됐다.')
    add('wrong_linked_event','grounding',True,'가온사는 바다사를 지원했다.','가온사는 바다사를 인수했다.')
    add('wrong_linked_sale','grounding',True,'가온사는 바다사를 인수했다.','가온사는 바다사를 매각했다.')
    add('wrong_linked_support','grounding',True,'새봄시는 가온사를 공개했다.','새봄시는 가온사를 지원했다.')
    add('correct_negative','normal',False,'새봄시는 야간버스를 도입하지 않는다.','새봄시는 야간버스를 도입하지 않습니다.')
    add('correct_plan','normal',False,'새봄시는 야간버스를 도입할 예정이다.','새봄시는 야간버스를 도입할 계획이다.')
    add('active_to_passive','normal',False,'가온사가 바다사를 인수했다.','바다사는 가온사에 의해 인수됐다.')
    add('passive_to_active','normal',False,'바다사는 가온사에 인수됐다.','가온사는 바다사를 인수했다.')
    add('object_first','normal',False,'가온사는 바다사를 인수했다.','바다사를 가온사가 인수했다.')
    add('unrelated_negative_clause','normal',False,['새봄시는 야간버스를 도입한다.','가온사는 지원금을 공개하지 않는다.'],
        '새봄시는 야간버스를 도입한다.')
    add('unrelated_tentative_clause','normal',False,['새봄시는 야간버스를 도입했다.','새봄시는 안내문을 공개할 예정이다.'],
        '새봄시는 야간버스를 도입했다.')
    add('completed_after_review','normal',False,'가온사는 바다사 인수를 검토 끝에 확정했다.','가온사는 바다사 인수를 확정했다.')
    add('mixed_polarity_same_event','normal',False,['새봄시는 야간버스를 도입하지 않는다.','가온시는 야간버스를 도입한다.'],
        '가온시는 야간버스를 도입한다.')
    add('separate_targets','normal',False,['가온사는 바다사를 인수하지 않는다.','가온사는 나래사를 인수했다.'],
        '가온사는 나래사를 인수했다.')
    add('double_negation','normal',False,'가온사는 지원금을 공개하지 않는 것은 아니다.','가온사는 지원금을 공개할 수 있다.')
    add('quoted_denial','normal',False,'가온사가 바다사를 인수했다는 주장은 사실이 아니다.','가온사가 바다사를 인수했다는 주장은 사실이 아니다.')
    add('unsupported_synonym','normal',False,'가온사는 바다사를 인수했다.','가온사는 바다사를 사들였다.')
    add('ordinary_omission','normal',False,['새봄시는 야간버스를 도입했다.','기존 일정에는 변경이 없다.'],
        '새봄시는 야간버스를 도입했다.')
    add('implicit_pronoun','unsupported',True,'가온사는 바다사를 인수했다.','그 회사는 자신이 상대 회사에 인수됐다고 밝혔다.',True)
    add('causal_invention','unsupported',True,'가온사는 바다사를 인수했다.','가온사는 정부의 지시 때문에 바다사를 인수했다.',True)
    add('unrecognized_event','unsupported',True,'가온사는 공장을 운영한다.','가온사는 공장을 폐쇄했다.',True)
    return rows


def warning_sets(row):
    claim,refs = row['claim'],row['references']
    context = '\n'.join(refs)
    old = set()
    if bool(NEGATION.search(claim)) != bool(NEGATION.search(context)):old.add('polarity_unverified')
    if TENTATIVE.search(context) and CERTAIN.search(claim):old.add('certainty_change_suspected')
    relation = set(relation_warnings(claim,refs)['warnings'])
    old |= relation & {'subject_quantity_conflict_suspected','organization_person_relation_conflict_suspected',
                       'negation_context_requires_review','certainty_context_requires_review'}
    comparison = compare_claim(claim,refs)
    new = set(comparison['warnings']) | (relation & {'subject_quantity_conflict_suspected','organization_person_relation_conflict_suspected'})
    if not comparison['scope_complete']:
        new |= old
    return sorted(old),sorted(new)


def evaluate():
    rows = cases()
    results = []
    for row in rows:
        before,after = warning_sets(row)
        results.append(dict(row,baseline_warnings=before,candidate_warnings=after))
    metrics = {}
    for name in ('baseline','candidate'):
        errors = [r for r in results if r['error']]
        normal = [r for r in results if not r['error']]
        detected = sum(bool(r[name+'_warnings']) for r in errors)
        false = sum(bool(r[name+'_warnings']) for r in normal)
        metrics[name] = dict(error_cases=len(errors),detected=detected,detection_rate=detected/len(errors),
                             normal_cases=len(normal),false_warnings=false,false_positive_rate=false/len(normal),
                             missed_ids=[r['id'] for r in errors if not r[name+'_warnings']],
                             false_warning_ids=[r['id'] for r in normal if r[name+'_warnings']])
    return dict(matrix_version='authored-factual-v1',fixture_hash=hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
                authored_cases_not_llm_accuracy=True,independent_holdout=False,automatic_approval=False,
                metrics=metrics,cases=results)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output');args=parser.parse_args()
    report=evaluate()
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report['metrics'],ensure_ascii=False,indent=2))


if __name__=='__main__':main()
