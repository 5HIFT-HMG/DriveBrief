import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import gzip
import io
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .news_repository import NewsRepository, PROJECT, crawler
from .review import ReviewStore

spec = importlib.util.spec_from_file_location('drivebrief_shared_settings', PROJECT / 'news_crawler/shared_db.py')
shared_settings = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared_settings)


def enabled():
    return os.getenv('DRIVEBRIEF_SHARED_DB') == '1'


class SharedDatabase:
    def __init__(self, config=None, opener=None):
        cfg = shared_settings.settings() if config is None else config
        self.base = cfg.get('SUPABASE_URL', '').rstrip('/')
        self.key = cfg.get('SUPABASE_SECRET_KEY', '')
        from urllib.parse import urlsplit
        url = urlsplit(self.base)
        if (url.scheme != 'https' or not url.hostname or not url.hostname.endswith('.supabase.co')
                or url.path or url.query or url.fragment or url.username or url.port
                or not self.key.startswith('sb_secret_')):
            raise ValueError('shared_database_not_configured')
        self.opener = opener or urlopen

    def request(self, path, method='GET', value=None, prefer=None):
        headers = {'apikey': self.key, 'Content-Type': 'application/json', 'Accept-Encoding': 'gzip'}
        if prefer:
            headers['Prefer'] = prefer
        body = json.dumps(value, ensure_ascii=False).encode() if value is not None else None
        req = Request(self.base + '/rest/v1/' + path, data=body, method=method, headers=headers)
        with self.opener(req, timeout=30) as response:
            raw = response.read(20_000_001)
            compressed = response.headers.get('Content-Encoding') == 'gzip'
        if compressed:
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                raw = stream.read(20_000_001)
        if len(raw) > 20_000_000:
            raise ValueError('shared_response_too_large')
        return json.loads(raw) if raw else None

    def rows(self, table, parameters=None):
        rows = []
        for offset in range(0, 50000, 1000):
            query = dict(parameters or {}, limit=1000, offset=offset)
            batch = self.request(table + '?' + urlencode(query))
            if not isinstance(batch, list):
                raise ValueError('shared_response_invalid')
            rows.extend(batch)
            if len(batch) < 1000:
                return rows
        raise ValueError('shared_response_too_large')


class SharedNewsRepository(NewsRepository):
    def __init__(self, remote=None, **kwargs):
        super().__init__(**kwargs)
        self.remote = remote or SharedDatabase()
        self.lock = threading.Lock()
        self.cached = None
        self.cached_at = 0

    def candidate_rows(self):
        with self.lock:
            if self.cached is None or time.monotonic() - self.cached_at > 30:
                rows = self.remote.rows('news_articles', {'select': '*,news_memberships(category,source)',
                                                        'order': 'published_at.desc,url.asc'})
                flattened = []
                for row in rows:
                    for membership in row.get('news_memberships', []):
                        flattened.append(dict(row, category=membership['category'], source=membership['source']))
                self.cached, self.cached_at = flattened, time.monotonic()
            return [dict(row) for row in self.cached]

    def page(self, category=None, day=None, limit=20, offset=0, per_category_limit=None, categories=None):
        import tempfile
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'news.sqlite3'
                with closing(crawler.connect(path)) as db:
                    for row in self.candidate_rows():
                        db.execute('INSERT OR IGNORE INTO articles VALUES (?,?,?,?,?,?)',
                                   tuple(row[key] for key in ('url','title','description','published_at','first_seen','last_seen')))
                        db.execute('INSERT OR IGNORE INTO memberships VALUES (?,?,?)',
                                   (row['url'],row['category'],row['source']))
                    db.commit()
                return NewsRepository(path, self.config_path).page(category, day, limit, offset, per_category_limit, categories)
        except Exception:
            from fastapi import HTTPException
            raise HTTPException(503, detail={'code': 'shared_news_unavailable'}) from None


