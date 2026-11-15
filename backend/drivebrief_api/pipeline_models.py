"""Wire DTOs are intentionally separate from selection/planning algorithms."""
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator


class GroupReason(BaseModel):
    kind: Literal["exact_url_or_normalized_title", "conservative_metadata_similarity"]
    article_ids: List[str]
    title_similarity: Optional[float] = None
    description_similarity: Optional[float] = None
    shared_tokens: Optional[List[str]] = None
    hours_apart: Optional[float] = None


class SelectionReason(BaseModel):
    interest_match: bool
    balance_category: Optional[str]
    fallback: bool


class CandidateItem(BaseModel):
    article_id: str
    group_id: str
    title: str
    source: str
    sources: List[str]
    category: str
    categories: List[str]
    published_at: Optional[str]
    source_url: str
    importance_score: float
    score_components: Dict[str, float]
    related_article_ids: List[str]
    grouping_reasons: List[GroupReason]
    ai_eligible: Literal[False]
    summary_status: Literal["not_available"]
    rank: int
    selection_reason: SelectionReason


class CandidateResponse(BaseModel):
    schema_version: Literal["ranked-news-v1"]
    as_of: str
    metadata_only: Literal[True]
    ai_eligible: Literal[False]
    grouping_method: Literal["conservative_heuristic_v1"]
    input_count: int
    processed_count: int
    input_truncated: bool
    group_count: int
    articles: List[CandidateItem]


class ApprovedStatus(BaseModel):
    status: Literal["approved"]
    approved: Literal[True]
    review_required: Literal[False]


class PlannedArticle(BaseModel):
    content_kind: Literal["fictional", "rss_metadata"] = "fictional"
    article_id: str
    title: str
    source: str
    published_at: str
    source_url: Optional[str]
    tts_sentences: List[str] = Field(min_length=1, max_length=8)
    one_line: str
    detail: str
    mock: bool
    validation: ApprovedStatus
    categories: List[str]
    group_id: str
    importance_score: float
    sentence_indices: List[int]
    approved_sentence_count: int = Field(ge=1, le=8)
    order: int = Field(ge=1)
    partial_tts: bool
    estimated_seconds: float = Field(ge=0)


class PlannedResponse(BaseModel):
    schema_version: Literal["approved-briefing-v1"]
    fictional_only: bool = Field(strict=True)
    content_kind: Literal["fictional", "rss_metadata"] = "fictional"
    playback_requires_user_action: Literal[True]
    briefing_id: str
    length_option: Literal["짧게", "중간", "길게"]
    policy_status: Literal["development_placeholder_not_team_policy"]
    target_seconds: float = Field(gt=0)
    estimated_seconds: float = Field(ge=0)
    delta_seconds: float
    planning_method: Literal['legacy_prefix','budget_prefix','legacy_fallback'] = 'legacy_prefix'
    timing_profile: Literal['baseline','calibrated'] = 'baseline'
    timing_estimate_only: Literal[True]
    as_of: str
    shortage: bool
    status: Literal["ready", "no_fitting_approved_articles"]
    articles: List[PlannedArticle] = Field(max_length=10)

    @model_validator(mode="after")
    def check_origin(self):
        if self.content_kind != ("fictional" if self.fictional_only else "rss_metadata"):
            raise ValueError("briefing_origin_mismatch")
        for article in self.articles:
            if article.content_kind != self.content_kind:
                raise ValueError("mixed_briefing_origins")
            if not self.fictional_only:
                from urllib.parse import urlsplit
                url = urlsplit(article.source_url or "")
                if article.mock or url.scheme != "https" or not url.hostname or url.username or url.password:
                    raise ValueError("rss_playback_input_invalid")
        return self


class PreviewStatus(BaseModel):
    status: Literal["needs_review"]
    approved: Literal[False]
    review_required: Literal[True]


class PreviewArticle(PlannedArticle):
    validation: PreviewStatus
    content_kind: Literal["rss_metadata"]
    mock: Literal[False]


class PrivateRssPreview(PlannedResponse):
    """Never accepted by the production publisher or ordinary Android parser."""
    schema_version: Literal["private-rss-preview-v1"]
    preview_only: Literal[True]
    publication_allowed: Literal[False]
    fictional_only: Literal[False]
    content_kind: Literal["rss_metadata"]
    articles: List[PreviewArticle] = Field(max_length=10)
