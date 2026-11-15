from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets
import sqlite3


def select_articles(articles, categories, length, budget_seconds=None):
    counts = {'short': 1, 'medium': 2, 'long': 3}
    if length not in counts or not categories or not set(categories) <= {'경제', '사회', '정치', 'IT', '스포츠'}:
        raise ValueError('invalid_preferences')
    if budget_seconds is not None and not 30 <= budget_seconds <= 7200:
        raise ValueError('invalid_budget')
    candidates = sorted(articles, key=lambda a: (a['published_at'], a['article_id']), reverse=True)
    selected, seen, total = [], set(), 0
    for article in candidates:
        if article.get('summary_length', length) != length:
            continue
        if article['category'] not in categories or article.get('validation', {}).get('approved') is not True:
            continue
        key = re.sub(r'\W+', '', article['title']).casefold()
        if not key or key in seen:
            continue
        sentences = article['tts_sentences'][:counts[length]]
        if not sentences:
            continue
        seconds = max(1, round(sum(len(s) for s in sentences) / 5 + len(sentences)))
        if budget_seconds is not None and total + seconds > budget_seconds:
            continue
        seen.add(key)
        selected.append(dict(article, tts_sentences=sentences, estimated_seconds=seconds))
        total += seconds
        if len(selected) == 10:
            break
    return selected, total


class SessionStore:
    def __init__(self, path):
        self.path = Path(path)

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(self.path), timeout=20)
        db.execute('''CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL, preferences TEXT NOT NULL, articles TEXT NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS playback_events (
            session_id TEXT NOT NULL, event_id TEXT NOT NULL, article_id TEXT NOT NULL,
            sequence INTEGER NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(session_id,event_id), UNIQUE(session_id,article_id,sequence))''')
        return db

    def create(self, catalog, categories, length, budget_seconds=None):
        articles, total = select_articles(catalog, categories, length, budget_seconds)
        session_id = secrets.token_urlsafe(32)
        prefs = {'categories': categories, 'length': length, 'budget_seconds': budget_seconds}
        with closing(self.connect()) as db, db:
            db.execute('INSERT INTO sessions VALUES (?,?,?,?)',
                       (session_id, datetime.now(timezone.utc).isoformat(), json.dumps(prefs),
                        json.dumps(articles, ensure_ascii=False)))
        return {'schema_version': 'session-briefing-v1', 'session_id': session_id,
                'length': length, 'estimated_seconds': total, 'duration_is_estimate': True,
                'playback_requires_user_action': True, 'event_dedup_status': 'normalized_title_only',
                'selection_method': 'category_then_latest', 'articles': articles}

    def get(self, db, session_id):
        row = db.execute('SELECT created_at,preferences,articles FROM sessions WHERE id=?', (session_id,)).fetchone()
        if row is None:
            raise LookupError('session_missing')
        return row[0], json.loads(row[1]), json.loads(row[2])

    def record(self, session_id, event):
        if set(event) != {'event_id', 'article_id', 'sequence', 'state', 'completed_sentences', 'bookmarked'}:
            raise ValueError('invalid_event')
        if (not isinstance(event['event_id'], str) or not 1 <= len(event['event_id']) <= 100
                or type(event['sequence']) is not int or event['sequence'] < 0
                or type(event['completed_sentences']) is not int or event['completed_sentences'] < 0
                or type(event['bookmarked']) is not bool
                or event['state'] not in ('unplayed', 'playing', 'interrupted', 'completed')):
            raise ValueError('invalid_event')
        payload = json.dumps(event, sort_keys=True)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            _, _, articles = self.get(db, session_id)
            article = next((a for a in articles if a['article_id'] == event['article_id']), None)
            if article is None:
                raise ValueError('article_not_in_session')
            count = len(article['tts_sentences'])
            if (event['completed_sentences'] > count or
                    (event['state'] == 'completed' and event['completed_sentences'] != count) or
                    (event['state'] == 'unplayed' and event['completed_sentences'] != 0)):
                raise ValueError('invalid_progress')
            old = db.execute('SELECT payload FROM playback_events WHERE session_id=? AND event_id=?',
                             (session_id, event['event_id'])).fetchone()
            if old:
                if old[0] != payload:
                    raise ValueError('event_id_conflict')
                return {'accepted': True, 'duplicate': True}
            last = db.execute('''SELECT sequence,payload FROM playback_events
                WHERE session_id=? AND article_id=? ORDER BY sequence DESC LIMIT 1''',
                (session_id, event['article_id'])).fetchone()
            if last:
                previous = json.loads(last[1])
                if event['sequence'] <= last[0] or event['completed_sentences'] < previous['completed_sentences']:
                    raise ValueError('stale_progress')
                if previous['state'] != 'unplayed' and event['state'] == 'unplayed':
                    raise ValueError('stale_progress')
                if previous['state'] == 'completed' and event['state'] != 'completed':
                    raise ValueError('completed_article')
            db.execute('INSERT INTO playback_events VALUES (?,?,?,?,?)',
                       (session_id, event['event_id'], event['article_id'], event['sequence'], payload))
        return {'accepted': True, 'duplicate': False}

    def onepaper(self, session_id):
        with closing(self.connect()) as db:
            created, prefs, articles = self.get(db, session_id)
            events = db.execute('SELECT article_id,sequence,payload FROM playback_events WHERE session_id=? ORDER BY sequence',
                                (session_id,)).fetchall()
        latest = {article_id: json.loads(payload) for article_id, _, payload in events}
        output = []
        for article in articles:
            state = latest.get(article['article_id'], {})
            completed = state.get('state') == 'completed'
            progress = state.get('completed_sentences', 0)
            output.append({k: article[k] for k in ('article_id', 'title', 'source', 'source_url', 'published_at', 'one_line', 'detail', 'mock')})
            output[-1].update(state='completed' if completed else 'interrupted' if state.get('state') in ('playing', 'interrupted') else 'unplayed',
                              completed_sentences=progress, total_sentences=len(article['tts_sentences']),
                              bookmarked=state.get('bookmarked', False),
                              summary_scope='full_article',
                              listening_basis='client_playback_report',
                              summary_notice='기사 전체 내용의 요약이며 실제 청취한 부분만의 요약이 아닙니다.')
        return {'schema_version': 'onepaper-v1', 'session_id': session_id, 'created_at': created,
                'preferences': prefs, 'articles': output}


