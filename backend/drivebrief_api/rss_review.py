"""Explicitly permitted RSS metadata -> existing human review. No provider or web-body fetch."""
import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal
from urllib.parse import urlencode, urlsplit

from pydantic import Field
from drivebrief_summary.models import Article, StrictModel
from drivebrief_summary.segments import split_article
from drivebrief_summary.service import digest
from .review import ReviewStore, resolve
from .selection import CATEGORIES, canonical, metadata, stable_id

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / ".cache/rss-review.sqlite3"
DEFAULT_POLICY = ROOT / ".cache/rss-tts-policy.json"


class RssPermission(StrictModel):
    source: str = Field(min_length=1, max_length=300)
    article_host: str = Field(min_length=1, max_length=250)
    tts_allowed: bool = False
    reuse_allowed: bool = False
    basis: str = Field(min_length=1, max_length=1000)
    confirmed_by: str = Field(min_length=1, max_length=100)
    confirmed_at: str

    def checked(self):
        stamp = datetime.fromisoformat(self.confirmed_at)
        if (not self.tts_allowed or not self.reuse_allowed or not self.basis.strip()
                or not self.confirmed_by.strip() or stamp.tzinfo is None
                or stamp > datetime.now(timezone.utc) or "/" in self.article_host
                or self.article_host != self.article_host.lower()):
            raise ValueError("rss_permission_unverified")
        return self


