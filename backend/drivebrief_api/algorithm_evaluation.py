"""Reproducible offline experiment CLI; no network, model inference or DB writes."""
import argparse
import csv
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path

from .quality import (fingerprint, assignments, evaluate, ranking_report, write_json)
from .pipeline_settings import load_config
from .selection import group_events, related, timestamp
from .algorithm_v2 import normalized_candidate, candidate_ranks, budget_candidate


def pair_dossier(bundle, labels):
    baseline = evaluate(bundle, labels)
    rows = {r["pair_id"]: r for r in labels}
    baseline_mapping = assignments(bundle["items"], bundle["configuration"])
    candidate = {m["article_id"]: g["group_id"] for g in normalized_candidate(bundle["items"], bundle["configuration"])
                 for m in g["members"]}
    items = {r["article_id"]: r for r in bundle["items"]}
    comparisons = []
    counts = dict(tp=0, fp=0, fn=0, tn=0)
    for pair in bundle["pairs"]:
        a, b = items[pair["left_id"]], items[pair["right_id"]]
        row = rows.get(pair["pair_id"], {})
        truth = row.get("human_label", "").strip()
        pred = candidate[pair["left_id"]] == candidate[pair["right_id"]]
        if truth in ("same_event", "different_event"):
            counts[("tp" if pred else "fn") if truth == "same_event" else ("fp" if pred else "tn")] += 1
        da, db = timestamp(a["published_at"]), timestamp(b["published_at"])
        comparisons.append(dict(pair_id=pair["pair_id"], stratum=pair["stratum"],
            left=a, right=b, baseline_same=baseline_mapping[pair["left_id"]] == baseline_mapping[pair["right_id"]], candidate_same=pred,
            baseline_pair_match=related(a, b, bundle["configuration"]),
            hours_apart=abs((da-db).total_seconds())/3600 if da and db else None,
            human_label=truth, reviewer=row.get("reviewer", ""),
            analysis_status="human_error_type_pending" if not truth else "human_label_available"))
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    return {"schema": "pair-dossier-v2", "source_hash": bundle["source_hash"],
            "human_labels": baseline["labeled"], "baseline": baseline["models"]["baseline"],
            "candidate": dict(counts, precision=tp/(tp+fp) if tp+fp else None,
                              recall=tp/(tp+fn) if tp+fn else None,
                              f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None),
            "candidate_default_enabled": False, "sample_only": True, "pairs": comparisons}


def ranking_identity(review, as_of, interests, k):
    return fingerprint(dict(review_pool=review, as_of=as_of, interests=sorted(interests), k=k))


