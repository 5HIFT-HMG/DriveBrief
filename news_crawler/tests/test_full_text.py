import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import news
import full_text


class FullTextTests(unittest.TestCase):
    def test_body_selector_excludes_scripts_and_navigation(self):
        body = '새로운 기술에 관한 기사 본문입니다. ' * 12
        html = f'<nav>광고</nav><div id="body"><p>{body}</p><script>tracking()</script></div><footer>관련 기사</footer>'
        text, method = full_text.extract_body(html, 'body')
        self.assertEqual(method, 'element_id')
        self.assertNotIn('tracking', text)
        self.assertNotIn('관련 기사', text)
        self.assertIn(body.strip(), text)

    def test_jsonld_graph_and_no_description_fallback(self):
        import json
        body = '검증용 기사 원문 문장입니다. ' * 15
        html = '<script type="application/ld+json">' + json.dumps({'@graph': [{'@type': 'NewsArticle', 'articleBody': body}]}) + '</script>'
        self.assertEqual(full_text.extract_body(html)[0], body.strip())
        with self.assertRaises(ValueError):
            full_text.extract_body('<meta name="description" content="RSS 설명"><p>목록</p>')

    def test_collection_reuses_db_skips_success_and_retries_failure(self):
        db = news.connect(':memory:')
        self.addCleanup(db.close)
        url = 'https://news.example.org/a'
        db.execute('INSERT INTO articles VALUES (?,?,?,?,?,?)', (url, '제목', 'RSS 설명', '2026-11-13', '', ''))
        policy = {'news.example.org': {'collection_allowed': True}}
        with patch('full_text.fetch_body', side_effect=OSError('network')):
            self.assertEqual(full_text.collect_bodies(db, policy), 0)
        with patch('full_text.fetch_body', return_value=('본문 ' * 100, 'json_ld')) as fetch:
            self.assertEqual(full_text.collect_bodies(db, policy), 1)
            self.assertEqual(full_text.collect_bodies(db, policy), 0)
            self.assertEqual(fetch.call_count, 1)
        self.assertEqual(db.execute('SELECT description FROM articles').fetchone()[0], 'RSS 설명')
        self.assertIsNone(db.execute('SELECT error FROM article_bodies').fetchone()[0])

    def test_unconfigured_host_never_fetched_and_redirect_checked(self):
        db = news.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('INSERT INTO articles VALUES (?,?,?,?,?,?)', ('https://example.org/a', '제목', '', '', '', ''))
        with patch('full_text.fetch_body') as fetch:
            self.assertEqual(full_text.collect_bodies(db, {}), 0)
            fetch.assert_not_called()
        for url in ['http://example.org/a', 'https://evil.org/a', 'https://example.org:8443/a']:
            with self.assertRaises(ValueError):
                full_text.checked_url(url, 'example.org')
