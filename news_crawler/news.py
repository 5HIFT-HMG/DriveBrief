#!/usr/bin/env python3
"""개인용 RSS 뉴스 수집기. Python 표준 라이브러리만 사용합니다."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time as dtime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import escape, unescape
from html.parser import HTMLParser
import json
import importlib.util
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import webbrowser
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
quality_spec = importlib.util.spec_from_file_location('drivebrief_content_quality', ROOT / 'content_quality.py')
content_quality = importlib.util.module_from_spec(quality_spec)
quality_spec.loader.exec_module(content_quality)
KST = timezone(timedelta(hours=9))
CATEGORIES = ['경제', '사회', '정치', 'IT', '스포츠']


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []; self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'template', 'noscript'):
            self.hidden += 1
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'template', 'noscript') and self.hidden:
            self.hidden -= 1
    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def clean(value):
    value = value or ''
    for _ in range(8):
        decoded = unescape(value)
        if decoded == value:
            break
        value = decoded
    parser = PlainText()
    parser.feed(value)
    parser.close()
    return re.sub(r'\s+', ' ', ' '.join(parser.parts)).strip()


def normalize_stored_text(db):
    changes = []
    for row in db.execute('SELECT url,title,description FROM articles'):
        title, description = clean(row['title']), clean(row['description'])
        if (title, description) != (row['title'], row['description']):
            changes.append((title, description, row['url']))
    with db:
        db.executemany('UPDATE articles SET title=?,description=? WHERE url=?', changes)
    return len(changes)


def audit_content_quality(db):
    db.execute("""CREATE TABLE IF NOT EXISTS article_content_quality (
        url TEXT PRIMARY KEY, version TEXT NOT NULL, eligible INTEGER NOT NULL,
        reasons TEXT NOT NULL, removed TEXT NOT NULL, clean_description TEXT NOT NULL)""")
    counts = {}
    for row in db.execute('SELECT url,title,description FROM articles').fetchall():
        result = content_quality.assess(row['title'], row['description'])
        for reason in result['reasons'] + result['removed']:
            counts[reason] = counts.get(reason,0)+1
        db.execute('INSERT OR REPLACE INTO article_content_quality VALUES (?,?,?,?,?,?)',
                   (row['url'], result['version'], int(result['eligible']), json.dumps(result['reasons']),
                    json.dumps(result['removed']), result['description']))
    db.commit()
    return counts


def safe_url(value):
    value = (value or '').strip()
    p = urlsplit(value)
    return value if p.scheme in ('http', 'https') and p.hostname and not p.username else ''


def canonical_url(value):
    p = urlsplit(value)
    tracking = {'plink', 'cooper', 'fbclid', 'gclid'}
    pairs = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                   if k.lower() not in tracking and not k.lower().startswith('utm_'))
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, urlencode(pairs), ''))


def parse_date(value):
    try:
        dt = parsedate_to_datetime(re.sub(r'([+-]\d{2}):(\d{2})$', r'\1\2', (value or '').strip()))
    except (ValueError, TypeError, IndexError):
        try:
            dt = datetime.fromisoformat((value or '').strip().replace('Z', '+00:00'))
        except ValueError:
            return None
    # 시간대 없는 날짜를 임의로 한국 시간으로 간주하지 않습니다.
    return dt.astimezone(KST) if dt.tzinfo else None


def parse_feed(payload):
    if b'<!DOCTYPE' in payload.upper() or b'<!ENTITY' in payload.upper():
        raise ValueError('외부 엔티티를 포함한 피드는 지원하지 않습니다.')
    root = ET.fromstring(payload)
    articles, skipped = [], 0
    for item in root.findall('.//item'):
        title = clean(item.findtext('title'))
        link = safe_url(item.findtext('link'))
        published = parse_date(item.findtext('pubDate') or item.findtext('{http://purl.org/dc/elements/1.1/}date'))
        if not title or not link or not published:
            skipped += 1
            continue
        articles.append({'title': title[:1000], 'url': canonical_url(link),
                         'description': clean(item.findtext('description'))[:1500],
                         'published_at': published.isoformat()})
    if not root.findall('.//channel'):
        raise ValueError('RSS 2.0 채널 형식이 아닙니다.')
    return articles, skipped


def connect(path):
    db = sqlite3.connect(path, timeout=20)
    db.row_factory = sqlite3.Row
    db.executescript('''
      CREATE TABLE IF NOT EXISTS articles (
        url TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
        published_at TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS memberships (
        url TEXT NOT NULL, category TEXT NOT NULL, source TEXT NOT NULL,
        PRIMARY KEY(url, category, source));
      CREATE TABLE IF NOT EXISTS feed_status (
        feed_url TEXT PRIMARY KEY, category TEXT NOT NULL, source TEXT NOT NULL,
        last_attempt TEXT, last_success TEXT, item_count INTEGER, skipped INTEGER, error TEXT);
    ''')
    return db


def fetch(feed):
    try:
        req = Request(feed['url'], headers={'User-Agent': 'MorningNews/1.0 (personal RSS reader)',
                                           'Accept': 'application/rss+xml, application/xml, text/xml'})
        with urlopen(req, timeout=15) as response:
            payload = response.read(4_000_001)
        if len(payload) > 4_000_000:
            raise ValueError('피드 크기가 4MB를 넘었습니다.')
        articles, skipped = parse_feed(payload)
        if not articles:
            raise ValueError('유효한 기사가 없습니다. 피드 형식 또는 날짜를 확인하세요.')
        return feed, articles, skipped, None
    except Exception as exc:
        return feed, [], 0, f'{type(exc).__name__}: {exc}'[:400]


def collect(db, feeds):
    normalize_stored_text(db)
    now = datetime.now(KST).isoformat()
    successes = 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(fetch, feeds))
    for feed, articles, skipped, error in results:
        old = db.execute('SELECT last_success FROM feed_status WHERE feed_url=?', (feed['url'],)).fetchone()
        last_success = old['last_success'] if old else None
        if not error:
            successes += 1
            last_success = now
            for a in articles:
                db.execute('''INSERT INTO articles VALUES (?,?,?,?,?,?)
                    ON CONFLICT(url) DO UPDATE SET title=excluded.title,
                    description=excluded.description, published_at=excluded.published_at,
                    last_seen=excluded.last_seen''',
                    (a['url'], a['title'], a['description'], a['published_at'], now, now))
                db.execute('INSERT OR IGNORE INTO memberships VALUES (?,?,?)',
                           (a['url'], feed['category'], feed['source']))
        db.execute('INSERT OR REPLACE INTO feed_status VALUES (?,?,?,?,?,?,?,?)',
                   (feed['url'], feed['category'], feed['source'], now, last_success,
                    len(articles), skipped, error))
        print(f"[{feed['category']}] {feed['source']}: " + (f'실패 — {error}' if error else f'{len(articles)}개 확인, {skipped}개 제외'), flush=True)
    db.commit()
    audit_content_quality(db)
    shared_spec = importlib.util.spec_from_file_location('drivebrief_shared_db', ROOT / 'shared_db.py')
    shared_db = importlib.util.module_from_spec(shared_spec)
    shared_spec.loader.exec_module(shared_db)
    shared_db.sync_after_collection(db)
    return successes


def day_bounds(day):
    start = datetime.combine(day, dtime.min, tzinfo=KST)
    return start.isoformat(), (start + timedelta(days=1)).isoformat()


def get_articles(db, day=None, *, all_history=False, category=None):
    condition, args = '', ()
    if day:
        condition, args = 'WHERE a.published_at >= ? AND a.published_at < ?', day_bounds(day)
    elif not all_history:
        condition, args = 'WHERE a.published_at >= ?', ((datetime.now(KST) - timedelta(days=30)).isoformat(),)
    if category is not None:
        selected_categories = [category] if isinstance(category, str) else list(category)
        if any(name not in CATEGORIES for name in selected_categories):
            raise ValueError('지원하지 않는 분야입니다.')
        if not selected_categories:
            return []
        condition += (' AND ' if condition else 'WHERE ') + 'm.category IN (' + ','.join('?' for _ in selected_categories) + ')'
        args += tuple(selected_categories)
    rows = db.execute('''SELECT a.*, m.category, m.source FROM articles a
        JOIN memberships m ON a.url=m.url ''' + condition + ' ORDER BY a.published_at DESC, a.url', args)
    output = []
    for row in rows:
        title, description = clean(row['title']), clean(row['description'])
        if content_quality.NON_NEWS_TITLE.fullmatch(title.strip('[] ')):
            continue
        output.append(dict(row, title=title, description=description))
    return output


def connect_read_only(path):
    """No CREATE/DDL or implicit empty DB creation on a missing file."""
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    return db


def get_candidates(db, day=None, category=None):
    """All stored history unless day is explicit; latest first, no keyword ranking.
    Dedup exact canonical URLs and whitespace/case-normalized titles, NOT semantic events.
    Keep all observed source/category memberships on the newest representative.
    """
    rows = get_articles(db, day, all_history=True, category=category)
    representatives, by_url, by_title = [], {}, {}
    for row in rows:
        if not safe_url(row['url']):
            continue
        url = canonical_url(row['url'])
        title = re.sub(r'\s+', ' ', unescape(row['title'])).strip().casefold()
        url_match, title_match = by_url.get(url), by_title.get(title)
        existing = url_match if url_match is not None else title_match
        if url_match is not None and title_match is not None and url_match is not title_match:
            # Join duplicate groups without leaving an alias title/URL in a second group.
            keep, drop = sorted((url_match, title_match), key=lambda item: representatives.index(item))
            for field in ('categories', 'sources'):
                keep[field] = list(dict.fromkeys(keep[field] + drop[field]))
            for mapping in (by_url, by_title):
                for key, value in list(mapping.items()):
                    if value is drop:
                        mapping[key] = keep
            representatives = [item for item in representatives if item is not drop]
            existing = keep
        if existing is None:
            existing = dict(row, url=url, categories=[], sources=[])
            representatives.append(existing)
        if row['category'] not in existing['categories']:
            existing['categories'].append(row['category'])
        if row['source'] not in existing['sources']:
            existing['sources'].append(row['source'])
        by_url[url] = existing
        by_title[title] = existing
    for row in representatives:
        row['categories'].sort()
        row['sources'].sort()
    return representatives


def candidate_page(db, *, day=None, category=None, limit=20, offset=0,
                   category_limits=None, per_category_limit=None):
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise ValueError('잘못된 조회 범위입니다.')
    limits = {name: 100 for name in CATEGORIES} if category_limits is None else category_limits
    if set(limits) != set(CATEGORIES) or any(type(v) is not int or not 1 <= v <= 1000 for v in limits.values()):
        raise ValueError('분야별 후보 설정을 확인하세요.')
    if per_category_limit is not None:
        if type(per_category_limit) is not int or not 0 <= per_category_limit <= 1000:
            raise ValueError('잘못된 분야별 후보 수입니다.')
        limits = {name: per_category_limit for name in CATEGORIES}
    rows = get_candidates(db, day, category)
    counts = {name: sum(name in row['categories'] for row in rows) for name in CATEGORIES}
    used = {name: 0 for name in CATEGORIES}
    selected = []
    for row in rows:
        eligible = [name for name in row['categories'] if name in limits and
                    (limits[name] == 0 or used[name] < limits[name])]
        if not eligible:
            continue
        selected.append(row)
        for name in row['categories']:
            if name in used:
                used[name] += 1
    return {'total_candidates': len(rows), 'available_count': len(selected),
            'category_counts': counts, 'category_limits': limits,
            'limit': limit, 'offset': offset, 'has_more': offset + limit < len(selected),
            'articles': selected[offset:offset + limit]}


def interest_score(article, keywords):
    # ASCII 단어는 경계를 확인하여 'AI'가 'said' 등에 매칭되지 않도록 합니다.
    def contains(text, key):
        if re.fullmatch(r'[a-zA-Z0-9 +.-]+', key):
            return bool(re.search(r'(?<![a-zA-Z0-9])' + re.escape(key) + r'(?![a-zA-Z0-9])', text, re.I))
        return key.casefold() in text.casefold()
    return sum(3 * contains(article['title'], k) + contains(article['description'], k) for k in keywords)


def select_articles(rows, keywords, limit):
    selected = {}
    for category in CATEGORIES:
        candidates = [dict(a, score=interest_score(a, keywords)) for a in rows if a['category'] == category]
        candidates.sort(key=lambda a: (a['score'], a['published_at']), reverse=True)
        seen, chosen = set(), []
        for a in candidates:
            key = re.sub(r'\W+', '', a['title']).casefold()
            if a['url'] in seen or key in seen:
                continue
            seen.update((key, a['url'])); chosen.append(a)
            if len(chosen) >= limit:
                break
        selected[category] = chosen
    return selected


def atomic_write(path, text):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(text, encoding='utf-8')
    temp.replace(path)


def render(db, config, day, output):
    rows = get_articles(db)
    statuses = [dict(r) for r in db.execute('SELECT * FROM feed_status ORDER BY category, source')]
    first = db.execute('SELECT MIN(first_seen) FROM articles').fetchone()[0]
    payload = {'articles': rows, 'categories': CATEGORIES, 'statuses': statuses,
               'stored_total': db.execute('SELECT COUNT(*) FROM articles').fetchone()[0],
               'keywords': config['keywords'], 'limit': config['limit'], 'day': day.isoformat(),
               'first_seen': first, 'generated_at': datetime.now(KST).isoformat()}
    # JSON을 script 태그에 안전하게 넣고 RSS 문자열은 브라우저에서 textContent로 표시합니다.
    data = json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    template = (ROOT / 'report.html').read_text(encoding='utf-8')
    atomic_write(output, template.replace('__NEWS_DATA__', data))
    selected = select_articles(get_articles(db, day), config['keywords'], config['limit'])
    day_rows = get_articles(db, day)
    atomic_write(output.with_suffix('.json'), json.dumps({'date': day.isoformat(),
                 'stored_total': payload['stored_total'], 'date_candidates': len({a['url'] for a in day_rows}),
                 'ranking': f"분야별 최대 {config['limit']}개, 키워드별 제목 일치 +3·설명 일치 +1, 동점이면 최신순, 분야 내 URL·정규화 제목 중복 제거",
                 'categories': selected}, ensure_ascii=False, indent=2))
    print(f'뉴스 화면: {output}', flush=True)


def main():
    parser = argparse.ArgumentParser(description='개인용 무료 RSS 아침 뉴스 수집기')
    parser.add_argument('--collect', action='store_true', help='RSS를 수집합니다')
    parser.add_argument('--full-text', action='store_true', help='설정한 출처의 기사 본문도 수집합니다')
    parser.add_argument('--watch', action='store_true', help='켜둔 동안 주기적으로 수집합니다')
    parser.add_argument('--interval', type=int, default=3600, help='수집 간격(초), 최소 300초')
    parser.add_argument('--date', type=date.fromisoformat, help='조회 날짜 YYYY-MM-DD, 기본 어제(한국 시간)')
    parser.add_argument('--open', action='store_true', help='뉴스 화면을 브라우저로 엽니다')
    parser.add_argument('--config', type=Path, default=ROOT / 'config.json')
    parser.add_argument('--db', type=Path, default=ROOT / 'news.sqlite3')
    args = parser.parse_args()
    if args.interval < 300:
        parser.error('수집 간격은 300초 이상으로 설정하세요.')
    config = json.loads(args.config.read_text(encoding='utf-8'))
    if not isinstance(config.get('keywords'), list) or not all(isinstance(k, str) and k.strip() for k in config['keywords']):
        parser.error('config.json의 keywords는 빈 문자열 없는 목록이어야 합니다.')
    config['keywords'] = list(dict.fromkeys(k.strip() for k in config['keywords']))
    if not isinstance(config.get('limit'), int) or not 1 <= config['limit'] <= 20:
        parser.error('분야별 개수 limit는 1~20으로 설정하세요.')
    feeds = config.get('feeds', [])
    if not feeds or any(f.get('category') not in CATEGORIES or not f.get('source') or not safe_url(f.get('url')) for f in feeds):
        parser.error('RSS 주소, 분야, 출처 설정을 확인하세요.')
    db = connect(args.db)
    output = ROOT / '내_뉴스.html'
    opened = False
    try:
        while True:
            if args.watch:
                updated = json.loads(args.config.read_text(encoding='utf-8'))
                next_feeds = updated.get('feeds', [])
                if (not next_feeds or any(f.get('category') not in CATEGORIES or not f.get('source')
                                         or not safe_url(f.get('url')) for f in next_feeds)):
                    raise ValueError('RSS 주소, 분야, 출처 설정을 확인하세요.')
                feeds = next_feeds
            successes = collect(db, feeds) if args.collect or args.watch else None
            if args.full_text:
                from full_text import collect_bodies
                collect_bodies(db, config.get('body_sources', {}))
            day = args.date or (datetime.now(KST).date() - timedelta(days=1))
            render(db, config, day, output)
            if args.open and not opened:
                webbrowser.open(output.as_uri()); opened = True
            if not args.watch:
                return 2 if successes == 0 else 0
            print(f'{args.interval // 60}분 뒤 다시 수집합니다. 종료: Ctrl+C. 컴퓨터가 잠들면 수집이 지연됩니다.', flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print('\n자동 수집을 종료했습니다. 저장된 기사는 남아 있습니다.')
        return 0
    finally:
        db.close()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f'실행 오류: {exc}', file=sys.stderr)
        sys.exit(1)
