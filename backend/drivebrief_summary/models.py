from typing import List, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Rights(StrictModel):
    kind: Literal["fictional", "licensed", "unverified"]
    external_llm_allowed: bool = False
    summary_reuse_allowed: bool = False
    basis: str = Field(default="", max_length=1000)


class Article(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(max_length=20000)
    source: str = Field(min_length=1, max_length=300)
    rights: Rights


class SummaryText(StrictModel):
    status: Literal["ok", "insufficient"]
    reason: str
    tts_sentences: List[str]
    one_line: str
    detail: str

    @model_validator(mode="after")
    def check_text(self):
        if self.status == "insufficient":
            if not self.reason.strip() or self.tts_sentences or self.one_line or self.detail:
                raise ValueError("insufficient requires reason and empty summary text")
        else:
            if self.reason or not 1 <= len(self.tts_sentences) <= 8:
                raise ValueError("ok requires empty reason and 1..8 TTS sentences")
            if not self.one_line.strip() or len(self.one_line) > 250 or "\n" in self.one_line:
                raise ValueError("one_line must be a nonempty single line <=250 characters")
            if not self.detail.strip() or len(self.detail) > 2500:
                raise ValueError("detail must be nonempty and <=2500 characters")
            if any(not s.strip() or len(s) > 350 or "\n" in s for s in self.tts_sentences):
                raise ValueError("invalid TTS sentence")
        return self


class EvidenceLink(StrictModel):
    target: Literal["tts_sentences", "one_line", "detail"]
    index: int = Field(ge=0)
    evidence_ids: List[str] = Field(min_length=1, max_length=8)


class Draft(SummaryText):
    """LLM wire format: no quote and no self-attested validation/approval fields."""
    evidence_links: List[EvidenceLink]

    @model_validator(mode="after")
    def check_links(self):
        if self.status == "insufficient":
            if self.evidence_links:
                raise ValueError("insufficient cannot contain links")
        elif not 1 <= len(self.evidence_links) <= 10:
            raise ValueError("each output requires one link")
        return self


class Evidence(StrictModel):
    claim: str
    quote: str


class Summary(SummaryText):
    """Public result keeps legacy claim/quote fields; Python alone creates quotes."""
    evidence_snippets: List[Evidence]

    @model_validator(mode="after")
    def check_evidence(self):
        if self.status == "insufficient":
            if self.evidence_snippets:
                raise ValueError("insufficient cannot contain evidence")
        elif not 1 <= len(self.evidence_snippets) <= 80:
            raise ValueError("evidence is required")
        if any(not e.claim.strip() or not e.quote.strip() or len(e.quote) > 1200
               for e in self.evidence_snippets):
            raise ValueError("invalid evidence")
        return self


def insufficient(reason: str) -> Summary:
    return Summary(status="insufficient", reason=reason, tts_sentences=[],
                   one_line="", detail="", evidence_snippets=[])


def insufficient_draft(reason: str) -> Draft:
    return Draft(status="insufficient", reason=reason, tts_sentences=[],
                 one_line="", detail="", evidence_links=[])
