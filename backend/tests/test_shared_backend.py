import copy
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs,urlsplit
from fastapi.testclient import TestClient
from drivebrief_api.app import create_app
from drivebrief_api.review import ReviewStore
from drivebrief_api.shared_backend import SharedReviewStore, SharedNewsRepository, publish_reviews
from drivebrief_summary.providers import MockProvider

class FakeRemote:
    base = 'https://fixture.supabase.co'
    def __init__(self): self.records = {}; self.news = []
    def rows(self, table, parameters=None):
        if table == 'news_articles': return copy.deepcopy(self.news)
        namespace = parameters['namespace'][3:]
        return [copy.deepcopy(v) for k,v in sorted(self.records.items()) if k[0] == namespace]
    def request(self, path, method='GET', value=None, prefer=None):
        if method == 'POST':
            key = (value['namespace'],value['id'])
            if key in self.records: raise ValueError('conflict')
            self.records[key] = copy.deepcopy(value)
            return None
        query = parse_qs(urlsplit(path).query)
        key = (query['namespace'][0][3:],query['id'][0][3:])
        old = self.records.get(key)
        if old is None or old['revision'] != query['revision'][0][3:]: return []
        self.records[key] = copy.deepcopy(value)
        return [value]

class SharedBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.local = ReviewStore(root/'review.sqlite3')
        self.records = json.loads((Path(__file__).parents[1]/'samples/pipeline_articles.json').read_text())
        self.local.generate(self.records,MockProvider(),root/'cache.sqlite3')
        self.remote = FakeRemote(); self.ledger = root/'ledger.sqlite3'
    def publish(self): return publish_reviews(self.local,'fictional',self.remote,self.ledger)
    def approve(self):
        article_id = self.records[0]['article']['id']; doc = self.local.review_document(article_id)
        self.local.decide(article_id,'fixture-reviewer','approved',doc['revision'])
        return article_id
    def test_drafts_are_not_playable_and_approved_plan_uses_shared_data(self):
        self.assertEqual(self.publish()['uploaded'],3)
        reader = SharedReviewStore(self.remote)
        self.assertEqual(reader.briefing()['articles'],[])
        article_id = self.approve(); self.assertEqual(self.publish()['uploaded'],1)
        self.assertEqual(reader.briefing()['articles'][0]['article_id'],article_id)
        response = TestClient(create_app(review_store=reader)).get('/v1/briefings/plan?length=중간')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['articles'][0]['article_id'],article_id)
        self.assertNotIn('source_spans',response.text); self.assertNotIn('fixture-reviewer',response.text)
    def test_revocation_is_shared_without_changing_existing_review_logic(self):
        article_id = self.approve(); self.publish(); doc = self.local.review_document(article_id)
        self.local.decide(article_id,'fixture','rejected',doc['revision'])
        self.assertEqual(self.publish()['uploaded'],1)
        self.assertEqual(SharedReviewStore(self.remote).briefing()['articles'],[])
    def test_remote_changes_are_not_overwritten_by_stale_local_review(self):
        self.publish(); article_id = self.approve()
        self.remote.records[('fictional',article_id)]['revision'] = 'other-reviewer-change'
        self.assertEqual(self.publish()['conflicts'],1)
        self.assertEqual(self.remote.records[('fictional',article_id)]['decision'],'needs_review')
    def test_identical_rows_are_not_rewritten_and_cloud_deletion_can_be_repaired(self):
        self.publish(); self.assertEqual(self.publish()['uploaded'],0)
        key = next(iter(self.remote.records)); del self.remote.records[key]
        self.assertEqual(self.publish()['uploaded'],1)
    def test_cloud_news_is_used_by_existing_candidate_ranker(self):
        self.remote.news = [{'url':'https://example.com/new','title':'합성 기사','description':'테스트 설명',
            'published_at':'2026-11-13T12:00:00+00:00','first_seen':'2026-11-13T12:00:00+00:00',
            'last_seen':'2026-11-13T12:00:00+00:00','news_memberships':[{'category':'사회','source':'테스트'}]}]
        repo = SharedNewsRepository(self.remote)
        self.assertEqual(repo.page(category='사회').articles[0].title,'합성 기사')
        response = TestClient(create_app(news_repository=repo,review_store=self.local)).get('/v1/news/candidates?categories=사회')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['articles'][0]['categories'],['사회'])
