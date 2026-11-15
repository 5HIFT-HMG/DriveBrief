import copy
import unittest
from unittest.mock import patch
from drivebrief_api import rss_auto as rss
from tests.test_rss_auto import NOW, rows, Remote


class RssQualityIntegrationTests(unittest.TestCase):
    def test_filters_closing_and_short_data_before_ranking(self):
        data=rows(4)
        data[0]['title']='클로징'
        data[1]['description']='소식입니다.'
        data[2]['description']='끝나지 않은 기사 설명이 누'
        with patch.object(rss,'rank_groups',wraps=rss.rank_groups) as rank:
            docs=rss.build(data,now=NOW)
        self.assertEqual(1,len(docs['길게']['articles']))
        self.assertEqual(data[3]['url'],docs['길게']['articles'][0]['source_url'])
        self.assertTrue(rank.called)
    def test_only_clean_complete_source_spans_are_published(self):
        data=rows(1);original=data[0]['description']
        data[0]['description']='▲ 사진 설명\n[서울=뉴시스]김가영 인턴 기자 = '+original+' 홍길동 기자입니다. 추가 소식은 …누'
        docs=rss.build(data,now=NOW)
        article=docs['길게']['articles'][0]
        self.assertEqual(original,article['detail'])
        self.assertNotRegex(' '.join(article['tts_sentences']),r'▲|인턴 기자|홍길동|…누')
        rss.checked_catalog(docs)
    def test_legacy_dirty_publication_is_not_reused(self):
        docs=rss.build(rows(),now=NOW)
        bad=copy.deepcopy(docs)
        for doc in bad.values():doc['articles'][0]['detail']='클로징입니다.'
        with self.assertRaises(ValueError):rss.checked_catalog(bad)
    def test_zero_safe_articles_publishes_empty_catalog_not_dirty_fallback(self):
        remote=Remote();rss.refresh(remote,now=NOW)
        for row in remote.news:row['title']='클로징'
        result=rss.refresh(remote,now=NOW)
        self.assertEqual('published',result['status'])
        self.assertEqual(0,result['articles'])
        self.assertTrue(all(not row['briefing']['articles'] for row in remote.current))
    def test_editorial_labels_are_removed_from_title_and_all_spoken_outputs(self):
        data=rows(2)
        data[0]['title']='[에디터픽] '+data[0]['title']
        data[1]['title']=data[1]['title']+' [뉴시스Pic]'
        docs=rss.build(data,now=NOW)
        for doc in docs.values():
            for article in doc['articles']:
                self.assertNotRegex(article['title']+' '+article['one_line']+' '+' '.join(article['tts_sentences']),r'에디터픽|뉴시스Pic')
        self.assertEqual({r['url'] for r in data},{a['source_url'] for a in docs['길게']['articles']})
        rss.checked_catalog(docs)
