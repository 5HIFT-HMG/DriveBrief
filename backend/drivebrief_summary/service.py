import hashlib
import json
import re
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .errors import SummaryError
from .models import Article, Draft, Summary, insufficient_draft
from .prompt import PROMPT_VERSION, SYSTEM_PROMPT
from .providers import Provider
from .segments import SEGMENT_VERSION, split_article
from .validation import VALIDATION_VERSION, resolve_draft

OUTPUT_VERSION = "2-source-ids-review"


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def check_rights(article: Article):
    rights = article.rights
    if (rights.kind not in ("fictional", "licensed") or not rights.external_llm_allowed
            or not rights.summary_reuse_allowed or not rights.basis.strip()):
        raise SummaryError("permission_denied", "Verified external processing and summary reuse permission is required")


def validate_summary(raw: str, article: Article) -> Summary:
    """Accept the new ID-based draft and return legacy-shaped, Python-resolved evidence."""
    return resolve_draft(raw, article)[0]


class Summarizer:
    def __init__(self, provider: Provider, cache_path: Path):
        self.provider = provider
        self.cache_path = Path(cache_path)

    def summarize(self, article: Article) -> dict:
        check_rights(article)
        identity = {
            "source_sha256": digest(article.model_dump()),
            "provider": self.provider.name,
            "settings": asdict(self.provider.settings),
            "prompt_version": PROMPT_VERSION,
            "prompt_sha256": digest(SYSTEM_PROMPT),
            "schema_sha256": digest(Draft.model_json_schema()),
            "public_schema_sha256": digest(Summary.model_json_schema()),
            "validation_version": VALIDATION_VERSION,
            "segment_version": SEGMENT_VERSION,
            "output_version": OUTPUT_VERSION,
        }
        cache_key = digest(identity)
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(str(self.cache_path), timeout=150) as db:
                db.execute("CREATE TABLE IF NOT EXISTS summaries (cache_key TEXT PRIMARY KEY, result TEXT NOT NULL, created_at TEXT NOT NULL)")
                db.execute("BEGIN IMMEDIATE")
                cached = db.execute("SELECT result, created_at FROM summaries WHERE cache_key=?", (cache_key,)).fetchone()
                if cached:
                    raw, created = cached
                    try:
                        result, validation, links = resolve_draft(raw, article)
                    except SummaryError:
                        raise SummaryError("cache_corrupt", "Cached draft is invalid; inspect or remove the local cache") from None
                else:
                    count = len([s for s in re.split(r"(?<=[.!?。])\s+", article.body.strip()) if s])
                    if len(article.body.strip()) < 100 or count < 2:
                        raw = insufficient_draft("원문이 짧거나 완결된 설명이 부족합니다.").model_dump_json()
                    else:
                        raw = self.provider.generate(article)
                    result, validation, links = resolve_draft(raw, article)
                    maximum = {"default": 8, "short": 1, "medium": 2, "long": 3}[self.provider.settings.summary_length]
                    if len(result.tts_sentences) > maximum:
                        raise SummaryError("summary_length", "Provider exceeded requested sentence count")
                    created = datetime.now(timezone.utc).isoformat()
                    # Cache draft IDs, never approval supplied by an LLM. Revalidate every hit.
                    db.execute("INSERT INTO summaries VALUES (?, ?, ?)", (cache_key, raw, created))
                used_ids = {span_id for link in links for span_id in link["evidence_ids"]}
                references = [span.as_dict() for span in split_article(article) if span.id in used_ids]
                return {
                    "schema_version": OUTPUT_VERSION,
                    "article_id": article.id,
                    "result": result.model_dump(),
                    "validation": validation,
                    "evidence_links": links,
                    "evidence_sources": references,
                    "provenance": dict(identity, cache_key=cache_key, created_at=created,
                                       cached=bool(cached), mock=self.provider.name.startswith("mock"),
                                       review_required=True, approved=False),
                }
        except sqlite3.Error:
            raise SummaryError("cache_io", "SQLite cache operation failed") from None
        except OSError:
            raise SummaryError("cache_io", "Cache directory is unavailable") from None
