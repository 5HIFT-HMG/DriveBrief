"""Default RSS automatic publication; explicit legacy reviewed/fictional routes remain available.
Dry-run never writes to Supabase. No article generation, approval, body fetch or external LLM.
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone

from .pipeline_settings import load_config
from .pipeline_models import PlannedResponse
from .planning import SAMPLE_CATEGORIES, plan

LENGTHS = ("짧게", "중간", "길게")


def build(document, config):
    if document.get("fictional_only") is not True and document.get("content_kind") != "rss_metadata":
        raise ValueError("real_planning_blocked_by_policy")
    category_map = json.loads(SAMPLE_CATEGORIES.read_text(encoding="utf-8"))
    category_map.update({a["article_id"]: [a["category"]] for a in document["articles"] if a.get("category")})
    now = datetime.now(timezone.utc)
    return {length: PlannedResponse.model_validate(
        plan(document, length, [], config, now, category_map)).model_dump() for length in LENGTHS}


def publish(plans, namespace, remote):
    # Validate every option BEFORE the first write; never erase an older briefing on empty input.
    if namespace not in ("real", "fictional") or set(plans) != set(LENGTHS):
        raise ValueError("published_plan_invalid")
    checked = {length: PlannedResponse.model_validate(plans[length]).model_dump() for length in LENGTHS}
    if any(p["fictional_only"] != (namespace == "fictional") for p in checked.values()):
        raise ValueError("namespace_origin_mismatch")
    if any(not p["articles"] for p in checked.values()):
        raise ValueError("empty_plan_not_published")
    published = {}
    for length, briefing in checked.items():
        revision = hashlib.sha256(json.dumps(briefing, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        remote.request("published_briefings?on_conflict=length_option", "POST",
                       [{"length_option": length, "namespace": namespace, "briefing": briefing, "revision": revision}],
                       prefer="resolution=merge-duplicates,return=minimal")
        published[length] = len(briefing["articles"])
    return published


def main(argv=None):
    from .rss_review import DEFAULT_DB, DEFAULT_POLICY
    parser = argparse.ArgumentParser(description="Publish automatic RSS by default; use --dry-run first")
    parser.add_argument("--namespace", choices=["real", "fictional"], default="real")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reviewed-rss", action="store_true", help="Legacy explicit source-permission and article review path")
    parser.add_argument("--private-rss-preview", action="store_true", help="Unapproved, local debug preview only; requires --dry-run")
    parser.add_argument("--preview-output")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--rss-review-db", default=str(DEFAULT_DB))
    parser.add_argument("--rss-policy", default=str(DEFAULT_POLICY))
    args = parser.parse_args(argv)
    try:
        if args.private_rss_preview:
            if not args.dry_run or args.namespace != "real":
                raise ValueError("private_preview_requires_dry_run")
            from .private_preview import read_recent, build_preview, save_preview
            from .shared_backend import SharedDatabase
            rows, count = read_recent(SharedDatabase(), args.limit)
            plans = build_preview(rows, load_config())
            if args.preview_output:
                save_preview(plans, args.preview_output)
            print(json.dumps({"status": "private_preview_dry_run", "publication_allowed": False,
                "read_count": count, "articles": {k: len(v["articles"]) for k, v in plans.items()},
                "estimated_seconds": {k: v["estimated_seconds"] for k, v in plans.items()}}, ensure_ascii=False))
            return 0
        if args.preview_output:
            raise ValueError("private_preview_requires_dry_run")
        if args.namespace == "real" and not args.reviewed_rss:
            from .rss_auto import refresh
            from .shared_backend import SharedDatabase
            try:
                outcome = refresh(SharedDatabase(), args.dry_run)
            except Exception:
                raise ValueError("rss_auto_refresh_failed") from None
            print(json.dumps(outcome, ensure_ascii=False))
            return 0
        if args.namespace == "real":
            from .rss_review import RssReviewStore
            store = RssReviewStore(args.rss_review_db, args.rss_policy)
        else:
            from .shared_backend import SharedDatabase, SharedReviewStore
            store = SharedReviewStore(SharedDatabase(), "fictional")
        plans = build(store.briefing(limit=None), load_config())
        counts = {k: len(v["articles"]) for k, v in plans.items()}
        if args.dry_run:
            print(json.dumps({"status": "dry_run", "ready_to_publish": all(counts.values()),
                              "articles": counts,
                              "estimated_seconds": {k: p["estimated_seconds"] for k, p in plans.items()}},
                             ensure_ascii=False))
            return 0
        from .shared_backend import SharedDatabase
        print(json.dumps({"status": "published", "namespace": args.namespace,
                          "articles": publish(plans, args.namespace, SharedDatabase())}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error) as error:
        safe = {"rss_auto_refresh_failed", "private_preview_requires_dry_run", "preview_output_must_be_local_results", "rss_policy_missing", "rss_permission_unverified", "rss_permission_changed",
                "rss_policy_invalid", "rss_policy_duplicate", "real_planning_blocked_by_policy",
                "empty_plan_not_published", "namespace_origin_mismatch"}
        reason = str(error) if str(error) in safe else "publish_input_unavailable"
        print(json.dumps({"status": "blocked", "reason": reason}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
