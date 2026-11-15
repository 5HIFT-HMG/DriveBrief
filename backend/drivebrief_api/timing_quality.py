"""Observed Pleos timing diagnostics and experimental two-parameter calibration."""
import argparse
import copy
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from .pipeline_settings import load_config

FEATURES = ("characters", "hangul", "spaces", "digits", "punctuation", "latin", "other")


def measured(records):
    valid, seen = [], {}
    excluded = defaultdict(int)
    for record in records:
        aid = record["attempt_id"]
        if aid in seen:
            if seen[aid] != record: raise ValueError("conflicting_attempt_id")
            continue
        seen[aid] = record
        if record.get("schema") != "speech-timing-v1" or record.get("engine") != "pleos-on-device" or record.get("locale") != "ko-KR":
            excluded["not_observed_pleos"] += 1; continue
        if record.get("outcome") != "completed":
            excluded["not_completed"] += 1; continue
        f = record["features"]
        if any(type(f[k]) is not int or f[k] < 0 for k in FEATURES):
            raise ValueError("invalid_features")
        if f["characters"] <= 0 or sum(f[k] for k in FEATURES if k != "characters") != f["characters"]:
            raise ValueError("inconsistent_features")
        durations = [record.get(k) for k in ("startup_ms", "start_to_done_ms", "request_to_done_ms")]
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in durations):
            raise ValueError("invalid_duration")
        if durations[1] <= 0 or abs(durations[0]+durations[1]-durations[2]) > 5:
            raise ValueError("inconsistent_duration")
        digest = record["text_sha256"]
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid_sentence_hash")
        valid.append(record)
    environments = {(r.get("sdk_version"), r.get("locale")) for r in valid}
    if len(environments) > 1 or any(not sdk for sdk, _ in environments):
        raise ValueError("mixed_or_unknown_sdk_locale")
    return valid, dict(excluded)


def unique_sentences(records):
    groups = defaultdict(list)
    for r in records: groups[r["text_sha256"]].append(r)
    output = []
    for digest, rows in sorted(groups.items()):
        if any(r["features"] != rows[0]["features"] for r in rows):
            raise ValueError("feature_hash_mismatch")
        output.append({"hash": digest, "features": rows[0]["features"],
                       "seconds": statistics.median(r["request_to_done_ms"]/1000 for r in rows)})
    return output


def fit(rows):
    if len(rows) < 3: return None
    xs = [r["features"]["characters"] for r in rows]; ys = [r["seconds"] for r in rows]
    xbar, ybar = statistics.mean(xs), statistics.mean(ys)
    variance = sum((x-xbar)**2 for x in xs)
    if variance <= 0: return None
    slope = sum((x-xbar)*(y-ybar) for x, y in zip(xs, ys))/variance
    intercept = ybar-slope*xbar
    # Nonnegative least squares for intercept + character slope, no extra dependencies.
    choices = [(max(0, slope), max(0, intercept)),
               (max(0, sum(x*y for x, y in zip(xs, ys))/sum(x*x for x in xs)), 0),
               (0, ybar)]
    slope, intercept = min(choices, key=lambda p: sum((p[0]*x+p[1]-y)**2 for x, y in zip(xs, ys)))
    if not 1/30 <= slope <= 2 or not 0 <= intercept <= 5: return None
    return {"characters_per_second": 1/slope, "sentence_pause_seconds": intercept}


def predicted(features, cfg):
    return features["characters"]/cfg["characters_per_second"] + cfg["sentence_pause_seconds"]


def errors(rows, cfg):
    if not rows: return None
    residuals = [predicted(r["features"], cfg)-r["seconds"] for r in rows]
    return {"n_unique_sentences": len(rows), "mae_seconds": statistics.mean(abs(e) for e in residuals),
            "mean_signed_error_seconds": statistics.mean(residuals),
            "rmse_seconds": math.sqrt(statistics.mean(e*e for e in residuals))}


def correlation(xs, ys):
    if len(xs) < 3: return None
    xbar, ybar = statistics.mean(xs), statistics.mean(ys)
    denominator = math.sqrt(sum((x-xbar)**2 for x in xs)*sum((y-ybar)**2 for y in ys))
    return sum((x-xbar)*(y-ybar) for x, y in zip(xs, ys))/denominator if denominator else None


