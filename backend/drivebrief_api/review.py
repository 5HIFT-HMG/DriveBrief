"""Local, fictional-only review workflow. Never reads RSS or auto-approves."""
import argparse
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Literal, ClassVar

from pydantic import Field, ValidationError
from drivebrief_summary.models import Article, StrictModel
from drivebrief_summary.service import Summarizer, check_rights, digest
from drivebrief_summary.providers import MockProvider, GroqProvider, Settings
from drivebrief_summary.validation import resolve_draft, VALIDATION_VERSION
from drivebrief_summary.errors import SummaryError

_DEFAULT_LIMIT = object()

DEFAULT_DB = Path(__file__).resolve().parents[1] / ".cache/review.sqlite3"


class InputArticle(StrictModel):
    allowed_kinds: ClassVar[tuple] = ("fictional",)
    article: Article
    published_at: str
    authored_at: Optional[str] = None
    source_url: Optional[str] = None
    origin: str = Field(min_length=1, max_length=1000)

    def checked(self):
        check_rights(self.article)
        # Phase 6 does not authorize real news, even if supplied rights claim otherwise.
        if self.article.rights.kind not in self.allowed_kinds:
            raise ValueError("fictional_only")
        for value in (self.published_at, self.authored_at):
            if value is not None and datetime.fromisoformat(value).tzinfo is None:
                raise ValueError("timezone_required")
        if self.source_url is not None:
            from urllib.parse import urlsplit
            u = urlsplit(self.source_url)
            if u.scheme != "https" or not u.netloc or u.username or u.password:
                raise ValueError("invalid_url")
        return self


def resolve(record, draft):
    record.checked()
    summary, validation, links = resolve_draft(json.dumps(draft, ensure_ascii=False), record.article)
    if summary.status != "ok":
        raise ValueError("insufficient")
    return summary, validation, links


