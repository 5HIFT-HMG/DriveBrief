"""Read-only adapter reusing the original crawler. No collection, summary provider or DDL."""
from datetime import date as Date, datetime, timezone
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
from typing import Dict, List, Literal, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

PROJECT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("drivebrief_existing_news", PROJECT / "news_crawler/news.py")
crawler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crawler)
Category = Literal["경제", "사회", "정치", "IT", "스포츠"]


class NewsItem(BaseModel):
    article_id: str
    title: str
    category: str
    categories: List[str]
    source: str
    sources: List[str]
    published_at: str
    description: str
    source_url: str
    content_level: Literal["rss_description"] = "rss_description"
    summary_status: Literal["not_available"] = "not_available"
    ai_eligible: Literal[False] = False
    ai_blockers: List[str]


class NewsPage(BaseModel):
    schema_version: Literal["news-candidates-v1"] = "news-candidates-v1"
    total_candidates: int
    available_count: int
    category_counts: Dict[str, int]
    category_limits: Dict[str, int]
    limit: int
    offset: int
    has_more: bool
    event_dedup_status: Literal["not_performed"] = "not_performed"
    articles: List[NewsItem]


class NewsRepository:
    def __init__(self, db_path=None, config_path=None):
        self.db_path = Path(db_path) if db_path else PROJECT / "news_crawler/news.sqlite3"
        self.config_path = Path(config_path) if config_path else PROJECT / "news_crawler/config.json"

    def candidate_rows(self):
        with closing(crawler.connect_read_only(self.db_path)) as db:
            return crawler.get_articles(db, all_history=True)

    def collection_status(self, interval=300):
        result = {'database_available': False, 'article_count': 0, 'latest_article_at': None,
                  'last_attempt_at': None, 'last_success_at': None, 'stale': True,
                  'feed_count': 0, 'failed_feed_count': 0, 'stale_feed_count': 0}
        try:
            config = json.loads(self.config_path.read_text(encoding='utf-8'))
            feeds = config.get('feeds', [])
            with closing(crawler.connect_read_only(self.db_path)) as db:
                count, latest = db.execute('SELECT count(*),max(published_at) FROM articles').fetchone()
                rows = {r['feed_url']: dict(r) for r in db.execute('SELECT * FROM feed_status')}
            selected = [rows.get(feed['url'], {}) for feed in feeds]
            attempts = [r['last_attempt'] for r in selected if r.get('last_attempt')]
            successes = [r['last_success'] for r in selected if r.get('last_success')]
            now = datetime.now(timezone.utc)
            def stale(row):
                stamp = crawler.parse_date(row.get('last_success'))
                return stamp is None or not -300 <= (now - stamp).total_seconds() <= interval * 2
            stale_count = sum(stale(row) for row in selected)
            result.update(database_available=True, article_count=count, latest_article_at=latest,
                          last_attempt_at=max(attempts, default=None), last_success_at=max(successes, default=None),
                          feed_count=len(feeds), failed_feed_count=sum(bool(r.get('error')) for r in selected),
                          stale_feed_count=stale_count, stale=not selected or stale_count > 0)
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError, AttributeError):
            pass
        return result

    def page(self, category=None, day=None, limit=20, offset=0, per_category_limit=None, categories=None):
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
            limits = config.get("candidate_limits", {name: 100 for name in crawler.CATEGORIES})
            with closing(crawler.connect_read_only(self.db_path)) as db:
                data = crawler.candidate_page(db, category=category if category is not None else categories, day=day, limit=limit, offset=offset,
                                               category_limits=limits, per_category_limit=per_category_limit)
            items = []
            for row in data["articles"]:
                items.append(NewsItem(
                    article_id="rss_" + hashlib.sha256(row["url"].encode("utf-8")).hexdigest()[:24],
                    title=row["title"], category=category or row["category"],
                    categories=row["categories"], source=row["source"], sources=row["sources"],
                    published_at=row["published_at"], description=row["description"], source_url=row["url"],
                    ai_blockers=["full_text_missing", "external_ai_permission_unverified", "reuse_permission_unverified"]))
            return NewsPage(**dict(data, articles=items))
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError, AttributeError):
            raise HTTPException(503, detail={"code": "news_data_unavailable"}) from None


def news_router(repository=None):
    api = APIRouter()
    store = repository or NewsRepository()

    @api.get("/v1/news", response_model=NewsPage)
    def news(category: Optional[Category] = None, date: Optional[Date] = None,
             categories: Optional[List[Category]] = Query(None),
             limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
             per_category_limit: Optional[int] = Query(None, ge=0, le=1000)):
        if category is not None and categories is not None:
            raise HTTPException(422, detail={"code": "ambiguous_category_filter"})
        return store.page(category, date, limit, offset, per_category_limit, categories)
    return api
