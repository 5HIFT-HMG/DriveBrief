import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import List
from .models import Article

SEGMENT_VERSION = "source-spans-v1"
MAX_SPAN = 900


@dataclass(frozen=True)
class SourceSpan:
    id: str
    field: str
    start: int
    end: int
    text: str

    def as_dict(self):
        return asdict(self)


def split_article(article: Article) -> List[SourceSpan]:
    """Deterministic approximate sentence spans, preserving exact Unicode codepoint offsets.
    IDs are stable for identical title/body and algorithm version; any revision invalidates IDs.
    No assertion of semantic independence is made for a span.
    """
    revision = hashlib.sha256(json.dumps([article.title, article.body],
                                         ensure_ascii=False).encode("utf-8")).hexdigest()
    spans = []
    for field, text in (("title", article.title), ("body", article.body)):
        start = 0
        cuts = [m.start() for m in re.finditer(r"(?<=[.!?。！？])[ \t\r\n]+|[\r\n]+", text)] + [len(text)]
        for end in cuts:
            cursor = start
            while cursor < end:
                while cursor < end and text[cursor].isspace():
                    cursor += 1
                if cursor == end:
                    break
                stop = min(cursor + MAX_SPAN, end)
                if stop < end:
                    boundary = text.rfind(" ", cursor, stop)
                    if boundary > cursor:
                        stop = boundary
                trimmed = stop
                while trimmed > cursor and text[trimmed - 1].isspace():
                    trimmed -= 1
                chunk = text[cursor:trimmed]
                identity = json.dumps([SEGMENT_VERSION, revision, field, cursor, trimmed, chunk], ensure_ascii=False)
                span_id = "e_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
                spans.append(SourceSpan(span_id, field, cursor, trimmed, chunk))
                cursor = stop
            start = end
    if len({span.id for span in spans}) != len(spans):
        raise ValueError("Source span id collision")
    return spans
