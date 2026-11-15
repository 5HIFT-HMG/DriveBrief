"""Timing-only profiles trained before a disjoint validation recording; no policy weights."""
import argparse
import copy
import json
import math
from pathlib import Path

from .timing_quality import measured,unique_sentences,fit,errors


def profile(training):
    rows,_=measured(training)
    unique=unique_sentences(rows)
    if len(unique)<8 or len({r['article_id'] for r in rows})<2:
        raise ValueError('insufficient_training_sentences')
    coefficients=fit(unique)
    if coefficients is None:
        raise ValueError('timing_fit_not_identifiable')
    return dict(schema='pleos-timing-profile-v1',engine='pleos-on-device',sdk_version=rows[0]['sdk_version'],locale=rows[0]['locale'],
                coefficients=coefficients,training_hashes=sorted({r['text_sha256'] for r in rows}),
                training_articles=sorted({r['article_id'] for r in rows}),training_attempts=sorted({r['attempt_id'] for r in rows}),
                independent_validation=None)


def validate_profile(model):
    if model.get('schema')!='pleos-timing-profile-v1' or model.get('engine')!='pleos-on-device' or model.get('locale')!='ko-KR':
        raise ValueError('invalid_timing_profile')
    values=model['coefficients']
    if set(values)!={'characters_per_second','sentence_pause_seconds'}:
        raise ValueError('invalid_timing_coefficients')
    for key,low,high in [('characters_per_second',.5,30),('sentence_pause_seconds',0,5)]:
        value=values[key]
        if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:
            raise ValueError('invalid_timing_coefficients')
    return model


def validate(model,testing,baseline):
    validate_profile(model)
    rows,excluded=measured(testing)
    unique=unique_sentences(rows)
    if len(unique)<6 or len({r['article_id'] for r in rows})<2:
        raise ValueError('insufficient_validation_sentences')
    if set(model['training_hashes']) & {r['text_sha256'] for r in rows} or set(model['training_articles']) & {r['article_id'] for r in rows} or set(model['training_attempts']) & {r['attempt_id'] for r in rows}:
        raise ValueError('validation_overlaps_training')
    if {(r['sdk_version'],r['locale']) for r in rows}!={(model['sdk_version'],model['locale'])}:
        raise ValueError('validation_environment_changed')
    before=errors(unique,baseline)
    after=errors(unique,dict(baseline,**model['coefficients']))
    result=copy.deepcopy(model)
    result['independent_validation']=dict(sentences=len(unique),articles=len({r['article_id'] for r in rows}),
        validation_hashes=sorted({r['text_sha256'] for r in rows}),baseline=before,candidate=after,excluded=excluded,
        accepted=after['mae_seconds']<=before['mae_seconds']*.9,fit_on_validation=False)
    return result


def calibrated_config(config,path=None,sdk=None,locale=None):
    if not path:
        return config
    model=validate_profile(json.loads(Path(path).read_text()))
    validation=model.get('independent_validation')
    if not validation or validation.get('accepted') is not True or validation.get('fit_on_validation') is not False:
        raise ValueError('timing_profile_not_independently_validated')
    if (sdk,locale)!=(model['sdk_version'],model['locale']):
        return config
    result=dict(config,**model['coefficients'])
    result['_timing_profile']='calibrated'
    return result


def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='command',required=True)
    train=sub.add_parser('train');train.add_argument('--input',type=Path,required=True);train.add_argument('--output',type=Path,required=True)
    check=sub.add_parser('validate');check.add_argument('--model',type=Path,required=True);check.add_argument('--input',type=Path,required=True);check.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    records=[json.loads(line) for line in args.input.read_text().splitlines() if line.strip()]
    if args.command=='train':
        result=profile(records)
    else:
        from .pipeline_settings import load_config
        result=validate(json.loads(args.model.read_text()),records,load_config())
    if args.output.exists():raise ValueError('output_exists')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'coefficients':result['coefficients'],'independent_validation':result['independent_validation']},ensure_ascii=False))


if __name__=='__main__':main()
