import argparse
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Literal
from urllib.parse import urlsplit

from .review import InputArticle, ReviewStore
from drivebrief_summary.providers import GroqProvider, MockProvider, Settings

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / 'backend/.cache/real-review.sqlite3'


class RealArticle(InputArticle):
    allowed_kinds = ('licensed',)
    category: Literal['경제', '사회', '정치', 'IT', '스포츠']
    summary_length: Literal['short', 'medium', 'long'] = 'long'


class RealReviewStore(ReviewStore):
    record_type = RealArticle
    fictional_only = False
    output_limit = 300

    def __init__(self, path=DEFAULT_DB):
        super().__init__(path)

    def briefing(self):
        result = super().briefing()
        records = {r[0]: self.record_type.model_validate_json(r[1]) for r in self.rows()}
        for article in result['articles']:
            article['category'] = records[article['article_id']].category
            article['summary_length'] = records[article['article_id']].summary_length
        return result


def load_candidates(news_db, config_path, limit=10, length="long"):
    if length not in ("short", "medium", "long"):
        raise ValueError("invalid_length")
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    policies = config.get('body_sources', {})
    days = config.get('max_article_age_days', 7)
    if type(days) is not int or not 1 <= days <= 30:
        raise ValueError('invalid_article_age')
    now = datetime.now(timezone.utc)
    with closing(sqlite3.connect(Path(news_db).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute('''SELECT a.url,a.title,a.published_at,b.body,b.body_sha256,
            MIN(m.source) AS source, MIN(m.category) AS category
            FROM articles a JOIN article_bodies b ON a.url=b.url
            JOIN memberships m ON m.url=a.url
            WHERE b.error IS NULL AND LENGTH(b.body)>=100
            GROUP BY a.url ORDER BY a.published_at DESC''').fetchall()
    records, blocked = [], 0
    for row in rows:
        published = datetime.fromisoformat(row['published_at'])
        if published.tzinfo is None or not now - timedelta(days=days) <= published <= now + timedelta(minutes=5):
            continue
        policy = policies.get(urlsplit(row['url']).hostname, {})
        rights = policy.get('rights', {})
        if (policy.get('collection_allowed') is not True or rights.get('kind') != 'licensed'
                or rights.get('external_llm_allowed') is not True
                or rights.get('summary_reuse_allowed') is not True or not rights.get('basis', '').strip()):
            blocked += 1
            continue
        if hashlib.sha256(row['body'].encode()).hexdigest() != row['body_sha256']:
            raise ValueError('body_hash_mismatch')
        record = RealArticle.model_validate({
            'article': {'id': 'rss_' + hashlib.sha256(row['url'].encode()).hexdigest()[:24] + '_' + length,
                        'title': row['title'], 'body': row['body'], 'source': row['source'], 'rights': rights},
            'published_at': row['published_at'], 'source_url': row['url'],
            'origin': 'news_crawler/article_bodies', 'category': row['category'], 'summary_length': length}).checked()
        if len(records) < limit:
            records.append(record.model_dump())
    return records, blocked


def current_catalog():
    from .shared_backend import enabled, SharedRealReviewStore
    store = SharedRealReviewStore() if enabled() else RealReviewStore()
    if not store.rows():
        return []
    records = []
    for length in ('short', 'medium', 'long'):
        batch, _ = load_candidates(ROOT / 'news_crawler/news.sqlite3', ROOT / 'news_crawler/config.json', 100, length)
        records.extend(batch)
    current = {r['article']['id']: r for r in records}
    stored = {r[0]: RealArticle.model_validate_json(r[1]).model_dump() for r in store.rows()}
    return [a for a in store.briefing()['articles']
            if a['article_id'] in current and stored[a['article_id']] == current[a['article_id']]]


def main():
    parser = argparse.ArgumentParser(description='Real article import and existing review workflow')
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest='command', required=True)
    generate = sub.add_parser('generate')
    generate.add_argument('--news-db', type=Path, default=ROOT / 'news_crawler/news.sqlite3')
    generate.add_argument('--config', type=Path, default=ROOT / 'news_crawler/config.json')
    generate.add_argument('--provider', choices=['mock', 'groq'], default='mock')
    generate.add_argument('--length', choices=['short', 'medium', 'long'], default='medium')
    generate.add_argument('--allow-external', action='store_true')
    generate.add_argument('--limit', type=int, default=10)
    inspect = sub.add_parser('inspect')
    inspect.add_argument('--id', required=True)
    inspect.add_argument('--output', type=Path, required=True)
    decide = sub.add_parser('decide')
    decide.add_argument('--id', required=True)
    decide.add_argument('--reviewer', required=True)
    decide.add_argument('--revision', required=True)
    decide.add_argument('--decision', choices=['approved', 'rejected'], required=True)
    decide.add_argument('--edited-draft', type=Path)
    decide.add_argument('--confirm-human-review', action='store_true')
    args = parser.parse_args()
    store = RealReviewStore(args.db)
    if args.command == 'generate':
        if not 1 <= args.limit <= 100:
            parser.error('--limit must be 1..100')
        records, blocked = load_candidates(args.news_db, args.config, args.limit, args.length)
        provider = MockProvider(args.length)
        if args.provider == 'groq':
            if not args.allow_external or os.getenv('DRIVEBRIEF_ALLOW_GROQ') != '1':
                parser.error('external_opt_in_required')
            provider = GroqProvider(replace(Settings.from_env(), summary_length=args.length))
        outcomes = store.generate(records, provider, DEFAULT_DB.parent / 'real-summaries.sqlite3')
        print(json.dumps({'outcomes': outcomes, 'blocked': blocked}))
        return int(any(item['status'] == 'failed' for item in outcomes))
    if args.command == 'inspect':
        document = store.review_document(args.id)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as target:
            json.dump(document, target, ensure_ascii=False, indent=2)
    else:
        if not args.confirm_human_review:
            parser.error('human_review_confirmation_required')
        edited = json.loads(args.edited_draft.read_text()) if args.edited_draft else None
        store.decide(args.id, args.reviewer, args.decision, args.revision, edited)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, sqlite3.Error):
        print('{"error":"real_news_operation_failed"}')
        raise SystemExit(1)