class ReviewStore:
    record_type = InputArticle
    fictional_only = True
    output_limit = 10

    def __init__(self, path=DEFAULT_DB):
        self.path = Path(path)

    def write_db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(self.path))
        db.execute("CREATE TABLE IF NOT EXISTS reviews (id TEXT PRIMARY KEY, record TEXT NOT NULL, draft TEXT NOT NULL, provenance TEXT NOT NULL, decision TEXT NOT NULL, approval TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS decisions (id TEXT NOT NULL, at TEXT NOT NULL, reviewer TEXT NOT NULL, decision TEXT NOT NULL, revision TEXT NOT NULL)")
        return db

    def rows(self):
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            return db.execute("SELECT id,record,draft,provenance,decision,approval FROM reviews ORDER BY id").fetchall()

    def get(self, article_id):
        rows = [r for r in self.rows() if r[0] == article_id]
        if not rows:
            raise ValueError("article_missing")
        return rows[0]

    def generate(self, records, provider, cache):
        service = Summarizer(provider, cache)
        outcomes = []
        # Each failure is isolated; no retry and no source/provider error body logs.
        for raw in records:
            try:
                record = self.record_type.model_validate(raw).checked()
                result = service.summarize(record.article)
                draft = dict(result["result"])
                draft.pop("evidence_snippets")
                draft["evidence_links"] = result["evidence_links"]
                resolve(record, draft)
                encoded = record.model_dump_json()
                d = json.dumps(draft, ensure_ascii=False)
                p = json.dumps(result["provenance"])
                with closing(self.write_db()) as db, db:
                    old = db.execute("SELECT record,draft,provenance FROM reviews WHERE id=?", (record.article.id,)).fetchone()
                    # Identical content keeps its decision. Changed source/draft revokes approval.
                    if (old is None or old[:2] != (encoded, d)
                            or json.loads(old[2]).get("cache_key") != result["provenance"]["cache_key"]):
                        db.execute("INSERT OR REPLACE INTO reviews VALUES (?,?,?,?,?,NULL)",
                                   (record.article.id, encoded, d, p, "needs_review"))
                    decision = db.execute("SELECT decision FROM reviews WHERE id=?", (record.article.id,)).fetchone()[0]
                outcomes.append({"status": decision, "cached": result["provenance"]["cached"]})
            except (SummaryError, ValidationError, ValueError, TypeError, sqlite3.Error, OSError):
                # A failed replacement must not leave an older approval silently playable.
                article_id = raw.get("article", {}).get("id") if isinstance(raw, dict) and isinstance(raw.get("article"), dict) else None
                if isinstance(article_id, str) and self.path.exists():
                    with closing(self.write_db()) as db, db:
                        db.execute("UPDATE reviews SET decision='needs_review',approval=NULL WHERE id=?", (article_id,))
                outcomes.append({"status": "failed"})
        return outcomes

    def review_document(self, article_id):
        _, raw, draft, provenance, decision, _ = self.get(article_id)
        record = self.record_type.model_validate_json(raw)
        summary, validation, links = resolve(record, json.loads(draft))
        from drivebrief_summary.segments import split_article
        from drivebrief_summary.quality_review import diagnostics
        return {"record": record.model_dump(), "draft": json.loads(draft),
                "result": summary.model_dump(), "validation": validation,
                "evidence_links": links,
                "source_spans": [s.as_dict() for s in split_article(record.article)],
                "decision": decision, "revision": digest([raw, draft]),
                "mock": json.loads(provenance)["mock"],
                "quality_diagnostics": diagnostics(record.article, json.loads(draft))}

    def decide(self, article_id, reviewer, decision, expected_revision, edited=None):
        if not reviewer.strip() or len(reviewer) > 100 or decision not in ("approved", "rejected"):
            raise ValueError("decision_invalid")
        with closing(self.write_db()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT record,draft FROM reviews WHERE id=?", (article_id,)).fetchone()
            if not row or digest(list(row)) != expected_revision:
                raise ValueError("stale_review")
            raw, draft = row
            record = self.record_type.model_validate_json(raw)
            if edited is not None:
                draft = json.dumps(edited, ensure_ascii=False)
            resolve(record, json.loads(draft))  # edits cannot bypass evidence/schema/rights
            revision = digest([raw, draft])
            approval = json.dumps({"reviewer": reviewer, "at": datetime.now(timezone.utc).isoformat(),
                                   "revision": revision, "validator": VALIDATION_VERSION})
            db.execute("UPDATE reviews SET draft=?,decision=?,approval=? WHERE id=?",
                       (draft, decision, approval, article_id))
            db.execute("INSERT INTO decisions VALUES (?,?,?,?,?)",
                       (article_id, datetime.now(timezone.utc).isoformat(), reviewer, decision, revision))

    def briefing(self, limit=_DEFAULT_LIMIT):
        if limit is _DEFAULT_LIMIT:
            limit = self.output_limit
        output = []
        for article_id, raw, draft, provenance, decision, approval in self.rows():
            if decision != "approved":
                continue
            try:
                record = self.record_type.model_validate_json(raw)
                evidence = json.loads(approval)
                if (evidence["revision"] != digest([raw, draft])
                        or evidence["validator"] != VALIDATION_VERSION or not evidence["reviewer"].strip()):
                    raise ValueError("stale_approval")
                summary, _, _ = resolve(record, json.loads(draft))
                output.append({"article_id": article_id, "title": record.article.title,
                               "source": record.article.source, "published_at": record.published_at,
                               "source_url": record.source_url,
                               "tts_sentences": summary.tts_sentences, "one_line": summary.one_line,
                               "detail": summary.detail, "mock": bool(json.loads(provenance)["mock"]),
                               "validation": {"status": "approved", "approved": True, "review_required": False}})
            except (ValueError, TypeError, KeyError, SummaryError):
                # Fail closed for the whole response; never expose corrupt records or raw text.
                raise ValueError("review_data_invalid") from None
        return {"schema_version": "approved-briefing-v1", "fictional_only": self.fictional_only,
                "playback_requires_user_action": True, "articles": output if limit is None else output[:limit]}


def main():
    parser = argparse.ArgumentParser(description="Local fictional article review; no auto-approval")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("--input", type=Path, required=True)
    generate.add_argument("--provider", choices=["mock", "groq"], default="mock")
    generate.add_argument("--selected-ids", type=Path, help="Explicit selected ID JSON array; separate verified full-text input required")
    generate.add_argument("--allow-external", action="store_true")
    generate.add_argument("--cache", type=Path, default=DEFAULT_DB.parent / "stage6-summaries.sqlite3")
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--id", required=True)
    inspect.add_argument("--output", type=Path, required=True)
    decision = sub.add_parser("decide")
    decision.add_argument("--id", required=True)
    decision.add_argument("--reviewer", required=True)
    decision.add_argument("--revision", required=True)
    decision.add_argument("--decision", choices=["approved", "rejected"], required=True)
    decision.add_argument("--edited-draft", type=Path)
    decision.add_argument("--confirm-human-review", action="store_true")
    args = parser.parse_args()
    try:
        store = ReviewStore(args.db)
        if args.command == "generate":
            records = json.loads(args.input.read_text(encoding="utf-8"))
            if not isinstance(records, list) or not 1 <= len(records) <= 10:
                raise ValueError("batch_size")
            if args.selected_ids:
                from .summary_inputs import selected_inputs
                records = selected_inputs(json.loads(args.selected_ids.read_text(encoding="utf-8")), records)
            if args.provider == "groq":
                if not args.allow_external or os.getenv("DRIVEBRIEF_ALLOW_GROQ") != "1":
                    raise ValueError("external_opt_in_required")
                # Validate all input rights before making even one external request.
                for raw in records:
                    InputArticle.model_validate(raw).checked()
                provider = GroqProvider(Settings.from_env())
            else:
                provider = MockProvider()
            outcomes = store.generate(records, provider, args.cache)
            print(json.dumps({"outcomes": outcomes}))
            return int(any(o["status"] == "failed" for o in outcomes))
        elif args.command == "inspect":
            document = store.review_document(args.id)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as f:
                json.dump(document, f, ensure_ascii=False, indent=2)
            print('{"status":"review_exported"}')
        else:
            if not args.confirm_human_review:
                raise ValueError("human_review_confirmation_required")
            edited = json.loads(args.edited_draft.read_text(encoding="utf-8")) if args.edited_draft else None
            store.decide(args.id, args.reviewer, args.decision, args.revision, edited)
            print('{"status":"decision_saved"}')
        return 0
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error, SummaryError):
        print('{"error":"review_operation_failed","message":"Check input, rights, revision and review confirmation; no retry"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