class SharedReviewStore(ReviewStore):
    def __init__(self, remote=None, namespace='fictional'):
        super().__init__()
        self.remote = remote or SharedDatabase()
        self.namespace = namespace

    def rows(self):
        rows = self.remote.rows('briefing_review_records', {'namespace': 'eq.' + self.namespace, 'order': 'id.asc'})
        return [(row['id'],row['record'],row['draft'],row['provenance'],row['decision'],row['approval']) for row in rows]


from .real_news import RealReviewStore


class SharedRealReviewStore(RealReviewStore):
    def __init__(self, remote=None):
        super().__init__()
        self.remote = remote or SharedDatabase()
        self.namespace = 'real'

    def rows(self):
        return SharedReviewStore.rows(self)


def publish_reviews(store, namespace, remote=None, ledger_path=None):
    remote = remote or SharedDatabase()
    path = Path(ledger_path or PROJECT / 'backend/.cache/shared-review-ledger.sqlite3')
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=20)) as ledger:
        ledger.execute('CREATE TABLE IF NOT EXISTS reviews (project TEXT,namespace TEXT,id TEXT,revision TEXT, PRIMARY KEY(project,namespace,id))')
        ledger.commit()
        known = dict(ledger.execute('SELECT id,revision FROM reviews WHERE project=? AND namespace=?',(remote.base,namespace)))
        existing = {row['id']: row for row in remote.rows('briefing_review_records', {'namespace':'eq.'+namespace,'order':'id.asc'})}
        uploaded, conflicts = 0, 0
        local_rows = store.rows()
        if any(row[4] == 'approved' for row in local_rows):
            store.briefing()
        for row in local_rows:
            article_id, record, draft, provenance, decision, approval = row
            store.review_document(article_id)
            revision = hashlib.sha256(json.dumps(list(row), ensure_ascii=False).encode()).hexdigest()
            current = existing.get(article_id)
            if current and current['revision'] == revision:
                pass
            elif current and known.get(article_id) == revision:
                continue
            else:
                payload = dict(namespace=namespace,id=article_id,record=record,draft=draft,provenance=provenance,
                               decision=decision,approval=approval,revision=revision,
                               updated_at=datetime.now(timezone.utc).isoformat())
                if current:
                    if known.get(article_id) != current['revision']:
                        conflicts += 1
                        continue
                    query = urlencode({'namespace':'eq.'+namespace,'id':'eq.'+article_id,'revision':'eq.'+current['revision']})
                    saved = remote.request('briefing_review_records?'+query,'PATCH',payload,'return=representation')
                    if not saved:
                        conflicts += 1
                        continue
                else:
                    remote.request('briefing_review_records','POST',payload)
                uploaded += 1
            with ledger:
                ledger.execute('INSERT OR REPLACE INTO reviews VALUES (?,?,?,?)',(remote.base,namespace,article_id,revision))
        return {'uploaded':uploaded,'conflicts':conflicts}


def sync_local_reviews():
    if not enabled():
        return {}
    results = {}
    from .real_news import RealReviewStore
    for namespace,store in [('fictional',ReviewStore()),('real',RealReviewStore())]:
        if store.path.exists():
            results[namespace] = publish_reviews(store,namespace)
    return results


def main():
    parser = argparse.ArgumentParser(description='Publish existing reviewed data without generating or approving summaries')
    parser.add_argument('--db',type=Path)
    parser.add_argument('--namespace',choices=['fictional','real'],default='fictional')
    args = parser.parse_args()
    try:
        if args.db:
            if args.namespace == 'real':
                from .real_news import RealReviewStore
                store = RealReviewStore(args.db)
            else:
                store = ReviewStore(args.db)
            result = publish_reviews(store,args.namespace)
        else:
            result = sync_local_reviews()
        print(json.dumps(result,ensure_ascii=False))
    except Exception:
        print(json.dumps({'error':'shared_review_sync_failed'}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
