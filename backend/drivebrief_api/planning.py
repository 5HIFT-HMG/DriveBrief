"""Approved sentence-prefix planning. Does not generate, edit, approve or fetch articles."""
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Header
from .news_repository import Category
from .pipeline_settings import load_config
from .pipeline_models import PlannedResponse
from .selection import group_events, rank_groups, balanced_select, timestamp

SAMPLE_CATEGORIES = Path(__file__).resolve().parents[1] / "samples/pipeline_categories.json"


def estimate(sentence, cfg):
    return len(sentence)/cfg["characters_per_second"] + cfg["sentence_pause_seconds"]


def plan(document, option, interests, cfg, as_of=None, category_map=None, budget_packing=False, private_preview=False):
    schema = "rss-preview-input-v1" if private_preview else "approved-briefing-v1"
    if private_preview and (document.get("preview_only") is not True or document.get("publication_allowed") is not False
                            or document.get("fictional_only") is not False or budget_packing):
        raise ValueError("invalid_preview_input")
    if (option not in cfg["length_seconds"] or document.get("schema_version") != schema
            or type(document.get("fictional_only")) is not bool):
        raise ValueError("invalid_planning_input")
    fictional = document["fictional_only"]
    content_kind = document.get("content_kind", "fictional")
    if content_kind != ("fictional" if fictional else "rss_metadata"):
        raise ValueError("real_planning_blocked_by_policy")
    now = as_of or datetime.now(timezone.utc)
    target = cfg["length_seconds"][option]
    category_map = category_map or {}
    by_id, items = {}, []
    for article in document["articles"]:
        expected_status = ({"status": "needs_review", "approved": False, "review_required": True} if private_preview
                           else {"status": "approved", "approved": True, "review_required": False})
        if article["validation"] != expected_status:
            raise ValueError("unapproved_input")
        if article["article_id"] in by_id:
            raise ValueError("duplicate_article")
        if not article["tts_sentences"] or any(not isinstance(s, str) or not s.strip() for s in article["tts_sentences"]):
            raise ValueError("invalid_sentences")
        if not fictional:
            from urllib.parse import urlsplit
            url = urlsplit(article.get("source_url") or "")
            if (article.get("content_kind") != "rss_metadata" or article.get("mock") is not False
                    or url.scheme != "https" or not url.hostname or url.username or url.password):
                raise ValueError("rss_playback_input_invalid")
        by_id[article["article_id"]] = article
        cats = article.get("categories") or category_map.get(article["article_id"], [])
        items.append(dict(article_id=article["article_id"], title=article["title"],
                          description=article["one_line"], published_at=article["published_at"],
                          categories=cats, sources=[article["source"]],
                          source_url=article.get("source_url") or ""))
    # Empty source_url is not an exact duplicate key for synthetic source-less articles.
    groups = group_events(items, cfg)
    ranked = rank_groups(groups, interests, now, cfg)
    ordered = balanced_select(ranked, interests, cfg["max_articles"], cfg["event"]["balance_penalty"])
    selected, budget = [], float(target)
    seen_sentences = set()
    for candidate in ordered:
        original = by_id[candidate["article_id"]]
        first = original["tts_sentences"][0]
        if first in seen_sentences or estimate(first, cfg) > budget:
            continue
        selected.append(dict(original, categories=candidate["categories"], group_id=candidate["group_id"],
                             importance_score=candidate["importance_score"], sentence_indices=[0],
                             tts_sentences=[first], approved_sentence_count=len(original["tts_sentences"])))
        budget -= estimate(first, cfg)
        seen_sentences.add(first)
    # Allocate additional approved sentences in rank order, round-robin, always contiguous prefix.
    while selected:
        changed = False
        for item in selected:
            idx = len(item["tts_sentences"])
            original = by_id[item["article_id"]]["tts_sentences"]
            if idx < len(original):
                sentence = original[idx]
                if sentence not in seen_sentences and estimate(sentence, cfg) <= budget:
                    item["tts_sentences"].append(sentence)
                    item["sentence_indices"].append(idx)
                    seen_sentences.add(sentence)
                    budget -= estimate(sentence, cfg)
                    changed = True
        if not changed:
            break
    method = 'legacy_prefix'
    if budget_packing:
        from .algorithm_v2 import budget_candidate
        try:
            packed = budget_candidate(document,option,interests,cfg,now,category_map,objective='time')
            ranked_by_id = {item['article_id']:item for item in ordered}
            selected = [dict(item,categories=ranked_by_id[item['article_id']]['categories'],
                             group_id=ranked_by_id[item['article_id']]['group_id'],
                             importance_score=ranked_by_id[item['article_id']]['importance_score'],
                             approved_sentence_count=len(by_id[item['article_id']]['tts_sentences']))
                        for item in packed['articles']]
            budget = target - sum(estimate(s,cfg) for item in selected for s in item['tts_sentences'])
            method = 'budget_prefix'
        except ValueError as error:
            if str(error) != 'offline_state_limit_exceeded':
                raise
            method = 'legacy_fallback'
    for i, item in enumerate(selected):
        item["order"] = i + 1
        item["partial_tts"] = len(item["tts_sentences"]) < item["approved_sentence_count"]
        item["estimated_seconds"] = round(sum(estimate(s, cfg) for s in item["tts_sentences"]), 3)
    expected = round(target-budget, 3)
    identity = json.dumps({"articles": selected, "option": option, "target": target,
                           "rate": cfg["characters_per_second"], "pause": cfg["sentence_pause_seconds"]},
                          ensure_ascii=False, sort_keys=True)
    return dict(schema_version="private-rss-preview-v1" if private_preview else "approved-briefing-v1",
                **({"preview_only": True, "publication_allowed": False} if private_preview else {}),
                fictional_only=fictional, content_kind=content_kind, playback_requires_user_action=True,
                briefing_id="brief_" + hashlib.sha256(identity.encode()).hexdigest()[:24],
                length_option=option, policy_status=cfg["policy_status"], target_seconds=target,
                estimated_seconds=expected, delta_seconds=round(expected-target, 3),
                timing_estimate_only=True, as_of=now.isoformat(), planning_method=method,
                timing_profile=cfg.get('_timing_profile','baseline'),
                shortage=expected < target, status="ready" if selected else "no_fitting_approved_articles",
                articles=selected)


def planning_router(store):
    api = APIRouter()
    @api.get("/v1/briefings/plan", response_model=PlannedResponse)
    def briefing_plan(length: Literal["짧게", "중간", "길게"] = "중간",
                      categories: Optional[List[Category]] = Query(None), as_of: Optional[datetime] = None,
                      tts_sdk: Optional[str] = Header(None,alias='X-DriveBrief-TTS-SDK'),
                      tts_locale: Optional[str] = Header(None,alias='X-DriveBrief-TTS-Locale')):
        if as_of is not None and as_of.tzinfo is None:
            raise HTTPException(422, detail={"code": "timezone_required"})
        try:
            category_map = json.loads(SAMPLE_CATEGORIES.read_text(encoding="utf-8"))
            from .timing_calibration import calibrated_config
            config = calibrated_config(load_config(),os.getenv('DRIVEBRIEF_TIMING_MODEL'),tts_sdk,tts_locale)
            return PlannedResponse.model_validate(plan(store.briefing(limit=None),length,categories or [],config,
                as_of,category_map,budget_packing=os.getenv('DRIVEBRIEF_BUDGET_PACKING')=='1'))
        except (ValueError, OSError, KeyError, TypeError, sqlite3.Error):
            raise HTTPException(503, detail={"code": "planning_data_unavailable"}) from None
    return api
