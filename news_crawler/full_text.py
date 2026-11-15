import hashlib
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener


class ArticleParser(HTMLParser):
    def __init__(self, element_id=None):
        super().__init__(convert_charrefs=True)
        self.element_id = element_id
        self.stack = []
        self.parts = []
        self.scripts = []
        self.script = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        active = any(item[1] for item in self.stack)
        active = active or bool(self.element_id and attrs.get('id') == self.element_id)
        blocked = tag in ('script', 'style', 'nav', 'aside', 'button') or any(item[2] for item in self.stack)
        if tag == 'script' and attrs.get('type', '').lower() == 'application/ld+json':
            self.script = []
        if tag not in ('br', 'hr', 'img', 'input', 'meta', 'link', 'source', 'wbr'):
            self.stack.append((tag, active, blocked))
        elif tag == 'br' and active and not blocked:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag == 'script' and self.script is not None:
            self.scripts.append(''.join(self.script))
            self.script = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                if self.stack[i][1] and tag in ('p', 'div', 'section'):
                    self.parts.append('\n')
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)
        if self.stack and self.stack[-1][1] and not self.stack[-1][2]:
            self.parts.append(data)


def extract_body(html, element_id=None):
    parser = ArticleParser(element_id)
    parser.feed(html)
    text = ''.join(parser.parts)
    method = 'element_id'
    if not text.strip():
        candidates = []

        def visit(value):
            if isinstance(value, list):
                for item in value:
                    visit(item)
            elif isinstance(value, dict):
                kinds = value.get('@type', [])
                kinds = [kinds] if isinstance(kinds, str) else kinds
                if any(kind in ('NewsArticle', 'Article', 'ReportageNewsArticle') for kind in kinds):
                    if isinstance(value.get('articleBody'), str):
                        candidates.append(value['articleBody'])
                for item in value.values():
                    if isinstance(item, (dict, list)):
                        visit(item)

        for script in parser.scripts:
            try:
                visit(json.loads(script))
            except ValueError:
                continue
        text = max(candidates, key=len, default='')
        method = 'json_ld'
    text = '\n'.join(re.sub(r'\s+', ' ', line).strip() for line in text.splitlines() if line.strip())
    if len(text) < 100:
        raise ValueError('article_body_missing_or_too_short')
    return text, method


def checked_url(url, hostname):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('article_host_not_allowed')
    return url


class SameHostRedirect(HTTPRedirectHandler):
    def __init__(self, hostname):
        self.hostname = hostname

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url(newurl, self.hostname)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_body(url, policy):
    hostname = urlsplit(url).hostname
    checked_url(url, hostname)
    req = Request(url, headers={'User-Agent': 'DriveBrief/1.0', 'Accept': 'text/html'})
    with build_opener(SameHostRedirect(hostname)).open(req, timeout=15) as response:
        if response.headers.get_content_type() != 'text/html':
            raise ValueError('unexpected_content_type')
        raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise ValueError('article_too_large')
        html = raw.decode(response.headers.get_content_charset() or 'utf-8', errors='strict')
    return extract_body(html, policy.get('element_id'))


def collect_bodies(db, sources, limit=20):
    db.execute('''CREATE TABLE IF NOT EXISTS article_bodies (
        url TEXT PRIMARY KEY, body TEXT NOT NULL, body_sha256 TEXT NOT NULL,
        extraction_method TEXT, last_attempt TEXT, last_success TEXT, error TEXT)''')
    rows = db.execute('''SELECT a.url FROM articles a LEFT JOIN article_bodies b ON a.url=b.url
        WHERE b.url IS NULL OR b.error IS NOT NULL ORDER BY a.published_at DESC''').fetchall()
    attempted = succeeded = 0
    for row in rows:
        url = row['url']
        policy = sources.get(urlsplit(url).hostname, {})
        if policy.get('collection_allowed') is not True:
            continue
        if attempted >= limit:
            break
        attempted += 1
        now = datetime.now(timezone.utc).isoformat()
        try:
            body, method = fetch_body(url, policy)
            db.execute('''INSERT INTO article_bodies VALUES (?,?,?,?,?,?,NULL)
                ON CONFLICT(url) DO UPDATE SET body=excluded.body, body_sha256=excluded.body_sha256,
                extraction_method=excluded.extraction_method, last_attempt=excluded.last_attempt,
                last_success=excluded.last_success, error=NULL''',
                (url, body, hashlib.sha256(body.encode()).hexdigest(), method, now, now))
            succeeded += 1
        except (OSError, ValueError) as exc:
            db.execute('''INSERT INTO article_bodies VALUES (?, '', '', NULL, ?, NULL, ?)
                ON CONFLICT(url) DO UPDATE SET last_attempt=excluded.last_attempt, error=excluded.error''',
                (url, now, type(exc).__name__))
        db.commit()
    print(f'기사 본문: {attempted}건 시도, {succeeded}건 저장', flush=True)
    return succeeded