def analyze(records, config, calibrate=True):
    observations, excluded = measured(records)
    unique = unique_sentences(observations)
    model = fit(unique) if calibrate and len({r["article_id"] for r in observations}) >= 2 and len(unique) >= 4 else None
    candidate = dict(config, **model) if model else None
    folds = []
    for article in (sorted({r["article_id"] for r in observations}) if calibrate else []):
        test = [r for r in observations if r["article_id"] == article]
        hashes = {r["text_sha256"] for r in test}
        train = [r for r in observations if r["article_id"] != article and r["text_sha256"] not in hashes]
        fold_model = fit(unique_sentences(train))
        folds.append({"article_id": article, "train_unique": len(unique_sentences(train)),
                      "test_unique": len(hashes), "baseline": errors(unique_sentences(test), config),
                      "candidate": errors(unique_sentences(test), dict(config, **fold_model)) if fold_model else None})
    baseline_residuals = [predicted(r["features"], config)-r["seconds"] for r in unique]
    feature_analysis = {key: {"min": min((r["features"][key] for r in unique), default=None),
                             "max": max((r["features"][key] for r in unique), default=None),
                             "baseline_residual_correlation": correlation([r["features"][key] for r in unique], baseline_residuals)}
                        for key in FEATURES}
    sessions = defaultdict(list)
    for r in records:
        if r.get("engine") == "pleos-on-device":
            sessions[r["session_id"]].append(r)
    option_runs = []
    for sid, rows in sessions.items():
        done = [r for r in observations if r["session_id"] == sid]
        expected = {r["session_sentence_count"] for r in rows}
        keys = {(r["article_id"], r["sentence_index"]) for r in done}
        complete = (len(expected) == 1 and len(keys) == next(iter(expected)) and
                    len(done) == len(keys) and all(r.get("outcome") == "completed" for r in rows))
        ordered = sorted(done, key=lambda r: r["requested_monotonic_ms"])
        if any(b["requested_monotonic_ms"] < a["requested_monotonic_ms"]+a["request_to_done_ms"]-5 or
               b["requested_monotonic_ms"]-(a["requested_monotonic_ms"]+a["request_to_done_ms"]) > 5000
               for a, b in zip(ordered, ordered[1:])):
            complete = False  # Unknown pause, overlapping clocks, or cross-process/boot discontinuity.
        if not complete:
            option_runs.append({"session_id": sid, "status": "incomplete_or_interrupted_excluded"}); continue
        start = min(r["requested_monotonic_ms"] for r in done)
        finish = max(r["requested_monotonic_ms"]+r["request_to_done_ms"] for r in done)
        actual = (finish-start)/1000
        estimate = sum(predicted(r["features"], config) for r in done)
        option_runs.append({"session_id": sid, "status": "observed_full_session",
                           "option": done[0]["length_option"], "sentences": len(done),
                           "target_seconds_development_only": config["length_seconds"].get(done[0]["length_option"]),
                           "observed_elapsed_seconds": actual, "baseline_seconds": estimate,
                           "baseline_error_seconds": estimate-actual,
                           "candidate_same_sentences_seconds": sum(predicted(r["features"], candidate) for r in done) if candidate else None,
                           "candidate_is_in_sample_projection_not_new_playback": candidate is not None})
    per_sentence = [{"article_id": r["article_id"], "sentence_index": r["sentence_index"],
                     "text_sha256": r["text_sha256"], "features": r["features"],
                     "startup_ms": r["startup_ms"], "speech_ms": r["start_to_done_ms"],
                     "observed_seconds": r["request_to_done_ms"]/1000,
                     "baseline_seconds": predicted(r["features"], config)} for r in observations]
    def attempt_errors(cfg):
        if not observations or cfg is None: return None
        residuals = [predicted(r["features"], cfg)-r["request_to_done_ms"]/1000 for r in observations]
        return {"n_attempts": len(observations), "mae_seconds": statistics.mean(abs(v) for v in residuals),
                "mean_signed_error_seconds": statistics.mean(residuals)}
    startup = [r["startup_ms"] for r in observations]
    return {"attempt_level_baseline": attempt_errors(config), "attempt_level_candidate_in_sample": attempt_errors(candidate),
            "startup_ms": {"min": min(startup) if startup else None, "max": max(startup) if startup else None,
                           "median": statistics.median(startup) if startup else None},
            "evaluation_scope": "fit_and_article_holdout" if calibrate else "fixed_coefficients_no_fit",
            "schema": "tts-quality-v1", "status": "observed" if observations else "no_observed_data",
            "observations": len(observations), "unique_sentences": len(unique), "excluded": excluded,
            "baseline": errors(unique, config), "candidate_training_fit": errors(unique, candidate) if candidate else None,
            "leave_one_article_out": folds, "candidate_coefficients": model,
            "candidate_requires_independent_validation": True,
            "feature_analysis": feature_analysis, "feature_correlations_not_causal": True,
            "multi_feature_coefficients_not_identifiable_with_small_sample": True,
            "sentence_measurements": per_sentence, "option_runs": option_runs}, candidate


def main():
    p = argparse.ArgumentParser(description="Local observed TTS analysis; no text or API calls")
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--candidate-config", type=Path)
    p.add_argument("--config", type=Path)
    p.add_argument("--training-input", type=Path)
    p.add_argument("--no-fit", action="store_true")
    args = p.parse_args()
    records = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    held_out = None
    if args.training_input:
        if not args.no_fit: raise ValueError("attempt_holdout_requires_no_fit")
        training = [json.loads(line) for line in args.training_input.read_text(encoding="utf-8").splitlines() if line.strip()]
        training_ids = {r["attempt_id"] for r in training}
        before = len(records)
        records = [r for r in records if r["attempt_id"] not in training_ids]
        hashes = {r["text_sha256"] for r in training}
        held_out = {"excluded_training_attempts": before-len(records),
                    "new_attempts": len(records), "overlapping_sentence_hashes": len({r["text_sha256"] for r in records} & hashes),
                    "same_text_repeat_validation_not_unseen_text": True}
    configuration = load_config(args.config)
    report, candidate = analyze(records, configuration, calibrate=not args.no_fit)
    report["evaluation_coefficients"] = {k: configuration[k] for k in ("characters_per_second", "sentence_pause_seconds")}
    report["attempt_holdout"] = held_out
    if args.output.exists() or (args.candidate_config and args.candidate_config.exists()):
        raise ValueError("output_exists")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as f: json.dump(report, f, ensure_ascii=False, indent=2)
    if args.candidate_config and candidate:
        args.candidate_config.parent.mkdir(parents=True, exist_ok=True)
        with args.candidate_config.open("x", encoding="utf-8") as f: json.dump(candidate, f, ensure_ascii=False, indent=2)
    print(json.dumps({"status": report["status"], "observations": report["observations"],
                      "unique_sentences": report["unique_sentences"], "baseline": report["baseline"],
                      "candidate_coefficients": report["candidate_coefficients"]}))


if __name__ == "__main__":
    main()
