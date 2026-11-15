"""Frozen-model evaluation on genuinely unseen sentence hashes, no fitting or external calls."""
import argparse
import json
import statistics
from pathlib import Path
from .pipeline_settings import load_config
from .timing_quality import measured, errors, unique_sentences, FEATURES, correlation
from .quality import write_json


def compare(training, testing, baseline, candidate):
    train, _ = measured(training)
    test, excluded = measured(testing)
    if not train or not test: raise ValueError("observed_training_and_test_required")
    hashes = {r["text_sha256"] for r in train}
    overlap = hashes & {r["text_sha256"] for r in test}
    if overlap: raise ValueError("test_sentences_overlap_training")
    if {r["attempt_id"] for r in train} & {r["attempt_id"] for r in test}:
        raise ValueError("test_attempts_overlap_training")
    if {r["article_id"] for r in train} & {r["article_id"] for r in test}:
        raise ValueError("test_articles_overlap_training")
    # Different environment must be a separate experiment, not a pooled score.
    environments = {(r["sdk_version"],r["locale"]) for r in train+test}
    if len(environments)!=1: raise ValueError("training_test_environment_changed")
    rows = unique_sentences(test)
    startup = [r["startup_ms"] for r in test]
    speech = [r["start_to_done_ms"]/1000 for r in test]
    total = [r["request_to_done_ms"]/1000 for r in test]
    feature_ranges = {f:dict(train_min=min(r["features"][f] for r in train),
                            train_max=max(r["features"][f] for r in train),
                            test_min=min(r["features"][f] for r in test),
                            test_max=max(r["features"][f] for r in test),
                            correlation_with_speech_seconds=correlation([r["features"][f] for r in test],speech))
                      for f in FEATURES}
    articles = {}
    for aid in sorted({r["article_id"] for r in test}):
        subset = unique_sentences([r for r in test if r["article_id"]==aid])
        articles[aid]={"baseline":errors(subset,baseline),"candidate":errors(subset,candidate)}
    sessions=[]
    for sid in sorted({r["session_id"] for r in test}):
        batch=sorted([r for r in test if r["session_id"]==sid],key=lambda r:r["requested_monotonic_ms"])
        expected={r["session_sentence_count"] for r in batch}
        complete=(len(expected)==1 and len(batch)==next(iter(expected)) and
                  len({(r["article_id"],r["sentence_index"]) for r in batch})==len(batch))
        if not complete:
            sessions.append({"session_id":sid,"status":"incomplete_excluded"});continue
        elapsed=(batch[-1]["requested_monotonic_ms"]+batch[-1]["request_to_done_ms"]-batch[0]["requested_monotonic_ms"])/1000
        summed=sum(r["request_to_done_ms"] for r in batch)/1000
        gaps=[(b["requested_monotonic_ms"]-a["requested_monotonic_ms"]-a["request_to_done_ms"])/1000 for a,b in zip(batch,batch[1:])]
        if any(g < -.005 or g > 5 for g in gaps):
            sessions.append({"session_id":sid,"status":"pause_or_clock_discontinuity_excluded"});continue
        def estimate(cfg):return sum(r["features"]["characters"]/cfg["characters_per_second"]+cfg["sentence_pause_seconds"] for r in batch)
        sessions.append(dict(session_id=sid,status="observed_full_session",sentences=len(batch),
                             observed_seconds=elapsed,sum_request_seconds=summed,gap_seconds=elapsed-summed,
                             baseline_seconds=estimate(baseline),candidate_seconds=estimate(candidate)))
    return {"unseen_sentences":len(rows),"test_attempts":len(test),"excluded":excluded,
            "training_attempts":len(train),"overlapping_hashes":0,"fit_on_test":False,
            "baseline":errors(rows,baseline),"candidate":errors(rows,candidate),
            "startup_ms":dict(min=min(startup),median=statistics.median(startup),max=max(startup)),
            "mean_speech_seconds":statistics.mean(speech),"mean_request_seconds":statistics.mean(total),
            "feature_ranges":feature_ranges,"feature_correlations_not_causal":True,
            "article_results":articles,"sessions":sessions,
            "candidate_not_promoted_to_default":True,"real_audio_listening_not_verified":True}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--training",type=Path,required=True);p.add_argument("--test",type=Path,required=True)
    p.add_argument("--candidate-config",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    def read(path):return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    report=compare(read(args.training),read(args.test),load_config(),load_config(args.candidate_config))
    write_json(args.output,report)
    print(json.dumps({k:report[k] for k in ("unseen_sentences","baseline","candidate","startup_ms","sessions")}))


if __name__=="__main__":
    main()
