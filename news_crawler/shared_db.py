import json
import hashlib
from datetime import datetime, timedelta, timezone
import os
import re
import ssl
from urllib.error import HTTPError, URLError
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent


def settings():
    values = {}
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('\"\'')
    return {key: os.environ.get(key, values.get(key, '')) for key in
            ('SUPABASE_URL', 'SUPABASE_SECRET_KEY')}


def retention_policy():
    path = ROOT / 'config.json'
    config = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    policy = config.get('cloud_storage', {})
    days, maximum = policy.get('retention_days', 5), policy.get('max_articles', 10000)
    if type(days) is not int or not 1 <= days <= 30 or type(maximum) is not int or not 100 <= maximum <= 50000:
        raise ValueError('invalid_cloud_retention_policy')
    return days, maximum


def eligible_articles(db, days, maximum, now):
    cutoff = now - timedelta(days=days)
    articles = []
    for item in db.execute('SELECT * FROM articles'):
        row = dict(item)
        try:
            published = datetime.fromisoformat(row['published_at'].replace('Z', '+00:00'))
        except (ValueError, TypeError):
            continue
        if published.tzinfo and cutoff <= published <= now + timedelta(minutes=5):
            articles.append((published, row))
    articles.sort(key=lambda item: item[1]['url'])
    articles.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in articles[:maximum]]


def upload(db, config=None, opener=None, *, now=None, force=False, policy=None):
    config = settings() if config is None else config
    base, secret = config.get('SUPABASE_URL', '').rstrip('/'), config.get('SUPABASE_SECRET_KEY', '')
    if not base and not secret:
        return {'state': 'not_configured', 'uploaded': 0}
    parsed = urlsplit(base)
    if (parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.supabase.co')
            or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.port
            or not secret.startswith('sb_secret_')):
        raise ValueError('invalid_supabase_configuration')
    days, maximum = retention_policy() if policy is None else policy
    now = now or datetime.now(timezone.utc)
    rows = eligible_articles(db, days, maximum, now)
    urls = {row['url'] for row in rows}
    memberships = {}
    for item in db.execute('SELECT * FROM memberships ORDER BY url,category,source'):
        row = dict(item)
        if row['url'] in urls:
            memberships.setdefault(row['url'], []).append(row)
    db.execute('''CREATE TABLE IF NOT EXISTS cloud_upload_ledger (
        project TEXT NOT NULL,url TEXT NOT NULL,fingerprint TEXT NOT NULL,
        PRIMARY KEY(project,url))''')
    db.commit()
    cached = dict(db.execute('SELECT url,fingerprint FROM cloud_upload_ledger WHERE project=?', (base,)))
    fingerprints = {}
    changed = []
    for row in rows:
        stable = {key: value for key, value in row.items() if key != 'last_seen'}
        value = json.dumps([stable, memberships.get(row['url'], [])], sort_keys=True, ensure_ascii=False)
        fingerprint = hashlib.sha256(value.encode('utf-8')).hexdigest()
        fingerprints[row['url']] = fingerprint
        if force or cached.get(row['url']) != fingerprint:
            changed.append(row)

    def request(path, method='GET', payload=None, prefer=None):
        headers = {'apikey': secret, 'Content-Type': 'application/json'}
        if prefer:
            headers['Prefer'] = prefer
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None
        if data is not None and len(data) > 20_000_000:
            raise ValueError('supabase_payload_too_large')
        req = Request(base + '/rest/v1/' + path, data=data, method=method, headers=headers)
        with (opener or urlopen)(req, timeout=30) as response:
            raw = response.read(1_000_001)
            content_range = response.headers.get('Content-Range', '') if hasattr(response, 'headers') else ''
        if len(raw) > 1_000_000:
            raise ValueError('invalid_supabase_response')
        return (json.loads(raw) if raw else None), content_range

    uploaded = 0
    for start in range(0, len(changed), 100):
        batch = changed[start:start + 100]
        links = [m for row in batch for m in memberships.get(row['url'], [])]
        count, _ = request('rpc/sync_news', 'POST', {'p_articles': batch, 'p_memberships': links})
        if type(count) is not int or count != len(batch):
            raise ValueError('invalid_supabase_count')
        with db:
            db.executemany('INSERT OR REPLACE INTO cloud_upload_ledger VALUES (?,?,?)',
                           [(base, row['url'], fingerprints[row['url']]) for row in batch])
        uploaded += count

    cutoff = (now - timedelta(days=days)).isoformat()
    _, content_range = request('news_articles?' + urlencode({'published_at': 'lt.' + cutoff}),
                               'DELETE', prefer='count=exact,return=minimal')
    match = re.search(r'/(\d+)$', content_range)
    purged = int(match.group(1)) if match else 0
    previous_overflow = None
    while True:
        overflow, _ = request('news_articles?' + urlencode({'select': 'url',
            'order': 'published_at.desc,url.asc', 'offset': maximum, 'limit': 20}))
        if not isinstance(overflow, list):
            raise ValueError('invalid_supabase_response')
        if not overflow:
            break
        if overflow == previous_overflow:
            raise ValueError('invalid_supabase_response')
        previous_overflow = overflow
        for item in overflow:
            if not isinstance(item, dict) or not isinstance(item.get('url'), str):
                raise ValueError('invalid_supabase_response')
            request('news_articles?' + urlencode({'url': 'eq.' + item['url']}), 'DELETE')
            purged += 1
    with db:
        db.executemany('DELETE FROM cloud_upload_ledger WHERE project=? AND url=?',
                       [(base, url) for url in cached if url not in urls])
    return {'state': 'synced', 'uploaded': uploaded, 'eligible': len(rows), 'purged': purged,
            'retention_days': days, 'max_articles': maximum}


