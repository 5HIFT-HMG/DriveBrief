import argparse
import json
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from .news_repository import NewsRepository, Category, crawler
from .pipeline_settings import load_config
from .pipeline_models import CandidateResponse
from .selection import metadata, group_events, rank_groups, balanced_select, CATEGORIES


def candidates(repository=None, interests=(), limit=20, as_of=None, config=None, rows=None):
    repo = repository or NewsRepository()
    cfg = config or load_config()
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("timezone_required")
    if rows is None:
        rows = repo.candidate_rows()
    items = metadata(rows)
    # Sorted by valid time, then stable ID. Bounded O(n^2) heuristic.
    from .selection import timestamp
    items.sort(key=lambda r: (-(timestamp(r["published_at"]).timestamp() if timestamp(r["published_at"]) else 0), r["article_id"]))
    total = len(items)
    items = items[:cfg["input_limit"]]
    groups = group_events(items, cfg)
    ranked = rank_groups(groups, list(interests), now, cfg)
    selected = balanced_select(ranked, list(interests), limit, cfg["event"]["balance_penalty"])
    return {"schema_version": "ranked-news-v1", "as_of": now.isoformat(),
            "metadata_only": True, "ai_eligible": False, "grouping_method": "conservative_heuristic_v1",
            "input_count": total, "processed_count": len(items), "input_truncated": total > len(items),
            "group_count": len(groups), "articles": selected}


def candidate_router(repository=None):
    api = APIRouter()
    @api.get("/v1/news/candidates", response_model=CandidateResponse)
    def get_candidates(categories: Optional[List[Category]] = Query(None),
                       limit: int = Query(20, ge=1, le=100), as_of: Optional[datetime] = None):
        if as_of is not None and as_of.tzinfo is None:
            raise HTTPException(422, detail={"code": "timezone_required"})
        try:
            return CandidateResponse.model_validate(candidates(repository, categories or [], limit, as_of))
        except Exception as exc:
            # Never return database paths, article content, or arbitrary exception text.
            import sqlite3
            if isinstance(exc, (sqlite3.Error, OSError, ValueError, TypeError, KeyError)):
                raise HTTPException(503, detail={"code": "candidate_data_unavailable"}) from None
            raise
    return api


def main():
    p = argparse.ArgumentParser(description="Read-only local metadata review report; no collection or AI")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--as-of", required=True)
    args = p.parse_args()
    repo = NewsRepository()
    with closing(crawler.connect_read_only(repo.db_path)) as db:
        rows = metadata(crawler.get_articles(db, all_history=True))
    # Up to five per category, 25 distinct URL samples. Fill only if a category lacks data.
    from .selection import timestamp
    rows.sort(key=lambda r: (-(timestamp(r["published_at"]).timestamp() if timestamp(r["published_at"]) else 0), r["article_id"]))
    sample = []
    for category in CATEGORIES:
        sample.extend([r for r in rows if category in r["categories"] and r not in sample][:5])
    sample.extend([r for r in rows if r not in sample][:25-len(sample)])
    data = candidates(rows=sample[:25], limit=25, as_of=datetime.fromisoformat(args.as_of))
    report = {"review_required": True, "accuracy_not_measured": True, "sample_size": len(sample[:25]),
              "instructions": "각 그룹의 원문 링크와 제목/설명을 확인하고 잘못된 병합·누락을 사람이 표시하세요.",
              "configuration": load_config(), "sample_metadata": sample[:25], "result": data}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps({"sample_count": len(sample[:25]), "group_count": data["group_count"],
                      "path": str(args.output), "review_required": True}))


if __name__ == "__main__":
    main()
