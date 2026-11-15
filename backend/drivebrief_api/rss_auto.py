"""RSS automatic briefing: exact metadata extraction, no LLM and no human approval flags."""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Literal
from urllib.parse import urlencode, urlsplit
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .news_repository import crawler
from .pipeline_settings import load_config
from .selection import metadata, group_events, rank_groups, balanced_select, timestamp, normalize

VERSION = "rss-extract-v4-short-lead"
OPTIONS = {"짧게": 1, "중간": 3, "길게": 5}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class AutoValidation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["rss_auto_validated"] = "rss_auto_validated"
    method: Literal["metadata_exact_extract_v1"] = "metadata_exact_extract_v1"
    human_reviewed: Literal[False] = False


class RssArticle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    article_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=250)
    source: str = Field(min_length=1, max_length=300)
    published_at: str
    source_url: str
    content_kind: Literal["rss_metadata"] = "rss_metadata"
    tts_sentences: List[str] = Field(min_length=1, max_length=5)
    one_line: str = Field(min_length=1, max_length=250)
    detail: str = Field(min_length=1, max_length=2500)
    categories: List[Literal["경제", "사회", "정치", "IT", "스포츠"]] = Field(min_length=1, max_length=5)
    validation: AutoValidation = Field(default_factory=AutoValidation)
    available_sentence_count: int = Field(ge=1, le=5)
    sentence_indices: List[int]
    partial_tts: bool
    order: int
    group_id: str
    importance_score: float

    @model_validator(mode="after")
    def check(self):
        url = urlsplit(self.source_url)
        if (url.scheme not in ("https", "http") or not url.hostname or url.username or url.password
                or timestamp(self.published_at) is None
                or any(not s.strip() or len(s) > 350 or "\n" in s for s in self.tts_sentences)
                or self.sentence_indices != list(range(len(self.tts_sentences)))
                or len(self.tts_sentences) > self.available_sentence_count
                or self.partial_tts != (len(self.tts_sentences) < self.available_sentence_count)):
            raise ValueError("invalid_rss_article")
        quality = crawler.content_quality.assess(self.title, self.detail)
        if not quality['eligible'] or quality['title'] != self.title or quality['description'] != self.detail:
            raise ValueError("unsafe_rss_content")
        expected = source_units(self.title, self.detail if self.detail != self.title else "")
        valid_text = (self.tts_sentences == expected[:len(self.tts_sentences)]
                      or self.tts_sentences == [short_sentence(self.title, self.detail)])
        if (self.one_line != self.title or self.available_sentence_count != len(expected)
                or not valid_text):
            raise ValueError("rss_text_not_in_metadata")
        return self


class RssBriefing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["rss-briefing-v1"] = "rss-briefing-v1"
    content_kind: Literal["rss_metadata"] = "rss_metadata"
    processing: Literal["automatic_metadata_extraction"] = "automatic_metadata_extraction"
    usage_rights_status: Literal["source_terms_not_verified"] = "source_terms_not_verified"
    playback_requires_user_action: Literal[True] = True
    catalog_id: str
    briefing_id: str
    length_option: Literal["짧게", "중간", "길게"]
    option_semantics: Literal["article_detail"] = "article_detail"
    sentence_limit: int
    generated_at: str
    latest_source_at: str
    input_revision: str
    articles: List[RssArticle] = Field(min_length=0, max_length=25)

    @model_validator(mode="after")
    def check(self):
        if (self.sentence_limit != OPTIONS[self.length_option]
                or timestamp(self.generated_at) is None or timestamp(self.latest_source_at) is None
                or len({a.article_id for a in self.articles}) != len(self.articles)
                or [a.order for a in self.articles] != list(range(1, len(self.articles) + 1))
                or any(len(a.tts_sentences) != min(self.sentence_limit, a.available_sentence_count) for a in self.articles)):
            raise ValueError("invalid_rss_briefing")
        for article in self.articles:
            expected = ([short_sentence(article.title, article.detail)] if self.length_option == "짧게"
                        else source_units(article.title, article.detail)[:self.sentence_limit])
            if article.tts_sentences != expected:
                raise ValueError("rss_text_not_in_option_source")
        return self


def source_units(title, description):
    units, seen = [], set()
    # No generated connective, summary, ellipsis or split inside a sentence.
    for text in [title] + re.split(r"(?<=[.!?。！？])\s+|[\r\n]+", description):
        text = text.strip()
        if not text:
            continue
        if len(text) > 350:
            break
        key = re.sub(r"\s+", "", text).rstrip(".!?。！？")
        if key in seen:
            continue
        seen.add(key)
        units.append(text)
        if len(units) == 5:
            break
    return units


