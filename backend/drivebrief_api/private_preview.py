"""Read-only RSS preview: no approval, LLM, review DB or remote writes."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from .selection import metadata, CATEGORIES, timestamp
from .planning import plan
from .pipeline_models import PrivateRssPreview


def preview_input(rows):
    articles = []
    for item in metadata(rows):
        title, description = item["title"], item["description"] or ""
        url = urlsplit(item["source_url"])
        if (url.scheme != "https" or not item["sources"] or not timestamp(item["published_at"])
                or not 1 <= len(title) <= 250 or len(description) > 2500):
            continue
        # Exact metadata only; stop at the first oversized span, never skip context.
        sentences = [title]
        for sentence in re.split(r"(?<=[.!?。！？])\s+|[\r\n]+", description):
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) > 350 or len(sentences) == 8:
                break
            sentences.append(sentence)
        articles.append(dict(item, source=item["sources"][0], tts_sentences=sentences,
            one_line=title, detail=description or title, mock=False, content_kind="rss_metadata",
            categories=[c for c in item["categories"] if c in CATEGORIES],
            validation={"status": "needs_review", "approved": False, "review_required": True}))
    return dict(schema_version="rss-preview-input-v1", fictional_only=False, content_kind="rss_metadata",
                preview_only=True, publication_allowed=False, articles=articles)


def build_preview(rows, config, as_of=None):
    document = preview_input(rows)
    now = as_of or datetime.now(timezone.utc)
    return {option: PrivateRssPreview.model_validate(
        plan(document, option, [], config, as_of=now, private_preview=True)).model_dump()
        for option in ("짧게", "중간", "길게")}


def read_recent(remote, limit=200):
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("invalid_preview_limit")
    raw = remote.request("news_articles?" + urlencode({
        "select": "url,title,description,published_at,news_memberships(category,source)",
        "order": "published_at.desc,url.asc", "limit": limit}))
    return [dict(row, category=m["category"], source=m["source"])
            for row in raw for m in row.get("news_memberships", [])], len(raw)


def save_preview(plans, path):
    # Generated real metadata stays under ignored backend/results, never a tracked fixture.
    destination = Path(path).resolve()
    results = Path(__file__).resolve().parents[1] / "results"
    if destination.parent != results:
        raise ValueError("preview_output_must_be_local_results")
    results.mkdir(exist_ok=True)
    with destination.open("x", encoding="utf-8") as file:
        json.dump(plans, file, ensure_ascii=False, indent=2)
