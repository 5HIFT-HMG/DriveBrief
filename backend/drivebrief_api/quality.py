"""Offline metadata evaluation. Human labels are never inferred from predictions."""
import argparse
import copy
import csv
import hashlib
import json
from collections import Counter
from contextlib import closing
from datetime import datetime
from itertools import combinations
from pathlib import Path

from .news_repository import NewsRepository, crawler
from .pipeline_settings import load_config
from .selection import (metadata, group_events, rank_groups, balanced_select, grams,
                        similarity, publisher, timestamp, related, normalize, tokens, CATEGORIES)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read_metadata():
    repo = NewsRepository()
    with closing(crawler.connect_read_only(repo.db_path)) as db:
        return metadata(crawler.get_articles(db, all_history=True))


def assignments(items, config):
    return {member["article_id"]: group["group_id"] for group in group_events(items, config)
            for member in group["members"]}


def sample_pairs(items, config, count=60):
    if not 4 <= count <= 500:
        raise ValueError("pair_count")
    items = sorted(items, key=lambda item: item["article_id"])
    groups = assignments(items, config)
    pairs = []
    for a, b in combinations(items, 2):
        aid, bid = a["article_id"], b["article_id"]
        pairs.append(dict(pair_id=fingerprint([aid, bid])[:24], left_id=aid, right_id=bid,
                          predicted_same=groups[aid] == groups[bid],
                          title_similarity=round(similarity(grams(a["title"]), grams(b["title"])), 6)))
    merged = sorted([p for p in pairs if p["predicted_same"]], key=lambda p: p["pair_id"])
    unmerged = sorted([p for p in pairs if not p["predicted_same"]],
                      key=lambda p: (-p["title_similarity"], p["pair_id"]))
    selected = [dict(p, stratum="merged") for p in merged[:max(1, count//3)]]
    similar_count = max(1, int(count*.65))
    selected += [dict(p, stratum="similar_unmerged") for p in unmerged[:similar_count]]
    used = {p["pair_id"] for p in selected}
    controls = sorted([p for p in unmerged if p["pair_id"] not in used], key=lambda p: p["pair_id"])
    selected += [dict(p, stratum="control_unmerged") for p in controls[:max(0, count-len(selected))]]
    selected = selected[:count]
    return {"schema": "human-pair-review-v1", "source_hash": fingerprint(items),
            "configuration": config, "items": items, "pairs": selected,
            "sampling": {"total_pairs": len(pairs), "predicted_merged_pairs": len(merged),
                         "selected_pairs": len(selected),
                         "strata": dict(Counter(p["stratum"] for p in selected)),
                         "biased_sample_not_population_estimate": True, "csv_blinded": True}}


def evaluate(bundle, labels, candidate_config=None):
    if bundle["source_hash"] != fingerprint(bundle["items"]):
        raise ValueError("source_changed")
    pairs = {p["pair_id"]: p for p in bundle["pairs"]}
    seen, labeled, excluded = set(), [], 0
    for row in labels:
        pid = row["pair_id"]
        if pid not in pairs or pid in seen or row["source_hash"] != bundle["source_hash"]:
            raise ValueError("unknown_duplicate_or_stale_label")
        seen.add(pid)
        label = row.get("human_label", "").strip()
        if label not in ("", "same_event", "different_event", "uncertain"):
            raise ValueError("invalid_human_label")
        if not label or label == "uncertain":
            excluded += 1
            continue
        if not row.get("reviewer", "").strip():
            raise ValueError("human_reviewer_required")
        labeled.append((pairs[pid], label == "same_event"))
    models = {"baseline": bundle["configuration"]}
    if candidate_config is not None:
        models["candidate"] = candidate_config
    result = {"status": "evaluated_sample_only" if labeled else "awaiting_human_labels",
              "labeled": len(labeled), "unlabeled_or_uncertain": len(pairs)-len(labeled),
              "population_recall_not_measured": True, "models": {}}
    for name, config in models.items():
        mapping = assignments(bundle["items"], config)
        tp = fp = fn = tn = 0
        mistakes = []
        for pair, truth in labeled:
            pred = mapping[pair["left_id"]] == mapping[pair["right_id"]]
            if pred and truth: tp += 1
            elif pred: fp += 1
            elif truth: fn += 1
            else: tn += 1
            if pred != truth:
                mistakes.append({"pair_id": pair["pair_id"], "kind": "false_merge" if pred else "missed_duplicate"})
        precision = tp/(tp+fp) if tp+fp else None
        recall = tp/(tp+fn) if tp+fn else None
        f1 = 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None
        result["models"][name] = dict(tp=tp, fp=fp, fn=fn, tn=tn, precision=precision,
                                     recall=recall, f1=f1, mistakes=mistakes)
    return result


def ranking_report(items, config, as_of, interests, limit=20, candidate_config=None):
    if as_of.tzinfo is None:
        raise ValueError("timezone_required")
    def run(cfg):
        ranked = rank_groups(group_events(items, cfg), interests, as_of, cfg)
        top = balanced_select(ranked, interests, limit, cfg["event"]["balance_penalty"])
        pubs = Counter(publisher(r["source"], cfg) for r in top)
        cats = Counter(r["selection_reason"]["balance_category"] or "unknown" for r in top)
        ages = [(as_of-timestamp(r["published_at"])).total_seconds()/3600
                for r in top if timestamp(r["published_at"]) and timestamp(r["published_at"]) <= as_of]
        return {"top": top, "groups_available": len(ranked), "shortage": len(top) < limit,
                "fresh_groups_within_48h": sum(bool(timestamp(r["published_at"]) and 0 <= (as_of-timestamp(r["published_at"])).total_seconds() <= 48*3600) for r in ranked),
                "representative_publisher_counts": dict(pubs), "assigned_category_counts": dict(cats),
                "largest_publisher_share": max(pubs.values(), default=0)/len(top) if top else None,
                "pool_representative_publisher_counts": dict(Counter(publisher(r["source"], cfg) for r in ranked)),
                "older_than_48h": sum(age > 48 for age in ages),
                "missing_or_future_dates": len(top)-len(ages),
                "oldest_top_age_hours": max(ages) if ages else None,
                "available_by_category": {c: sum(c in r["categories"] for r in ranked) for c in CATEGORIES}}
    baseline = run(config)
    variant = run(candidate_config) if candidate_config else None
    before = {r["group_id"]: r for r in baseline["top"]}
    after = {r["group_id"]: r for r in (variant or baseline)["top"]}
    comparisons = []
    for gid in sorted(set(before) | set(after)):
        a, b = before.get(gid), after.get(gid)
        comparisons.append({"group_id": gid, "title": (b or a)["title"],
                            "rank_before": a["rank"] if a else None,
                            "rank_after": b["rank"] if b else None,
                            "contributions_before": a["score_components"] if a else None,
                            "contributions_after": b["score_components"] if b else None})
    return {"schema": "ranking-review-v1", "as_of": as_of.isoformat(), "source_hash": fingerprint(items),
            "weights_baseline": config["weights"], "weights_candidate": candidate_config["weights"] if candidate_config else None,
            "human_preference_not_evaluated": True, "baseline": baseline, "candidate": variant,
            "rank_comparison": comparisons}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


def main():
    p = argparse.ArgumentParser(description="Offline human evaluation and ranking diagnostics; no AI")
    sub = p.add_subparsers(dest="command", required=True)
    sample = sub.add_parser("pairs")
    sample.add_argument("--output", type=Path, required=True)
    sample.add_argument("--count", type=int, default=60)
    score = sub.add_parser("evaluate")
    score.add_argument("--bundle", type=Path, required=True)
    score.add_argument("--labels", type=Path, required=True)
    score.add_argument("--candidate-config", type=Path)
    score.add_argument("--output", type=Path, required=True)
    ranks = sub.add_parser("ranking")
    ranks.add_argument("--as-of", required=True)
    ranks.add_argument("--categories", nargs="*", default=[])
    ranks.add_argument("--candidate-config", type=Path)
    ranks.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.command == "pairs":
        bundle = sample_pairs(read_metadata(), load_config(), args.count)
        csv_path = args.output.with_suffix(".csv")
        if csv_path.exists() or args.output.exists():
            raise ValueError("output_exists")
        write_json(args.output, bundle)
        with csv_path.open("x", encoding="utf-8-sig", newline="") as f:
            fields = ["pair_id", "left_id", "right_id", "source_hash",
                      "left_title", "right_title", "left_description", "right_description",
                      "left_url", "right_url", "left_sources", "right_sources", "left_published_at", "right_published_at",
                      "human_label", "reviewer", "notes"]
            writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader()
            by_id = {r["article_id"]: r for r in bundle["items"]}
            for pair in sorted(bundle["pairs"], key=lambda p: p["pair_id"]):
                a, b = by_id[pair["left_id"]], by_id[pair["right_id"]]
                row = {k: pair[k] for k in ("pair_id", "left_id", "right_id")}
                row.update(source_hash=bundle["source_hash"],
                           left_title=a["title"], right_title=b["title"],
                           left_description=a["description"], right_description=b["description"],
                           left_url=a["source_url"], right_url=b["source_url"],
                           left_sources="; ".join(a["sources"]), right_sources="; ".join(b["sources"]),
                           left_published_at=a["published_at"] or "", right_published_at=b["published_at"] or "",
                           human_label="", reviewer="", notes="")
                # CSV opened in spreadsheets must not execute an RSS string as a formula.
                for k, value in row.items():
                    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
                        row[k] = "'" + value
                writer.writerow(row)
        print(json.dumps({"status": "awaiting_human_labels", **bundle["sampling"]}))
    elif args.command == "evaluate":
        bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
        with args.labels.open(encoding="utf-8-sig", newline="") as f:
            labels = list(csv.DictReader(f))
        result = evaluate(bundle, labels, load_config(args.candidate_config) if args.candidate_config else None)
        write_json(args.output, result)
        print(json.dumps({"status": result["status"], "labeled": result["labeled"]}))
    else:
        result = ranking_report(read_metadata(), load_config(), datetime.fromisoformat(args.as_of),
                                args.categories, candidate_config=load_config(args.candidate_config) if args.candidate_config else None)
        md = args.output.with_suffix(".md")
        if md.exists() or args.output.exists(): raise ValueError("output_exists")
        write_json(args.output, result)
        def clean(s): return str(s).replace("|", "/").replace("\n", " ")
        lines = ["# 뉴스 순위 비교 (사람 선호 평가 전)", "",
                 "| 제목 | 이전 순위 | 실험 순위 | 최신성 전→후 | 보도량 전→후 | 다양성 전→후 | 관심 전→후 | 품질 전→후 |",
                 "|---|---:|---:|---|---|---|---|---|"]
        for row in result["rank_comparison"]:
            cells = [clean(row[k]) for k in ("title", "rank_before", "rank_after")]
            for metric in ("recency", "coverage", "diversity", "interest", "quality"):
                before, after = row["contributions_before"], row["contributions_after"]
                cells.append((f"{before[metric]:.4f}" if before else "-") + " → " + (f"{after[metric]:.4f}" if after else "-"))
            lines.append("| " + " | ".join(cells) + " |")
        with md.open("x", encoding="utf-8") as f: f.write("\n".join(lines)+"\n")
        print(json.dumps({"status": "diagnostic_only", "top_count": len(result["baseline"]["top"]),
                          "stale_top_count": result["baseline"]["older_than_48h"]}))


if __name__ == "__main__":
    main()
