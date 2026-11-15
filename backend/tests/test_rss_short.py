import copy
import unittest
from unittest.mock import patch
from drivebrief_api import rss_auto as rss
from tests.test_rss_auto import rows,NOW


class ShortRssTests(unittest.TestCase):
    def test_first_complete_sentence_is_exact_and_preserves_attribution(self):
        title="가상 행사 참가 인원 발표"
        first='시청은 "참가자는 자체 추산 3만 명이며 아직 확정되지 않았다"고 밝혔습니다.'
        self.assertEqual(first,rss.short_sentence(title,first+" 추가 정보를 나중에 알릴 예정입니다."))

    def test_fallback_for_empty_short_incomplete_and_repeated_lead(self):
        title="가상 시청 공원 개방 안내"
        for body in ("","소식입니다.","아직 끝나지 않은 소식이 이어지고 있습니다만",
                     title+"입니다. 시청은 새로운 운영 일정을 발표했습니다.",
                     '시청은 "현재 자체 추산 인원은 3만 명입니다. 다음 내용을 더 전했습니다.'):
            self.assertEqual(title,rss.short_sentence(title,body))

    def test_does_not_choose_second_sentence_when_first_repeats_title(self):
        title="가상 시청 공원 개방 안내"
        body=title+"입니다. 공원은 내일부터 시민들이 이용할 수 있도록 운영합니다."
        self.assertEqual(title,rss.short_sentence(title,body))

    def test_oversize_lead_falls_back_without_truncation(self):
        title="가상 소식"
        body="가상 설명을 전합니다 "*40+"마쳤습니다."
        self.assertEqual(title,rss.short_sentence(title,body))

    def test_middle_long_and_selection_are_identical_to_title_first_behavior(self):
        data=rows()
        with patch.object(rss,"short_sentence",side_effect=lambda title,description:title):
            before=rss.build(data,now=NOW)
        after=rss.build(data,now=NOW)
        self.assertEqual(before["중간"],after["중간"])
        self.assertEqual(before["길게"],after["길게"])
        for option in rss.OPTIONS:
            self.assertEqual([a["article_id"] for a in before[option]["articles"]],
                             [a["article_id"] for a in after[option]["articles"]])
        self.assertEqual(25,len(after["짧게"]["articles"]))
        for old,new in zip(before["짧게"]["articles"],after["짧게"]["articles"]):
            for field in old.keys()-{"tts_sentences"}:
                self.assertEqual(old[field],new[field],field)
            self.assertNotEqual(new["title"],new["tts_sentences"][0])

    def test_short_exact_lead_passes_forged_or_later_sentence_rejected(self):
        short=rss.build(rows(),now=NOW)["짧게"]
        rss.RssBriefing.model_validate(short)
        for text in ("원문에 없는 임의 생성 문장입니다.",short["articles"][0]["title"],
                     rss.source_units(short["articles"][0]["title"],short["articles"][0]["detail"])[2]):
            bad=copy.deepcopy(short);bad["articles"][0]["tts_sentences"]=[text]
            with self.assertRaises(ValueError):rss.RssBriefing.model_validate(bad)

    def test_short_title_fallback_is_still_valid(self):
        data=rows(1)
        data[0]["title"]="가상 기관에서 발표한 새로운 운영 소식"
        data[0]["description"]=data[0]["title"]+"입니다. 세부 운영 일정과 주민들의 자세한 이용 방법은 추후 시청 홈페이지를 통해 다시 안내할 계획입니다."
        doc=rss.build(data,now=NOW)["짧게"]
        self.assertEqual([doc["articles"][0]["title"]],doc["articles"][0]["tts_sentences"])
        rss.RssBriefing.model_validate(doc)

    def test_middle_long_cannot_use_body_only_prefix(self):
        docs=rss.build(rows(),now=NOW)
        for option in ("중간","길게"):
            bad=copy.deepcopy(docs[option]);a=bad["articles"][0]
            a["tts_sentences"][0]=rss.short_sentence(a["title"],a["detail"])
            with self.assertRaises(ValueError):rss.RssBriefing.model_validate(bad)