def ranking_bundle(items, config, as_of, interests, k=20):
    report = ranking_report(items, config, as_of, interests, limit=k)
    candidate, candidate_cfg = candidate_ranks(items, config, as_of, interests, k)
    models = {"baseline": report["baseline"]["top"], "candidate": candidate}
    pool = {r["group_id"]: r for rows in models.values() for r in rows}
    review = [{"group_id": gid, "title": r["title"], "source": r["source"],
               "published_at": r["published_at"], "categories": r["categories"]}
              for gid, r in sorted(pool.items())]
    def stats(rows):
        ages = sorted((as_of-timestamp(r["published_at"])).total_seconds()/3600 for r in rows if timestamp(r["published_at"]) and timestamp(r["published_at"]) <= as_of)
        components = {key: sum(r["score_components"][key] for r in rows)/len(rows) if rows else None
                      for key in config["weights"]}
        return {"age_hours": {"min": min(ages) if ages else None, "median": ages[len(ages)//2] if ages else None, "max": max(ages) if ages else None},
                "single_source_groups": sum(len(r["sources"]) == 1 for r in rows),
                "source_counts": dict(Counter(r["source"] for r in rows)),
                "category_counts": dict(Counter(r["selection_reason"]["balance_category"] for r in rows)),
                "interest_match_rate": sum(r["selection_reason"]["interest_match"] for r in rows)/len(rows) if rows and interests else None,
                "fallback_count": sum(r["selection_reason"]["fallback"] for r in rows),
                "mean_score_contributions": components,
                "coverage_diversity_joint_contribution": sum(r["score_components"]["coverage"]+r["score_components"]["diversity"] for r in rows)/len(rows) if rows else None,
                "old_news_count_48h": sum(bool(timestamp(r["published_at"]) and (as_of-timestamp(r["published_at"])).total_seconds()>48*3600) for r in rows)}
    return {"schema": "human-ranking-pool-v1", "source_hash": fingerprint(items), "k": k,
            "as_of": as_of.isoformat(), "interests": interests, "models": models,
            "review_pool": review, "pool_hash": ranking_identity(review, as_of.isoformat(), interests, k),
            "configurations": {"baseline": config, "candidate": candidate_cfg},
            "baseline_data_diagnostics": {k:v for k,v in report["baseline"].items() if k != "top"},
            "diagnostics": {name: stats(rows) for name, rows in models.items()},
            "changed_rank_positions": sum([r["group_id"] for r in models["baseline"]][i:i+1] !=
                                          [r["group_id"] for r in candidate][i:i+1]
                                          for i in range(max(len(candidate),len(models["baseline"])))),
            "human_relevance_not_evaluated": True}


def ranking_metrics(bundle, labels):
    if ranking_identity(bundle["review_pool"], bundle["as_of"], bundle["interests"], bundle["k"]) != bundle["pool_hash"]:
        raise ValueError("review_pool_changed")
    valid_ids = {r["group_id"] for r in bundle["review_pool"]}
    grades = {}
    seen = set()
    for row in labels:
        gid = row["group_id"]
        if gid not in valid_ids or gid in seen or row["pool_hash"] != bundle["pool_hash"]:
            raise ValueError("unknown_duplicate_or_stale_grade")
        seen.add(gid)
        grade = row.get("relevance", "").strip()
        if not grade or grade == "uncertain":
            continue
        if grade not in ("0", "1", "2", "3") or not row.get("reviewer", "").strip():
            raise ValueError("human_grade_and_reviewer_required")
        grades[gid] = int(grade)
    ready = bool(valid_ids) and set(grades) == valid_ids
    result = {"status": "evaluated_judged_pool_only" if ready else "awaiting_complete_pool_labels",
              "judged": len(grades), "pool_size": len(valid_ids), "models": {},
              "not_population_relevance": True}
    if not ready:
        return result
    k = bundle["k"]
    if type(k) is not int or k < 1:
        raise ValueError("invalid_k")
    for rows in bundle["models"].values():
        ids = [r["group_id"] for r in rows]
        if len(ids) != len(set(ids)) or set(ids)-valid_ids:
            raise ValueError("invalid_ranked_ids")
    def dcg(values):
        return sum((2**g-1)/math.log2(i+2) for i,g in enumerate(values[:k]))
    ideal = dcg(sorted(grades.values(), reverse=True))
    for name, rows in bundle["models"].items():
        values = [grades[r["group_id"]] for r in rows[:k]]
        result["models"][name] = {"ndcg_at_k": dcg(values)/ideal if ideal else None,
                                  "precision_at_k": sum(g>=2 for g in values)/k,
                                  "returned": len(values), "k": k,
                                  "no_relevant_items": ideal == 0}
    return result


def safe_cell(value):
    value = str(value)
    return "'"+value if value.startswith(("=", "+", "-", "@")) else value


def rank_csv(path, bundle):
    fields = ["group_id", "pool_hash", "as_of", "interests", "title", "source", "published_at", "relevance", "reviewer", "notes"]
    with path.open("x", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader()
        for row in bundle["review_pool"]:
            record = {k: safe_cell(row.get(k) or "") for k in fields}
            record["pool_hash"] = bundle["pool_hash"]
            record["as_of"] = bundle["as_of"]
            record["interests"] = ";".join(bundle["interests"])
            writer.writerow(record)


def main():
    p = argparse.ArgumentParser(description="Offline candidate experiments; never service policy")
    sub = p.add_subparsers(dest="command", required=True)
    pair = sub.add_parser("pairs")
    pair.add_argument("--bundle", type=Path, required=True)
    pair.add_argument("--labels", type=Path, required=True)
    rank = sub.add_parser("ranking")
    rank.add_argument("--bundle", type=Path, required=True, help="Existing pair snapshot; does not recollect RSS")
    rank.add_argument("--as-of", required=True)
    rank.add_argument("--categories", nargs="*", default=[])
    metric = sub.add_parser("ranking-evaluate")
    metric.add_argument("--bundle", type=Path, required=True)
    metric.add_argument("--labels", type=Path, required=True)
    for command in (pair,rank,metric): command.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    if args.command == "ranking":
        if bundle["source_hash"] != fingerprint(bundle["items"]): raise ValueError("source_changed")
        output = ranking_bundle(bundle["items"], bundle["configuration"], datetime.fromisoformat(args.as_of), args.categories)
        if args.output.with_suffix(".csv").exists() or args.output.with_suffix(".md").exists(): raise ValueError("output_exists")
        write_json(args.output, output)
        rank_csv(args.output.with_suffix(".csv"), output)
        lines = ["# 중요도 검토 보고서 (정답 아님)", "", "관심 분야: " + str(args.categories), ""]
        for name, rows in output["models"].items():
            lines += ["## " + name, "", "| 순위 | 제목 | 출처 | 발행 시각 | 점수 | 기여도 | 선정 이유 |",
                      "|---:|---|---|---|---:|---|---|"]
            for row in rows:
                values = [row["rank"], row["title"], row["source"], row["published_at"],
                          row["importance_score"], row["score_components"], row["selection_reason"]]
                lines.append("| " + " | ".join(str(v).replace("|", "/").replace("\n", " ") for v in values) + " |")
            lines.append("")
        with args.output.with_suffix(".md").open("x", encoding="utf-8") as f: f.write("\n".join(lines))
        print(json.dumps({"review_pool":len(output["review_pool"]), "changed_rank_positions":output["changed_rank_positions"],
                          "diagnostics":output["diagnostics"]}, ensure_ascii=False))
    else:
        with args.labels.open(encoding="utf-8-sig", newline="") as f: labels=list(csv.DictReader(f))
        output = pair_dossier(bundle, labels) if args.command == "pairs" else ranking_metrics(bundle, labels)
        if args.command == "pairs" and args.output.with_suffix(".md").exists(): raise ValueError("output_exists")
        write_json(args.output, output)
        if args.command == "pairs":
            lines = ["# 기사 쌍 검토 (예측 숨김)", "", "원래 CSV에 human_label/reviewer를 작성하세요. 동일 주제와 동일 사건을 구분하고, 불명확하면 uncertain으로 남기세요.", ""]
            for row in sorted(output["pairs"], key=lambda r:r["pair_id"]):
                lines += ["## " + row["pair_id"], ""]
                for side in ("left", "right"):
                    item=row[side]
                    lines += [side + ": " + item["title"], str(item["sources"]) + " · " + str(item["published_at"]),
                              item["description"], item["source_url"], ""]
            with args.output.with_suffix(".md").open("x", encoding="utf-8") as f: f.write("\n".join(lines))
        print(json.dumps({k:v for k,v in output.items() if k in ("human_labels","baseline","candidate","status","judged","pool_size","models")}))
    # Full report remains local; no RSS content printed.


if __name__ == "__main__":
    main()
