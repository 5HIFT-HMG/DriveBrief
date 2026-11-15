import json
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from drivebrief_summary.models import Article, EvidenceLink, Summary
from drivebrief_summary.errors import SummaryError
from drivebrief_summary.validation import resolve_draft

from .news_repository import news_router, NewsRepository

ROOT = Path(__file__).resolve().parents[1]


class ApprovedValidation(BaseModel):
    status: Literal["approved"]
    approved: Literal[True]
    review_required: Literal[False]


class ApprovedArticle(BaseModel):
    article_id: str
    title: str
    source: str
    published_at: str
    source_url: Optional[str]
    tts_sentences: List[str]
    one_line: str
    detail: str
    mock: bool
    validation: ApprovedValidation


class ApprovedBriefing(BaseModel):
    schema_version: Literal["approved-briefing-v1"]
    fictional_only: Literal[True]
    playback_requires_user_action: Literal[True]
    articles: List[ApprovedArticle]


class SavedValidation(BaseModel):
    model_config = ConfigDict(strict=True)
    status: Literal["needs_review"]
    approved: Literal[False]
    review_required: Literal[True]


class SavedProvenance(BaseModel):
    model_config = ConfigDict(strict=True)
    provider: Literal["groq"]
    mock: Literal[False]
    approved: Literal[False]
    review_required: Literal[True]


class SavedArticle(BaseModel):
    model_config = ConfigDict(strict=True)
    article_id: str
    result: Summary
    validation: SavedValidation
    evidence_links: List[EvidenceLink]
    provenance: SavedProvenance


class SavedDocument(BaseModel):
    model_config = ConfigDict(strict=True)
    mode: Literal["groq"]
    articles: List[SavedArticle] = Field(max_length=10)


class ApiValidation(BaseModel):
    status: Literal["needs_review"]
    approved: Literal[False] = False
    review_required: Literal[True] = True


class DemoArticle(BaseModel):
    article_id: str
    title: str
    tts_sentences: List[str]
    one_line: str
    detail: str
    source: str
    validation: ApiValidation


class DemoBriefing(BaseModel):
    schema_version: Literal["demo-briefing-v1"] = "demo-briefing-v1"
    demo_only: Literal[True] = True
    fictional_only: Literal[True] = True
    playback_requires_user_action: Literal[True] = True
    articles: List[DemoArticle]


def read_json(path: Path):
    try:
        with path.open("rb") as handle:
            raw = handle.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("size")
        return json.loads(raw)
    except FileNotFoundError:
        raise HTTPException(503, detail={"code": "demo_data_missing"}) from None
    except (OSError, ValueError):
        raise HTTPException(500, detail={"code": "demo_data_invalid"}) from None


def create_app(result_path=None, articles_path=None, demo_enabled=False, news_repository=None, review_store=None, session_store=None, briefing_catalog=None, collect_news=False, news_interval=300) -> FastAPI:
    from .news_collector import NewsCollector
    from .shared_backend import enabled, SharedNewsRepository, SharedReviewStore
    repository = news_repository or (SharedNewsRepository() if enabled() else NewsRepository())
    collector = NewsCollector(repository, news_interval)

    @asynccontextmanager
    async def lifespan(api):
        if collect_news:
            collector.start()
        try:
            yield
        finally:
            collector.stop()

    api = FastAPI(title="DriveBrief local API", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    api.state.news_collector = collector
    saved_path = Path(result_path) if result_path else ROOT / "results/groq-source-ids-v3-once.json"
    source_path = Path(articles_path) if articles_path else ROOT / "samples/articles.json"

    @api.get("/healthz")
    def healthz():
        return {"status": "ok", "demo_enabled": demo_enabled}

    @api.get('/v1/news/status')
    def news_status():
        return dict(repository.collection_status(news_interval), collection_enabled=collect_news,
                    collector_running=collector.running, interval_seconds=news_interval,
                    collector_error=collector.last_error, review_sync=getattr(collector, "review_sync", {}))

    @api.get("/v1/demo/briefing", response_model=DemoBriefing)
    def briefing(allow_unreviewed_fictional: bool = Query(False)):
        if not demo_enabled or not allow_unreviewed_fictional:
            raise HTTPException(403, detail={"code": "demo_opt_in_required"})
        document = read_json(saved_path)
        originals = read_json(source_path)
        try:
            saved = SavedDocument.model_validate(document)
            if not isinstance(originals, list):
                raise ValueError("source shape")
            sources = [Article.model_validate(item) for item in originals]
            if len({source.id for source in sources}) != len(sources):
                raise ValueError("duplicate source")
            by_id = {source.id: source for source in sources}
            if len({item.article_id for item in saved.articles}) != len(saved.articles):
                raise ValueError("duplicate result")
            output = []
            for item in saved.articles:
                article = by_id[item.article_id]
                if (article.rights.kind != "fictional" or not article.rights.external_llm_allowed
                        or not article.rights.summary_reuse_allowed or not article.rights.basis.strip()):
                    raise ValueError("fictional permission")
                # Re-resolve existing links, never regenerate/retrieve a summary from a provider.
                draft = item.result.model_dump(exclude={"evidence_snippets"})
                draft["evidence_links"] = [link.model_dump() for link in item.evidence_links]
                resolved, validation, _ = resolve_draft(json.dumps(draft, ensure_ascii=False), article)
                if resolved.model_dump() != item.result.model_dump() or validation["approved"]:
                    raise ValueError("stored result mismatch")
                if validation["status"] != "needs_review":
                    raise ValueError("not a reviewable draft")
                output.append(DemoArticle(
                    article_id=article.id, title=article.title, source=article.source,
                    tts_sentences=resolved.tts_sentences, one_line=resolved.one_line, detail=resolved.detail,
                    validation=ApiValidation(status="needs_review")))
            return DemoBriefing(articles=output)
        except (ValidationError, ValueError, KeyError, TypeError, SummaryError):
            raise HTTPException(500, detail={"code": "demo_data_invalid"}) from None

    from .review import ReviewStore
    store = review_store or (SharedReviewStore() if enabled() else ReviewStore())

    @api.get("/v1/briefings/current", response_model=ApprovedBriefing)
    def approved_briefing():
        try:
            return store.briefing()
        except (ValueError, OSError, sqlite3.Error):
            raise HTTPException(503, detail={"code": "review_data_unavailable"}) from None

    from .planning import planning_router
    api.include_router(planning_router(store))
    from .candidates import candidate_router
    api.include_router(candidate_router(repository))
    from .real_news import current_catalog
    from .sessions import SessionStore, session_router
    sessions = session_store or SessionStore(ROOT / '.cache/sessions.sqlite3')
    api.include_router(session_router(briefing_catalog or current_catalog, sessions))
    api.include_router(news_router(repository))
    return api


app = create_app(demo_enabled=os.getenv("DRIVEBRIEF_DEMO_ENABLED") == "1", collect_news=True)
