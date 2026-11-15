"""Read-only, metadata-only reproducible local audit. No collection or provider calls."""
from contextlib import closing
from datetime import date
import hashlib
import json
from pathlib import Path
import statistics
import time
from .news_repository import PROJECT, NewsRepository, crawler

if __name__ == "__main__":
    path = PROJECT / "news_crawler/news.sqlite3"
    selected = json.loads((PROJECT / "news_crawler/내_뉴스.json").read_text(encoding="utf-8"))
    with closing(crawler.connect_read_only(path)) as db:
        count = db.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        all_rows = crawler.get_candidates(db)
        selected_day = crawler.get_candidates(db, date.fromisoformat(selected["date"]))
        durations = []
        for _ in range(10):
            start = time.perf_counter()
            crawler.get_candidates(db)
            durations.append((time.perf_counter() - start) * 1000)
        result = {
            "raw_articles": count, "dedup_candidates": len(all_rows),
            "category_counts": {name: sum(name in r["categories"] for r in all_rows) for name in crawler.CATEGORIES},
            "selected_json_date": selected["date"],
            "selected_json_counts": {k: len(v) for k, v in selected["categories"].items()},
            "same_day_dedup_candidates": len(selected_day),
            "same_day_category_counts": {name: sum(name in r["categories"] for r in selected_day) for name in crawler.CATEGORIES},
            "candidate_query_median_ms_10_runs": round(statistics.median(durations), 3),
            "db_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    page = NewsRepository().page(category="IT", limit=20)
    result["api_it_returned"] = len(page.articles)
    result["api_it_total"] = page.total_candidates
    print(json.dumps(result, ensure_ascii=False, indent=2))
