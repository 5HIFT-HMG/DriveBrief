import importlib.util
import io
import json
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs, urlsplit
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('shared_db', Path(__file__).resolve().parents[1] / 'shared_db.py')
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)


class SharedDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE articles(url,title,description,published_at,first_seen,last_seen);
            CREATE TABLE memberships(url,category,source);
            INSERT INTO articles VALUES ('https://example.com/a','기사','내용','2026-11-13T00:00:00Z','2026-11-13T00:00:00Z','2026-11-13T00:00:00Z');
            INSERT INTO memberships VALUES ('https://example.com/a','사회','매체');''')
        self.now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
        self.config = {'SUPABASE_URL': 'https://fixture.supabase.co', 'SUPABASE_SECRET_KEY': 'sb_secret_fixture'}

    def test_payload_preserves_categories_and_only_uses_secret_as_api_header(self):
        def opener(request, timeout):
            if request.get_method() == 'DELETE':
                return io.BytesIO(b'')
            if request.get_method() == 'GET':
                return io.BytesIO(b'[]')
            self.assertEqual(request.full_url, 'https://fixture.supabase.co/rest/v1/rpc/sync_news')
            self.assertIsNone(request.get_header('Authorization'))
            self.assertEqual(request.get_header('Apikey'), 'sb_secret_fixture')
            payload = json.loads(request.data)
            self.assertEqual(payload['p_memberships'][0]['category'], '사회')
            self.assertNotIn('sb_secret_fixture', request.data.decode())
            self.assertEqual(timeout, 30)
            return io.BytesIO(b'1')
        self.assertEqual(shared.upload(self.db, self.config, opener, now=self.now)['uploaded'], 1)

    def test_missing_configuration_does_not_contact_network(self):
        self.assertEqual(shared.upload(self.db, {})['state'], 'not_configured')

    def test_untrusted_hosts_and_public_keys_are_rejected(self):
        for base in ['http://fixture.supabase.co', 'https://fixture.supabase.co.evil.test',
                     'https://fixture.supabase.co/path', 'https://user@fixture.supabase.co']:
            with self.subTest(base=base), self.assertRaises(ValueError):
                shared.upload(self.db, dict(self.config, SUPABASE_URL=base))
        with self.assertRaises(ValueError):
            shared.upload(self.db, dict(self.config, SUPABASE_SECRET_KEY='sb_publishable_fixture'))

    def test_failure_retains_local_articles_and_next_attempt_recovers(self):
        with patch.object(shared, 'upload', side_effect=OSError('credential must not be logged')):
            self.assertEqual(shared.sync_after_collection(self.db)['state'], 'failed')
        self.assertEqual(self.db.execute('SELECT count(*) FROM articles').fetchone()[0], 1)
        with patch.object(shared, 'upload', return_value={'state': 'synced', 'uploaded': 1}):
            shared.sync_after_collection(self.db)
        row = self.db.execute('SELECT * FROM cloud_sync_status').fetchone()
        self.assertEqual(row['state'], 'synced')
        self.assertIsNotNone(row['last_success_at'])

    def test_server_count_mismatch_is_failure(self):
        with self.assertRaises(ValueError):
            shared.upload(self.db, self.config, lambda *a, **k: io.BytesIO(b'0'))

    def test_http_diagnostics_do_not_reveal_server_body_or_credentials(self):
        from urllib.error import HTTPError
        error = HTTPError('https://example.com', 403, 'secret', {},
                          io.BytesIO(b'{"code":"42501","message":"sb_secret_private"}'))
        detail = shared.failure_detail(error)
        self.assertIn('HTTP 403 42501', detail)
        self.assertNotIn('sb_secret', detail)

    def transport(self, fail_batch=None):
        calls = []
        def opener(request, timeout):
            calls.append(request)
            if request.get_method() == 'POST':
                batch = json.loads(request.data)['p_articles']
                if fail_batch is not None and sum(r.get_method() == 'POST' for r in calls) == fail_batch:
                    raise OSError('offline')
                return io.BytesIO(str(len(batch)).encode())
            if request.get_method() == 'GET':
                return io.BytesIO(b'[]')
            return io.BytesIO(b'')
        return opener, calls

    def test_only_last_five_days_are_uploaded_and_local_history_is_preserved(self):
        old = (self.now - timedelta(days=6)).isoformat()
        self.db.execute('INSERT INTO articles VALUES (?,?,?,?,?,?)', ('https://example.com/old','old','old',old,old,old))
        opener, calls = self.transport()
        result = shared.upload(self.db, self.config, opener, now=self.now)
        self.assertEqual(result['eligible'], 1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM articles').fetchone()[0], 2)
        deleted = next(r for r in calls if r.get_method() == 'DELETE')
        cutoff = parse_qs(urlsplit(deleted.full_url).query)['published_at'][0]
        self.assertEqual(cutoff, 'lt.' + (self.now - timedelta(days=5)).isoformat())

    def test_second_sync_skips_unchanged_rows_but_retries_changed_titles(self):
        opener, calls = self.transport()
        self.assertEqual(shared.upload(self.db, self.config, opener, now=self.now)['uploaded'], 1)
        self.db.execute("UPDATE articles SET last_seen='2026-11-13T12:00:00Z'")
        self.assertEqual(shared.upload(self.db, self.config, opener, now=self.now)['uploaded'], 0)
        self.db.execute("UPDATE articles SET title='수정된 제목'")
        self.assertEqual(shared.upload(self.db, self.config, opener, now=self.now)['uploaded'], 1)
        self.assertEqual(sum(r.get_method() == 'POST' for r in calls), 2)

    def test_failed_batches_are_retried_without_resending_committed_batches(self):
        for i in range(150):
            self.db.execute('INSERT INTO articles SELECT ?,title,description,published_at,first_seen,last_seen FROM articles LIMIT 1',
                            (f'https://example.com/{i:03}',))
        opener, calls = self.transport(fail_batch=2)
        with self.assertRaises(OSError):
            shared.upload(self.db, self.config, opener, now=self.now)
        self.assertEqual(self.db.execute('SELECT count(*) FROM cloud_upload_ledger').fetchone()[0], 100)
        opener, calls = self.transport()
        result = shared.upload(self.db, self.config, opener, now=self.now)
        self.assertEqual(result['uploaded'], 51)
        self.assertEqual(len(json.loads(calls[0].data)['p_articles']), 51)

    def test_maximum_prefers_newest_articles_and_force_can_repair_cloud(self):
        for i in range(3):
            stamp = (self.now - timedelta(minutes=i)).isoformat()
            self.db.execute('INSERT INTO articles VALUES (?,?,?,?,?,?)', (f'https://example.com/new{i}',str(i),'',stamp,stamp,stamp))
        opener, calls = self.transport()
        result = shared.upload(self.db, self.config, opener, now=self.now, policy=(5, 2))
        self.assertEqual(result['eligible'], 2)
        batch = json.loads(calls[0].data)['p_articles']
        self.assertEqual([r['url'] for r in batch], ['https://example.com/new0','https://example.com/new1'])
        self.assertEqual(shared.upload(self.db, self.config, opener, now=self.now, policy=(5, 2), force=True)['uploaded'], 2)

    def test_membership_changes_trigger_upload_and_keys_do_not_share_ledger(self):
        opener, calls = self.transport()
        shared.upload(self.db, self.config, opener, now=self.now)
        self.db.execute("INSERT INTO memberships VALUES ('https://example.com/a','정치','매체')")
        self.assertEqual(shared.upload(self.db, self.config, opener, now=self.now)['uploaded'], 1)
        other = dict(self.config, SUPABASE_URL='https://other.supabase.co')
        self.assertEqual(shared.upload(self.db, other, opener, now=self.now)['uploaded'], 1)

    def test_cloud_overflow_is_deleted_without_removing_local_copy(self):
        calls = []
        pages = iter([[{'url': 'https://example.com/overflow'}], []])
        def opener(request, timeout):
            calls.append(request)
            if request.get_method() == 'POST':
                return io.BytesIO(b'1')
            if request.get_method() == 'GET':
                return io.BytesIO(json.dumps(next(pages)).encode())
            return io.BytesIO(b'')
        result = shared.upload(self.db, self.config, opener, now=self.now)
        self.assertEqual(result['purged'], 1)
        deletes = [r for r in calls if r.get_method() == 'DELETE']
        self.assertEqual(parse_qs(urlsplit(deletes[-1].full_url).query)['url'], ['eq.https://example.com/overflow'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM articles').fetchone()[0], 1)

    def test_boundary_and_future_articles_do_not_extend_retention(self):
        self.db.execute('DELETE FROM articles')
        for name, stamp in [('boundary',self.now-timedelta(days=5)),
                            ('old',self.now-timedelta(days=5,seconds=1)),
                            ('future',self.now+timedelta(days=1))]:
            self.db.execute('INSERT INTO articles VALUES (?,?,?,?,?,?)',
                            ('https://example.com/'+name,name,'',stamp.isoformat(),self.now.isoformat(),self.now.isoformat()))
        rows = shared.eligible_articles(self.db,5,10000,self.now)
        self.assertEqual([r['title'] for r in rows], ['boundary'])
