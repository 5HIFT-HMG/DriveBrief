"""Conservative RSS text extraction; raw metadata remains available for auditing."""
import re
from html import unescape
from html.parser import HTMLParser

VERSION = 'rss-quality-v2-editorial-labels'
MIN_DESCRIPTION_CHARACTERS = 50
EDITORIAL_LABELS = {
    '오그랲', '오그랩', '오그래프', '에디터픽', 'after8special', '지식의발견',
    '이슈대담', '뉴시스pic', 'newsispic', '뉴시스포토', '포토', '포토뉴스',
    '자막뉴스', 'd리포트', '글로벌d리포트', '이슈빡', '랭킹뉴스', '정치사상권',
    '뉴스딱', '뉴블더', '취재파일', '친절한경제', '올댓차이나', '차이나워치',
    'mai부동산', '여담야담', '분석+', '정지은의테크킥', '골프브리핑',
    '월가업&다운', '플랫', '트렌드+', '권용훈의트렌드워치', '이번주wsj',
}
EDGE_LABEL = re.compile(r'^\s*\[([^]\n]{1,50})\]\s*|\s*\[([^]\n]{1,50})\]\s*$')
SPLIT = re.compile(r'(?<=[.!?。！？])(?:\s+|(?=[가-힣]))|[\r\n]+')
NON_NEWS_TITLE = re.compile(r'^(?:(?:\[[^\]]{1,25}\]|\d{1,2}[월/.]\d{1,2}일?|\d{1,2}시|SBS|뉴스|8뉴스|8시 뉴스|모닝와이드)\s*)*(?:클로징|오프닝|방송\s*예고|뉴스\s*예고|끝인사)(?:\s*[.!]|\s*\([^)]*\))?\s*$', re.I)
CLOSING = re.compile(r'^(?:(?:(?:\d{1,2}시|SBS|8)\s*)?뉴스\s*(?:여기서\s*)?(?:마칩니다|마치겠습니다)|시청(?:해\s*주신|해주신|자\s*여러분).*?(?:고맙습니다|감사합니다)|(?:구독|좋아요|알림\s*설정).*(?:부탁드립니다|눌러주세요|주세요))[.!。]?$')
BRACKET_NOISE = re.compile(r'[\[(（](?:사진|영상|촬영|편집|그래픽|자료\s*사진|제공|출처|저작권|무단\s*전재|재배포)[^\]）)\n]*[\]）)]')
BYLINE_PREFIX = re.compile(r'^\s*(?:[\[(][^\])\n]{0,40}[\])]\s*)?(?:[가-힣]{2,4}(?:\s+[가-힣]{2,4}){0,4}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*(?:(?:인턴|수습|객원|선임|수석|사진|영상|전문)\s*)?(?:기자|특파원|통신원)\s*(?:=|:|/|\|)\s*')
BYLINE_SUFFIX = re.compile(r'(?:\s|[.!?。！？])(?:[가-힣]{2,4}\s*(?:(?:인턴|수습|객원|선임|수석|사진|영상|전문)\s*)?(?:기자|특파원|통신원))(?:\s+[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})?\s*\.?$')
REPORTER_SENTENCE = re.compile(r'^(?:보도에?\s*)?[가-힣]{2,4}\s*기자(?:의\s*보도)?(?:입니다|가\s*전합니다|가\s*보도합니다)[.!。]?$', re.I)
FOOTER = re.compile(r'(?:[©ⓒ]|Copyright\b|무단\s*(?:전재|복제)|재배포\s*금지|기사\s*제보|제보\s*(?:전화|메일)|[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}).*$', re.I)
CAPTION = re.compile(r'[▲△■□▶▷]|(?:^|\s)(?:사진|영상|자료사진)\s*[:=]')
ELLIPSIS = re.compile(r'(?:…|⋯|\.{3}|\[\s*(?:…|\.{3})\s*\])')


class Text(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []; self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'template', 'noscript'): self.hidden += 1
        if tag in ('p', 'div', 'br', 'li', 'figcaption'): self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'template', 'noscript') and self.hidden: self.hidden -= 1
        if tag in ('p', 'div', 'li', 'figcaption'): self.parts.append('\n')
    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)


