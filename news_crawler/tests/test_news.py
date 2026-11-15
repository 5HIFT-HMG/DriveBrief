import sys
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import news


class NewsTests(unittest.TestCase):
    def test_rfc_date_with_colon_timezone_is_aware(self):
        self.assertEqual(news.parse_date('Sat, 14 Nov 2026 14:44:16 +09:00').isoformat(),
                         '2026-11-14T14:44:16+09:00')
        self.assertEqual(news.parse_date('Sat, 14 Nov 2026 00:44:16 -05:00').isoformat(),
                         '2026-11-14T14:44:16+09:00')
        self.assertIsNone(news.parse_date('Sat, 14 Nov 2026 14:44:16'))

    def test_nested_html_entities_and_hidden_content_become_plain_text(self):
        value = '&amp;lt;p&amp;gt;첫 문단&amp;lt;/p&amp;gt;&amp;lt;p&amp;gt;둘째&amp;amp;nbsp;문단&amp;lt;/p&amp;gt;'
        self.assertEqual(news.clean(value), '첫 문단 둘째 문단')
        self.assertEqual(news.clean('<style>.ad{display:none}</style><script>alert(1)</script><p>기사 <b>설명</b></p>'), '기사 설명')
        self.assertEqual(news.clean('A &amp; B · 가격 3 < 5'), 'A & B · 가격 3 < 5')

    def test_existing_text_normalization_preserves_metadata_and_is_idempotent(self):
        db = news.connect(':memory:')
        try:
            original = ('https://example.com/a', '&lt;b&gt;AI 소식&lt;/b&gt;', '&lt;p&gt;기사 설명&lt;/p&gt;',
                        '2026-11-13T09:00:00+09:00', 'first', 'last')
            db.execute('INSERT INTO articles VALUES (?,?,?,?,?,?)', original)
            db.execute('INSERT INTO memberships VALUES (?,?,?)', (original[0], 'IT', 'fixture'))
            db.commit()
            self.assertEqual(news.get_articles(db, all_history=True)[0]['description'], '기사 설명')
            self.assertEqual(news.normalize_stored_text(db), 1)
            row = db.execute('SELECT * FROM articles').fetchone()
            self.assertEqual(tuple(row), (original[0], 'AI 소식', '기사 설명', *original[3:]))
            self.assertEqual(news.normalize_stored_text(db), 0)
            self.assertEqual(db.execute('SELECT count(*) FROM memberships').fetchone()[0], 1)
        finally:
            db.close()

    def test_watch_reloads_changed_feed_list_without_restarting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / 'config.json'
            first = {'category': 'IT', 'source': 'first', 'url': 'https://example.com/first'}
            second = {'category': '사회', 'source': 'second', 'url': 'https://example.com/second'}
            config = {'keywords': ['AI'], 'limit': 5, 'feeds': [first]}
            config_path.write_text(json.dumps(config))
            seen = []
            def collect(db, feeds):
                seen.append(list(feeds))
                if len(seen) == 2:
                    raise KeyboardInterrupt
                config['feeds'].append(second)
                config_path.write_text(json.dumps(config))
                return 1
            with patch.object(sys, 'argv', ['news.py', '--watch', '--config', str(config_path), '--db', str(root / 'news.sqlite3')]):
                with patch.object(news, 'collect', side_effect=collect), patch.object(news, 'render'), patch.object(news.time, 'sleep'):
                    self.assertEqual(news.main(), 0)
            self.assertEqual(seen, [[first], [first, second]])

    def test_rss_cleaning_dates_and_invalid_items(self):
        payload = '''<rss><channel><item><title>&lt;b&gt;AI 소식&lt;/b&gt;</title>
        <link>https://example.com/a?utm_source=rss&amp;id=7</link>
        <description>&lt;img src="https://tracker.test/pixel"/&gt;새 소식</description>
        <pubDate>Thu, 05 Nov 2026 15:00:00 GMT</pubDate></item>
        <item><title>누락</title><link>https://example.com/b</link></item>
        <item><title>위험 링크</title><link>javascript:alert(1)</link>
        <pubDate>Fri, 06 Nov 2026 09:00:00 +0900</pubDate></item></channel></rss>'''.encode()
        articles, skipped = news.parse_feed(payload)
        self.assertEqual(skipped, 2)
        self.assertEqual(articles[0]['title'], 'AI 소식')
        self.assertEqual(articles[0]['description'], '새 소식')
        self.assertEqual(articles[0]['url'], 'https://example.com/a?id=7')
        self.assertEqual(articles[0]['published_at'], '2026-11-06T00:00:00+09:00')

    def test_unknown_time_zone_is_not_invented(self):
        self.assertIsNone(news.parse_date('2026-11-06T09:00:00'))
        self.assertIsNone(news.parse_date('not a date'))

    def test_entity_feed_rejected(self):
        with self.assertRaises(ValueError):
            news.parse_feed(b'<!DOCTYPE rss [<!ENTITY x "test">]><rss><channel/></rss>')

    def test_exact_korean_day_boundaries_and_repeat_collection(self):
        feed = {'url': 'https://example.com/rss', 'source': '시험', 'category': 'IT'}
        articles = [dict(title='기사 '+str(i), url=f'https://example.com/{i}', description='', published_at=dt)
                    for i, dt in enumerate(['2026-11-05T23:59:59+09:00', '2026-11-06T00:00:00+09:00',
                                            '2026-11-06T23:59:59+09:00', '2026-11-07T00:00:00+09:00'])]
        db = news.connect(':memory:')
        try:
            with patch('news.fetch', return_value=(feed, articles, 0, None)):
                news.collect(db, [feed]); news.collect(db, [feed])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM articles').fetchone()[0], 4)
            self.assertEqual(len(news.get_articles(db, date(2026, 11, 6))), 2)
            with patch('news.fetch', return_value=(feed, [], 0, '접속 실패')):
                self.assertEqual(news.collect(db, [feed]), 0)
            status = db.execute('SELECT * FROM feed_status').fetchone()
            self.assertIsNotNone(status['last_success'])
            self.assertEqual(status['error'], '접속 실패')
            self.assertEqual(len(news.get_articles(db, date(2026, 11, 6))), 2)
        finally:
            db.close()

    def test_keyword_ranking_dedup_and_fewer_than_five(self):
        def article(title, url, published):
            return dict(title=title, url=url, description='', category='IT', published_at=published)
        rows = [article('새로운 일반 뉴스', 'https://a/1', '2026-11-06T23:00:00+09:00'),
                article('AI 뉴스', 'https://a/2', '2026-11-06T10:00:00+09:00'),
                article('AI  뉴스!', 'https://a/3', '2026-11-06T09:00:00+09:00')]
        selected = news.select_articles(rows, ['AI'], 5)
        self.assertEqual(len(selected['IT']), 2)
        self.assertEqual(selected['IT'][0]['url'], 'https://a/2')
        self.assertEqual(selected['경제'], [])
        self.assertEqual(news.interest_score(dict(title='said', description=''), ['AI']), 0)
        self.assertEqual(news.select_articles(rows, [], 5)['IT'][0]['url'], 'https://a/1')


if __name__ == '__main__':
    unittest.main()