def failure_detail(error):
    if isinstance(error, HTTPError):
        code = ''
        try:
            data = json.loads(error.read(4096))
            value = data.get('code', '') if isinstance(data, dict) else ''
            if isinstance(value, str) and re.fullmatch(r'[A-Z0-9_]{1,24}', value):
                code = value
        except Exception:
            pass
        hints = {
            401: '서버 키가 유효하지 않거나 다른 프로젝트의 키입니다.',
            403: 'DB/API 접근 권한이 없습니다.',
            404: '프로젝트 주소 또는 sync_news 함수 등록을 확인하세요.',
            413: '전송 데이터가 서버 제한을 넘었습니다.',
            429: '요청 한도에 도달했습니다. 잠시 뒤 재시도하세요.'}
        return f"HTTP {error.code} {code}: " + hints.get(error.code, '서버가 요청을 거절했습니다. 응답 코드를 확인하세요.')
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, ssl.SSLCertVerificationError):
        return 'TLS_CERTIFICATE: Python 인증서 검증에 실패했습니다.'
    if isinstance(reason, ConnectionResetError):
        return 'CONNECTION_RESET: 서버 연결이 도중에 끊겼습니다.'
    if isinstance(reason, TimeoutError):
        return 'TIMEOUT: 서버 연결 시간이 초과됐습니다.'
    if isinstance(error, URLError):
        return 'NETWORK_' + type(reason).__name__ + ': DNS/인터넷 연결을 확인하세요.'
    if isinstance(error, ValueError):
        allowed = {'invalid_supabase_configuration', 'supabase_payload_too_large',
                   'invalid_supabase_response', 'invalid_supabase_count', 'invalid_cloud_retention_policy'}
        return str(error) if str(error) in allowed else 'INVALID_RESPONSE'
    return type(error).__name__


def locked_upload(db, force=False):
    if not any(settings().values()):
        return upload(db, force=True) if force else upload(db)
    import fcntl
    folder = ROOT / '.cache'
    folder.mkdir(exist_ok=True)
    with (folder / 'cloud-sync.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'state': 'busy', 'uploaded': 0}
        try:
            return upload(db, force=True) if force else upload(db)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def sync_after_collection(db, *, force=False):
    db.execute('CREATE TABLE IF NOT EXISTS cloud_sync_status (id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL, uploaded INTEGER NOT NULL, attempted_at TEXT NOT NULL, last_success_at TEXT)')
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    try:
        result = locked_upload(db, force=force)
    except Exception as error:
        detail = failure_detail(error)
        result = {'state': 'failed', 'uploaded': 0, 'error': detail}
        print('실패 원인: ' + detail, flush=True)
    db.execute('''INSERT INTO cloud_sync_status VALUES (1,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET state=excluded.state,uploaded=excluded.uploaded,
        attempted_at=excluded.attempted_at,
        last_success_at=coalesce(excluded.last_success_at,cloud_sync_status.last_success_at)''',
        (result['state'], result['uploaded'], now, now if result['state'] == 'synced' else None))
    db.commit()
    if result.get('eligible') is not None:
        print(f"공유 DB 정책: 최근 {result['retention_days']}일 / 최대 {result['max_articles']}개 · 전송 {result['uploaded']}개 · 정리 {result['purged']}개", flush=True)
    if result['state'] != 'not_configured':
        print(f"공유 DB: {result['state']} ({result['uploaded']}개)", flush=True)
    # The existing collection cycle triggers RSS publication; no new scheduler.
    # A temporary/test database must never start the real backend process.
    database = db.execute('PRAGMA database_list').fetchone()[2]
    if (result['state'] == 'synced' and database
            and Path(database).resolve() == (ROOT / 'news.sqlite3').resolve()
            and os.environ.get('DRIVEBRIEF_RSS_AUTO', '1') == '1'):
        import subprocess
        backend = ROOT.parent / 'backend'
        executable = backend / '.venv/bin/python'
        try:
            completed = subprocess.run([str(executable), '-B', '-m', 'drivebrief_api.rss_auto'],
                cwd=backend, capture_output=True, text=True, timeout=120, check=False)
            outcome = json.loads(completed.stdout)
            print('RSS 브리핑: ' + str(outcome.get('status', 'failed')), flush=True)
            result['briefing'] = outcome.get('status', 'failed')
        except Exception:
            result['briefing'] = 'refresh_failed_existing_publication_preserved'
            print('RSS 브리핑 갱신 실패 · 기존 게시 유지', flush=True)
    return result


if __name__ == '__main__':
    import sqlite3
    import sys
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--full', action='store_true', help='변경 여부와 무관하게 보관 대상 전체 재전송')
    args = parser.parse_args()
    db = sqlite3.connect(ROOT / 'news.sqlite3')
    db.row_factory = sqlite3.Row
    try:
        result = sync_after_collection(db, force=args.full)
        if result['state'] != 'synced':
            print('Supabase 설정과 SQL 적용 여부를 확인하세요. 로컬 데이터는 유지됩니다.')
        sys.exit(0 if result['state'] == 'synced' else 1)
    finally:
        db.close()