def permissions(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if set(data) != {"sources"} or not isinstance(data["sources"], list):
            raise ValueError("rss_policy_invalid")
        values = [RssPermission.model_validate(row).checked() for row in data["sources"]]
        keys = [(p.source, p.article_host) for p in values]
        if len(keys) != len(set(keys)):
            raise ValueError("rss_policy_duplicate")
        return {key: p for key, p in zip(keys, values)}
    except FileNotFoundError:
        raise ValueError("rss_policy_missing") from None


class RssRecord(StrictModel):
    article: Article
    published_at: str
    source_url: str
    origin: Literal["rss_title_description"] = "rss_title_description"
    categories: List[Literal["경제", "사회", "정치", "IT", "스포츠"]] = Field(min_length=1, max_length=5)
    permission: RssPermission

    def checked(self):
        p = self.permission.checked()
        u = urlsplit(self.source_url)
        if (u.scheme != "https" or not u.hostname or u.username or u.password
                or u.hostname != p.article_host or self.article.source != p.source
                or datetime.fromisoformat(self.published_at).tzinfo is None):
            raise ValueError("rss_source_invalid")
        rights = self.article.rights
        if (rights.kind != "licensed" or rights.external_llm_allowed
                or not rights.summary_reuse_allowed or rights.basis != p.basis):
            raise ValueError("rss_rights_invalid")
        return self


def draft_for(record):
    spans = split_article(record.article)
    title = next(s for s in spans if s.field == "title")
    body = [s for s in spans if s.field == "body"]
    # No arbitrary truncation or rewriting to fit DTO limits. Long inputs need manual editing.
    spoken = [title] + body
    if len(spoken) > 8 or any(len(s.text) > 350 for s in spoken):
        raise ValueError("rss_metadata_too_long")
    return {"status": "ok", "reason": "", "tts_sentences": [s.text for s in spoken],
            "one_line": record.article.title,
            "detail": record.article.body or record.article.title,
            "evidence_links": [
                *[{"target": "tts_sentences", "index": i, "evidence_ids": [s.id]} for i, s in enumerate(spoken)],
                {"target": "one_line", "index": 0, "evidence_ids": [title.id]},
                {"target": "detail", "index": 0, "evidence_ids": [s.id for s in (body or [title])]}]}


class RssReviewStore(ReviewStore):
    record_type = RssRecord
    fictional_only = False
    output_limit = 300

    def __init__(self, path=DEFAULT_DB, policy_path=DEFAULT_POLICY):
        super().__init__(path)
        self.policy_path = Path(policy_path)

    def generate(self, *args, **kwargs):
        raise ValueError("rss_llm_generation_forbidden")

    def prepare(self, rows):
        allowed = permissions(self.policy_path)
        outcomes = []
        for item in metadata(rows):
            try:
                url = canonical(item["source_url"])
                host = urlsplit(url).hostname
                grant = next((allowed[(s, host)] for s in item["sources"] if (s, host) in allowed), None)
                if grant is None:
                    raise ValueError("rss_permission_unverified")
                record = RssRecord.model_validate({
                    "article": {"id": stable_id("rss_", url) + "_rss", "title": item["title"],
                                "body": item["description"], "source": grant.source,
                                "rights": {"kind": "licensed", "external_llm_allowed": False,
                                           "summary_reuse_allowed": True, "basis": grant.basis}},
                    "published_at": item["published_at"], "source_url": url,
                    "categories": [c for c in item["categories"] if c in CATEGORIES],
                    "permission": grant.model_dump()}).checked()
                draft = draft_for(record)
                resolve(record, draft)
                raw, text = record.model_dump_json(), json.dumps(draft, ensure_ascii=False)
                provenance = json.dumps({"provider": "rss_metadata", "mock": False})
                with closing(self.write_db()) as db, db:
                    old = db.execute("SELECT record,draft FROM reviews WHERE id=?", (record.article.id,)).fetchone()
                    if old != (raw, text):
                        db.execute("INSERT OR REPLACE INTO reviews VALUES (?,?,?,?,?,NULL)",
                                   (record.article.id, raw, text, provenance, "needs_review"))
                    decision = db.execute("SELECT decision FROM reviews WHERE id=?", (record.article.id,)).fetchone()[0]
                outcomes.append({"status": decision})
            except (ValueError, TypeError, KeyError):
                # A changed/invalid input must not leave its older approval publishable.
                article_id = stable_id("rss_", canonical(item["source_url"])) + "_rss"
                if self.path.exists():
                    with closing(self.write_db()) as db, db:
                        db.execute("UPDATE reviews SET decision=?, approval=NULL WHERE id=?",
                                   ("needs_review", article_id))
                outcomes.append({"status": "blocked"})
        return outcomes

    def briefing(self, limit=None):
        allowed = permissions(self.policy_path)
        result = super().briefing(limit)
        records = {row[0]: RssRecord.model_validate_json(row[1]) for row in self.rows()}
        for article in result["articles"]:
            record = records[article["article_id"]]
            active = allowed.get((record.article.source, urlsplit(record.source_url).hostname))
            if active is None or active.model_dump() != record.permission.model_dump():
                raise ValueError("rss_permission_changed")
            article.update(categories=record.categories, content_kind="rss_metadata")
        result["content_kind"] = "rss_metadata"
        return result


def main(argv=None):
    p = argparse.ArgumentParser(description="Permitted RSS metadata review; no LLM, no automatic approval")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    sub = p.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--limit", type=int, default=200)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--id", required=True)
    inspect.add_argument("--output", type=Path, required=True)
    decide = sub.add_parser("decide")
    decide.add_argument("--id", required=True)
    decide.add_argument("--reviewer", required=True)
    decide.add_argument("--revision", required=True)
    decide.add_argument("--decision", choices=["approved", "rejected"], required=True)
    decide.add_argument("--edited-draft", type=Path)
    decide.add_argument("--confirm-human-review", action="store_true")
    args = p.parse_args(argv)
    try:
        store = RssReviewStore(args.db, args.policy)
        if args.command == "prepare":
            if not 1 <= args.limit <= 200:
                raise ValueError("rss_limit_invalid")
            permissions(args.policy)  # Fail before any source read when policy is unavailable.
            from .shared_backend import SharedDatabase
            raw = SharedDatabase().request("news_articles?" + urlencode({
                "select": "url,title,description,published_at,news_memberships(category,source)",
                "order": "published_at.desc,url.asc", "limit": args.limit}))
            rows = [dict(r, category=m["category"], source=m["source"])
                    for r in raw for m in r.get("news_memberships", [])]
            print(json.dumps({"outcomes": store.prepare(rows)}))
        elif args.command == "inspect":
            document = store.review_document(args.id)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as f:
                json.dump(document, f, ensure_ascii=False, indent=2)
        else:
            if not args.confirm_human_review:
                raise ValueError("human_review_confirmation_required")
            edited = json.loads(args.edited_draft.read_text(encoding="utf-8")) if args.edited_draft else None
            store.decide(args.id, args.reviewer, args.decision, args.revision, edited)
        return 0
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error):
        print('{"error":"rss_review_operation_blocked","message":"Check permission, metadata and human review; no retry"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