def session_router(catalog, store):
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel, ConfigDict, Field
    from typing import List, Literal, Optional

    class BriefingRequest(BaseModel):
        model_config = ConfigDict(extra='forbid', strict=True)
        categories: List[Literal['경제', '사회', '정치', 'IT', '스포츠']] = Field(min_length=1, max_length=5)
        length: Literal['short', 'medium', 'long'] = 'medium'
        budget_seconds: Optional[int] = Field(default=None, ge=30, le=7200)

    class PlaybackEvent(BaseModel):
        model_config = ConfigDict(extra='forbid', strict=True)
        event_id: str = Field(min_length=1, max_length=100)
        article_id: str = Field(min_length=1, max_length=100)
        sequence: int = Field(ge=0)
        state: Literal['unplayed', 'playing', 'interrupted', 'completed']
        completed_sentences: int = Field(ge=0)
        bookmarked: bool = False

    router = APIRouter()

    @router.post('/v1/briefings', status_code=201)
    def create_briefing(request: BriefingRequest):
        try:
            return store.create(catalog(), request.categories, request.length, request.budget_seconds)
        except (ValueError, OSError, sqlite3.Error):
            raise HTTPException(503, detail={'code': 'briefing_data_unavailable'}) from None

    @router.post('/v1/sessions/{session_id}/events')
    def record_event(session_id: str, event: PlaybackEvent):
        try:
            return store.record(session_id, event.model_dump())
        except LookupError:
            raise HTTPException(404, detail={'code': 'session_missing'}) from None
        except ValueError as exc:
            raise HTTPException(409, detail={'code': str(exc)}) from None
        except (OSError, sqlite3.Error):
            raise HTTPException(503, detail={'code': 'session_store_unavailable'}) from None

    @router.get('/v1/sessions/{session_id}/onepaper')
    def onepaper(session_id: str):
        try:
            return store.onepaper(session_id)
        except LookupError:
            raise HTTPException(404, detail={'code': 'session_missing'}) from None
        except (OSError, ValueError, sqlite3.Error):
            raise HTTPException(503, detail={'code': 'session_store_unavailable'}) from None

    return router