def plain(value):
    value = value or ''
    for _ in range(8):
        new = unescape(value)
        if new == value: break
        value = new
    parser = Text(); parser.feed(value); parser.close()
    return ''.join(parser.parts)


def normalized(value):
    return re.sub(r'\s+', ' ', value).strip()


def spoken_title(title):
    def remove(match):
        label = re.sub(r'\s+', '', match.group(1) or match.group(2)).casefold()
        return '' if label in EDITORIAL_LABELS else match.group(0)
    while True:
        cleaned = EDGE_LABEL.sub(remove,title).strip()
        if cleaned == title:
            return cleaned
        title = cleaned


def complete(sentence):
    text = sentence.rstrip(' \"\'”’」』)]')
    if not text or ELLIPSIS.search(text): return False
    if text.endswith(('.', '!', '?', '。', '！', '？')): return True
    return bool(re.search(r'(?:다|요|죠|니다)$', text))


def credit_prefix(text):
    match = re.match(r'^([가-힣A-Za-z][가-힣A-Za-z0-9· ]{1,35})\s+제공\s+', text)
    if match and not re.search(r'[가-힣]+(?:은|는|을|를)\s', match.group(1)):
        return match.end()
    return 0


def assess(title, description, minimum=MIN_DESCRIPTION_CHARACTERS):
    title = re.sub(r'^[▲△■□▶▷]+\s*', '', normalized(BRACKET_NOISE.sub('', plain(title))))
    title = spoken_title(title)
    reasons, removed, sentences = [], [], []
    if NON_NEWS_TITLE.fullmatch(title.strip('[] ')): reasons.append('non_news_title')
    units = SPLIT.split(plain(description))
    for index, unit in enumerate(units):
        text = normalized(unit)
        if not text: continue
        if index+1 < len(units) and credit_prefix(normalized(units[index+1])):
            removed.append('photo_caption_before_credit'); continue
        credit = credit_prefix(text)
        if credit:
            text = text[credit:]; removed.append('photo_credit')
        if REPORTER_SENTENCE.fullmatch(text): removed.append('reporter_signoff'); continue
        if CLOSING.search(text): removed.append('closing_or_promotion'); continue
        if CAPTION.search(text): removed.append('caption_or_program_metadata'); continue
        text = normalized(BRACKET_NOISE.sub('', text))
        if REPORTER_SENTENCE.fullmatch(text): removed.append('reporter_signoff'); continue
        text = BYLINE_PREFIX.sub('', text)
        text = FOOTER.sub('', text)
        text = BYLINE_SUFFIX.sub('', text).strip()
        if not text: removed.append('attribution_or_footer'); continue
        if not complete(text): removed.append('incomplete_sentence'); continue
        if len(text) > 350: removed.append('oversize_sentence'); continue
        sentences.append(text)
    cleaned = ' '.join(sentences)
    if len(re.sub(r'\s', '', cleaned)) < minimum: reasons.append('insufficient_clean_description')
    if not sentences: reasons.append('no_complete_sentence')
    return dict(version=VERSION, title=title, description=cleaned, sentences=sentences,
                eligible=not reasons, reasons=sorted(set(reasons)), removed=sorted(set(removed)))


def main():
    import argparse
    import json
    import sqlite3
    from collections import Counter
    from pathlib import Path
    parser = argparse.ArgumentParser(description='Read-only RSS content-quality audit')
    parser.add_argument('--db', type=Path, required=True)
    args = parser.parse_args()
    counts = Counter()
    with sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro',uri=True) as db:
        for title, description in db.execute('SELECT title,description FROM articles'):
            result = assess(title,description)
            counts['articles'] += 1
            counts['eligible'] += result['eligible']
            counts.update(result['reasons']); counts.update(result['removed'])
    print(json.dumps(dict(version=VERSION,counts=dict(counts)),ensure_ascii=False))


if __name__ == '__main__':
    main()
