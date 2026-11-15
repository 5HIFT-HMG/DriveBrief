import argparse
from dataclasses import replace
import importlib.util
import json
import os
import sqlite3
from pathlib import Path
import time

from .real_news import ROOT, DEFAULT_DB, RealReviewStore, load_candidates
from drivebrief_summary.providers import Settings, GroqProvider, MockProvider


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def cycle(news_db, config_path, review_db, provider_name, lengths, allow_external=False):
    if provider_name == 'groq' and (not allow_external or os.getenv('DRIVEBRIEF_ALLOW_GROQ') != '1'
                                    or not os.getenv('GROQ_API_KEY', '').strip()):
        raise ValueError('groq_configuration_required')
    crawler = module('pipeline_crawler', ROOT / 'news_crawler/news.py')
    bodies = module('pipeline_bodies', ROOT / 'news_crawler/full_text.py')
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    feeds = config.get('feeds', [])
    if not feeds or any(f.get('category') not in crawler.CATEGORIES or not f.get('source')
                        or not crawler.safe_url(f.get('url')) for f in feeds):
        raise ValueError('invalid_feed_configuration')
    db = crawler.connect(news_db)
    try:
        feed_successes = crawler.collect(db, feeds)
        body_successes = bodies.collect_bodies(db, config.get('body_sources', {}))
    finally:
        db.close()
    outcomes = {}
    store = RealReviewStore(review_db)
    for length in lengths:
        records, blocked = load_candidates(news_db, config_path, 10, length)
        provider = (GroqProvider(replace(Settings.from_env(), summary_length=length))
                    if provider_name == 'groq' else MockProvider(length))
        outcomes[length] = {'outcomes': store.generate(records, provider, Path(review_db).parent / 'real-summaries.sqlite3'),
                            'blocked': blocked}
    return {'feed_successes': feed_successes, 'body_successes': body_successes,
            'provider': provider_name, 'lengths': outcomes, 'automatic_approval': False}


def main():
    parser = argparse.ArgumentParser(description='RSS -> body -> length-specific summary -> review queue')
    parser.add_argument('--news-db', type=Path, default=ROOT / 'news_crawler/news.sqlite3')
    parser.add_argument('--config', type=Path, default=ROOT / 'news_crawler/config.json')
    parser.add_argument('--review-db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--provider', choices=['mock', 'groq'], default='mock')
    parser.add_argument('--allow-external', action='store_true')
    parser.add_argument('--length', choices=['short', 'medium', 'long', 'all'], default='all')
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--interval', type=int, default=900)
    args = parser.parse_args()
    if args.interval < 300:
        parser.error('--interval must be at least 300 seconds')
    lengths = ('short', 'medium', 'long') if args.length == 'all' else (args.length,)
    try:
        while True:
            result = cycle(args.news_db, args.config, args.review_db, args.provider, lengths, args.allow_external)
            print(json.dumps(result), flush=True)
            failed = result['feed_successes'] == 0 or any(
                o['status'] == 'failed' for batch in result['lengths'].values() for o in batch['outcomes'])
            if not args.watch:
                return int(failed)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({'error': type(exc).__name__, 'message': 'Check pipeline configuration; no auto-approval'}))
        raise SystemExit(1)
