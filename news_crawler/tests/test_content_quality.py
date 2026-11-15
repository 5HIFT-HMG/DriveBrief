import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import content_quality as quality
import news

TEXT = '가상 시청은 주민들이 이용할 수 있는 도서관 운영 시간을 확대한다고 밝혔습니다. 새 운영 시간은 다음 주부터 적용되며 기존 대출 서비스도 계속 제공합니다.'


class ContentQualityTests(unittest.TestCase):
    def test_closing_is_not_news_but_report_about_closing_is_news(self):
        for title in ['클로징','8뉴스 클로징','[클로징]','오프닝','방송 예고']:
            self.assertIn('non_news_title',quality.assess(title,TEXT)['reasons'])
        self.assertTrue(quality.assess('뉴욕증시 클로징 벨 행사 개최',TEXT)['eligible'])
        self.assertFalse(quality.assess('클로징','8시 뉴스 마칩니다.시청해 주신 여러분 고맙습니다.')['eligible'])
    def test_caption_lines_brackets_and_reporter_signoffs_are_removed(self):
        raw = '▲ 도서관 전경\n'+TEXT+' [사진=가상시청] 홍길동 기자의 보도입니다.'
        result=quality.assess('도서관 운영 확대',raw)
        self.assertTrue(result['eligible'])
        self.assertEqual(TEXT,result['description'])
        self.assertNotIn('▲',result['description'])
        for tail in ['보도에 윤나라 기자입니다.','홍길동 기자입니다.','홍길동 기자의 보도입니다.']:
            self.assertEqual(TEXT,quality.assess('운영 확대',TEXT+' '+tail)['description'])
    def test_merged_caption_is_not_guessed_and_later_complete_sentence_survives(self):
        result=quality.assess('운영 확대','▲ 시청전경시청이 운영한다고 밝혔습니다. '+TEXT)
        self.assertEqual(TEXT,result['description'])
        self.assertIn('caption_or_program_metadata',result['removed'])
    def test_truncated_fragments_are_not_completed(self):
        for tail in ['발표를 하던 중 누','확인했습니다…','일정은 […]','추가 사항은...','이후 방문객이 …누']:
            result=quality.assess('운영 확대',TEXT+' '+tail)
            self.assertEqual(TEXT,result['description'])
            self.assertIn('incomplete_sentence',result['removed'])
        self.assertFalse(quality.assess('운영 확대','확인되지 않은 설명이 중간에 잘린 누')['eligible'])
    def test_fifty_nonspace_characters_and_missing_data_gate_playback(self):
        for text in ['', '기사 설명입니다.', '가 '*49]:
            self.assertFalse(quality.assess('운영 확대',text)['eligible'])
        self.assertTrue(quality.assess('운영 확대',TEXT)['eligible'])
    def test_normal_quotes_brackets_numbers_negation_and_names_are_retained(self):
        text='가상 시청은 3.5%의 요금 인상안(검토 중)을 아직 시행하지 않는다고 밝혔습니다. 홍길동 기자는 “방문객 120명의 의견을 먼저 확인한다”고 전했습니다.'
        self.assertEqual(text,quality.assess('요금 인상 검토',text)['description'])
    def test_html_boundaries_and_no_space_sentence_endings(self):
        result=quality.assess('운영 확대','<p>▲ 도서관 사진</p><p>'+TEXT+'</p><p>보도에 홍길동 기자입니다.</p>')
        self.assertEqual(TEXT,result['description'])
        self.assertNotIn('고맙습니다',quality.assess('운영 확대',TEXT+'시청해 주신 여러분 고맙습니다.')['description'])
    def test_cleaning_is_idempotent(self):
        once=quality.assess('[영상] 운영 확대',TEXT+' 홍길동 기자입니다.')
        twice=quality.assess(once['title'],once['description'])
        self.assertEqual((once['title'],once['description']),(twice['title'],twice['description']))
    def test_audit_keeps_original_and_excludes_closing_from_candidates(self):
        db=news.connect(':memory:');self.addCleanup(db.close)
        db.execute('INSERT INTO articles VALUES (?,?,?,?,?,?)',('https://fixture.test/a','클로징',TEXT,'2026-11-14T00:00:00Z','first','last'))
        db.execute('INSERT INTO memberships VALUES (?,?,?)',('https://fixture.test/a','사회','fixture'))
        news.audit_content_quality(db)
        self.assertEqual(TEXT,db.execute('SELECT description FROM articles').fetchone()[0])
        self.assertEqual(0,db.execute('SELECT eligible FROM article_content_quality').fetchone()[0])
        self.assertEqual([],news.get_articles(db,all_history=True))
    def test_intern_byline_and_fused_photo_credit(self):
        for prefix in ['[서울=뉴시스]허준희 인턴 기자 = ', '[춘천=뉴시스]김가영 기자 = ']:
            self.assertEqual(TEXT,quality.assess('운영 확대',prefix+TEXT)['description'])
        raw='참가자가 기념 촬영을 하고 있다. 라이엇 게임즈 제공 '+TEXT
        self.assertEqual(TEXT,quality.assess('운영 확대',raw)['description'])
        normal='시청은 주민을 위한 정보 제공 서비스를 확대한다고 밝혔습니다. '+TEXT
        self.assertEqual(normal,quality.assess('운영 확대',normal)['description'])
    def test_news_reporting_a_closing_quote_is_not_a_signoff(self):
        text='방송사는 “시청해 주신 여러분 고맙습니다”라는 표현을 새 안내문에 사용했다고 밝혔습니다. '+TEXT
        self.assertEqual(text,quality.assess('방송사 안내문 변경',text)['description'])
    def test_email_copyright_and_reporter_tail_are_not_spoken(self):
        raw=TEXT+' 홍길동 기자 test@example.com © 가상신문 무단 전재 및 재배포 금지'
        self.assertEqual(TEXT,quality.assess('운영 확대',raw)['description'])
    def test_editorial_labels_at_title_edges_are_not_spoken(self):
        for label in ['오그랲','에디터픽','AFTER 8 SPECIAL','지식의 발견','이슈대담','뉴시스Pic','NEWSIS PIC']:
            with self.subTest(label=label):
                self.assertEqual('도서관 운영 확대',quality.assess('['+label+'] 도서관 운영 확대',TEXT)['title'])
                self.assertEqual('도서관 운영 확대',quality.assess('도서관 운영 확대 ['+label+']',TEXT)['title'])
        self.assertEqual('도서관 운영 확대',quality.spoken_title('[오그랲][에디터픽] 도서관 운영 확대 [뉴시스Pic]'))
    def test_unknown_fact_labels_and_brackets_inside_headline_remain(self):
        for title in ['[APBC] 대표팀 경기 개최','[한국갤럽] 조사 결과 발표','행사 [에디터픽] 관련 발언 논란']:
            self.assertEqual(title,quality.assess(title,TEXT)['title'])
        self.assertEqual('',quality.spoken_title('[에디터픽]'))
    def test_joint_reporter_names_are_removed_only_in_byline_position(self):
        for names in ['권창회 박윤서','류현주 최진석 하지현 정유진']:
            self.assertEqual(TEXT,quality.assess('운영 확대','[서울=뉴시스] '+names+' 기자 = '+TEXT)['description'])
        normal='권창회 박윤서 기자는 현장 설명에 참석했습니다. '+TEXT
        self.assertEqual(normal,quality.assess('운영 확대',normal)['description'])