def short_sentence(title, description):
    """Exact first complete lead, or the original title. No rewriting or later-sentence search."""
    sentence = re.split(r"(?<=[.!?。！？])\s+|[\r\n]+", description or "", maxsplit=1)[0].strip()
    compact = lambda text: re.sub(r"[^가-힣a-z0-9]", "", normalize(text))
    key, heading = compact(sentence), compact(title)
    repeats = bool(heading) and heading in key and len(key) <= len(heading) + 12
    paired = all(sentence.count(a) == sentence.count(b) for a, b in (("“", "”"), ("‘", "’"), ("「", "」"), ("『", "』")))
    quoted = sentence.count('"') % 2 == 0 and sentence.count("'") % 2 == 0
    if (len(re.sub(r"\s", "", sentence)) < 20 or len(sentence) > 350
            or len(re.findall(r"[가-힣a-zA-Z0-9]+", sentence)) < 4
            or not crawler.content_quality.complete(sentence) or not paired or not quoted
            or repeats):
        return title
    return sentence


def prepare(rows, cfg, now, max_articles=25):
    if type(max_articles) is not int or not 1 <= max_articles <= 25:
        raise ValueError("invalid_rss_limit")
    valid, units = [], {}
    for item in metadata(rows):
        quality = crawler.content_quality.assess(item["title"], item["description"])
        if not quality['eligible']:
            continue
        title, body = quality['title'], quality['description']
        stamp = timestamp(item["published_at"])
        categories = [c for c in item["categories"] if c in ("경제", "사회", "정치", "IT", "스포츠")]
        if (not stamp or not now - timedelta(days=5) <= stamp <= now
                or not categories or not item["sources"] or not 1 <= len(title) <= 250
                or len(body) > 2500 or "\n" in title or re.search(r"<[^>]+>", title + body)):
            continue
        spoken = source_units(title, body)
        if not spoken:
            continue
        item = dict(item, title=title, description=body, categories=categories)
        valid.append(item)
        units[item["article_id"]] = spoken
    if not valid:
        recent = [a for a in metadata(rows) if timestamp(a['published_at'])
                  and now-timedelta(days=5) <= timestamp(a['published_at']) <= now]
        if not recent:
            raise ValueError("no_usable_rss_news")
    return valid, units, digest([VERSION, valid, cfg, max_articles])


def build(rows, config=None, now=None, max_articles=25, prepared=None):
    cfg, now = config or load_config(), now or datetime.now(timezone.utc)
    valid, units, revision = prepared or prepare(rows, cfg, now, max_articles)
    # The source timestamp makes unchanged inputs reproducible; never mutate algorithm/weights.
    as_of = max(timestamp(a["published_at"]) for a in (valid or metadata(rows))
                if timestamp(a["published_at"]) and now-timedelta(days=5) <= timestamp(a["published_at"]) <= now)
    groups = group_events(valid, cfg)
    ranked = rank_groups(groups, [], as_of, cfg)
    selected = balanced_select(ranked, [], max_articles, cfg["event"]["balance_penalty"])
    catalog = "rss_" + revision[:24]
    originals = {a["article_id"]: a for a in valid}
    documents = {}
    for option, limit in OPTIONS.items():
        articles = []
        for position, chosen in enumerate(selected, 1):
            original = originals[chosen["article_id"]]
            all_units = units[chosen["article_id"]]
            spoken = ([short_sentence(original["title"], original["description"])]
                      if option == "짧게" else all_units[:limit])
            articles.append(dict(
                article_id=chosen["article_id"], title=original["title"], source=chosen["source"],
                published_at=original["published_at"], source_url=original["source_url"],
                tts_sentences=spoken, one_line=original["title"], detail=original["description"] or original["title"],
                categories=chosen["categories"], available_sentence_count=len(all_units),
                sentence_indices=list(range(len(spoken))), partial_tts=len(spoken) < len(all_units),
                order=position, group_id=chosen["group_id"], importance_score=chosen["importance_score"]))
        documents[option] = RssBriefing(catalog_id=catalog, briefing_id=catalog + "_" + str(limit),
            length_option=option, sentence_limit=limit, generated_at=now.isoformat(),
            latest_source_at=as_of.isoformat(), input_revision=revision, articles=articles).model_dump()
    return documents


def read_news(remote, limit=200):
    if type(limit) is not int or not 25 <= limit <= 1000:
        raise ValueError("invalid_rss_candidate_limit")
    rows = remote.request("news_articles?" + urlencode({
        "select": "url,title,description,published_at,news_memberships(category,source)",
        "order": "published_at.desc,url.asc", "limit": limit}))
    return [dict(row, category=m["category"], source=m["source"]) for row in rows
            for m in row.get("news_memberships", [])]


def checked_catalog(documents):
    if set(documents) != set(OPTIONS):
        raise ValueError("incomplete_rss_options")
    checked = {key: RssBriefing.model_validate(value).model_dump() for key, value in documents.items()}
    baseline = checked["짧게"]
    ids = [a["article_id"] for a in baseline["articles"]]
    for key, document in checked.items():
        if (document["length_option"] != key or document["catalog_id"] != baseline["catalog_id"]
                or document["input_revision"] != baseline["input_revision"]
                or [a["article_id"] for a in document["articles"]] != ids):
            raise ValueError("inconsistent_rss_catalog")
    stable_fields = ("article_id", "title", "source", "published_at", "source_url", "detail",
                     "one_line", "categories", "available_sentence_count", "group_id", "importance_score")
    for document in checked.values():
        if any(any(article[field] != baseline["articles"][i][field] for field in stable_fields)
               for i, article in enumerate(document["articles"])):
            raise ValueError("inconsistent_rss_metadata")
    return checked


def publish(documents, remote, dry_run=False, current=None):
    checked = checked_catalog(documents)
    baseline = checked["짧게"]
    ids = [a["article_id"] for a in baseline["articles"]]
    current = current if current is not None else remote.request("published_briefings?select=length_option,revision,briefing&order=length_option.asc")
    revision = baseline["input_revision"]
    if len(current) == 3 and all(r["revision"] == revision for r in current):
        try:
            checked_catalog({r["length_option"]: r["briefing"] for r in current})
            return {"status": "unchanged", "articles": len(ids)}
        except ValueError:
            pass
    if dry_run:
        return {"status": "dry_run", "articles": len(ids)}
    published_at = datetime.now(timezone.utc).isoformat()
    # One PostgREST batch request is one PostgreSQL transaction: all options or none.
    remote.request("published_briefings?on_conflict=length_option", "POST",
        [dict(length_option=k, namespace="real", briefing=v, revision=revision, published_at=published_at)
         for k, v in checked.items()], prefer="resolution=merge-duplicates,return=minimal")
    return {"status": "published", "articles": len(ids), "generated_at": baseline["generated_at"]}


def refresh(remote, dry_run=False, now=None):
    cfg, now = load_config(), now or datetime.now(timezone.utc)
    rows = read_news(remote)
    prepared = prepare(rows, cfg, now)
    current = remote.request("published_briefings?select=length_option,revision,briefing&order=length_option.asc")
    if len(current) == 3 and {r["length_option"] for r in current} == set(OPTIONS) and all(
            r["revision"] == prepared[2] for r in current):
        # Validate stored data before reusing it; corrupted rows are repaired by one atomic batch.
        try:
            checked_catalog({row["length_option"]: row["briefing"] for row in current})
            return {"status": "unchanged", "articles": len(current[0]["briefing"]["articles"])}
        except ValueError:
            pass
    return publish(build(rows, cfg, now, prepared=prepared), remote, dry_run, current=[])


def publication_status(remote):
    rows = remote.request("published_briefings?select=length_option,revision,briefing,published_at")
    checked = checked_catalog({row["length_option"]: row["briefing"] for row in rows})
    return {"status": "ready", "same_article_ids_and_order": True,
            "options": {option: {"articles": len(doc["articles"]),
                "sentence_counts": {str(n): sum(len(a["tts_sentences"]) == n for a in doc["articles"])
                                    for n in range(1,6)},
                "generated_at": doc["generated_at"], "latest_source_at": doc["latest_source_at"]}
                        for option, doc in checked.items()},
            "sources": sorted({a["source"] for a in checked["짧게"]["articles"]})}


def main():
    parser = argparse.ArgumentParser(description="RSS automatic briefing; no LLM, no article approval")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true", help="Read-only publication validation and counts; never article text")
    args = parser.parse_args()
    try:
        from .shared_backend import SharedDatabase
        outcome = publication_status(SharedDatabase()) if args.status else refresh(SharedDatabase(), args.dry_run)
        print(json.dumps(outcome, ensure_ascii=False))
        return 0
    except Exception as error:
        # Never log provider responses, article bodies, keys or URLs from exceptions.
        safe = {"no_usable_rss_news", "invalid_rss_limit", "inconsistent_rss_catalog"}
        print(json.dumps({"status": "failed_existing_publication_preserved",
                          "reason": str(error) if str(error) in safe else type(error).__name__}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
