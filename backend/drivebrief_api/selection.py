"""Deterministic, conservative metadata heuristics. No source body, model or network."""
import hashlib
import math
import re
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

CATEGORIES = ["경제", "사회", "정치", "IT", "스포츠"]
STOP = {"뉴스", "속보", "오늘", "기자", "발표", "예정", "계획", "밝혔다", "대한", "이번", "위해"}
ACTIONS = [{"화재", "폭발", "사고"}, {"실적", "매출", "영업이익"}, {"출시", "신제품"}, {"착공", "준공", "건설"}]


def stable_id(prefix, value):
    return prefix + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def normalize(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "")).strip().casefold()


@lru_cache(maxsize=4096)
def tokens(text):
    return {t for t in re.findall(r"[가-힣a-z0-9]+", normalize(text)) if len(t) > 1 and t not in STOP}


@lru_cache(maxsize=4096)
def grams(text):
    text = re.sub(r"\s+", "", normalize(text))
    return {text[i:i+2] for i in range(len(text)-1)}


def similarity(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def timestamp(value):
    try:
        dt = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def canonical(value):
    try:
        u = urlsplit(value or "")
        if u.scheme not in ("https", "http") or not u.hostname or u.username or u.password:
            return ""
        args = sorted((k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
                      if not k.lower().startswith("utm_") and k.lower() not in {"plink", "cooper", "fbclid", "gclid"})
        return urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path, urlencode(args), ""))
    except ValueError:
        return ""


def metadata(rows):
    """Keep URL IDs and all memberships before exact/event grouping."""
    by_url = {}
    for row in rows:
        url = canonical(row.get("source_url", row.get("url", "")))
        if not url or not normalize(row.get("title")):
            continue
        item = by_url.setdefault(url, dict(article_id=stable_id("rss_", url), source_url=url,
            title=row["title"], description=row.get("description", ""), published_at=row.get("published_at"),
            categories=[], sources=[]))
        for field, single in (("categories", "category"), ("sources", "source")):
            item[field] = sorted(set(item[field]) | set(row.get(field) or [row.get(single, "")]) - {""})
    return sorted(by_url.values(), key=lambda r: r["article_id"])


def publisher(source, config):
    return normalize(config["source_aliases"].get(source, source))


def related(a, b, config):
    cfg = config["event"]
    da, db = timestamp(a["published_at"]), timestamp(b["published_at"])
    if not da or not db or abs((da-db).total_seconds()) > cfg["window_hours"]*3600:
        return None
    ta, tb = tokens(a["title"]), tokens(b["title"])
    shared = ta & tb
    if len(shared) < cfg["min_shared_tokens"]:
        return None
    for extract in (
        lambda text: {place for place in cfg.get("location_terms", []) if place in text},
        lambda text: set(re.findall(r"[가-힣a-z0-9]+(?:전자|자동차|은행|증권|그룹)", normalize(text))),
        lambda text: set(re.findall(r"(?:대표|장관|대통령|담당자|감독)\s*([가-힣]{2,4}?)(?=[\s,.:은는이가]|$)", text)),
    ):
        ea, eb = extract(a["title"]), extract(b["title"])
        if ea and eb and ea != eb:
            return None
    # Contradictory title numbers / explicit calendar dates are hard exclusions.
    na, nb = set(re.findall(r"\d+(?:[.,]\d+)*", a["title"])), set(re.findall(r"\d+(?:[.,]\d+)*", b["title"]))
    if na and nb and na != nb:
        return None
    aa = {i for i, words in enumerate(ACTIONS) if ta & words}
    ab = {i for i, words in enumerate(ACTIONS) if tb & words}
    if aa and ab and not aa & ab:
        return None
    title = similarity(grams(a["title"]), grams(b["title"]))
    if title < cfg["title_similarity"]:
        return None
    desc = similarity(tokens(a["description"]), tokens(b["description"]))
    if (len(shared) < cfg["min_shared_tokens"] or title < cfg["title_similarity"]
            or desc < cfg["description_similarity"]):
        return None
    return {"kind": "conservative_metadata_similarity", "title_similarity": round(title, 4),
            "description_similarity": round(desc, 4), "shared_tokens": sorted(shared),
            "hours_apart": round(abs((da-db).total_seconds())/3600, 3)}


def group_events(items, config):
    # Exact groups are unioned first; IDs of every source URL survive title dedup.
    parents = list(range(len(items)))
    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]; i = parents[i]
        return i
    urls, titles = {}, {}
    for i, row in enumerate(items):
        for mapping, key in ((urls, canonical(row["source_url"])), (titles, normalize(row["title"]))):
            if not key:
                continue
            if key in mapping:
                parents[find(i)] = find(mapping[key])
            mapping[key] = i
    exact = {}
    for i, item in enumerate(items):
        exact.setdefault(find(i), []).append(item)
    clusters = []
    for unit in sorted(exact.values(), key=lambda unit: min(r["article_id"] for r in unit)):
        # Complete-link across exact representatives avoids single-link chain merges.
        for cluster in clusters:
            if all(related(a, b, config) for old in cluster for a in unit for b in old):
                cluster.append(unit); break
        else:
            clusters.append([unit])
    groups = []
    for cluster in clusters:
        members = sorted([r for unit in cluster for r in unit], key=lambda r: r["article_id"])
        def quality(r):
            return sum([bool(r["description"].strip()), timestamp(r["published_at"]) is not None,
                        bool(r["categories"]), bool(r["sources"])])/4
        representative = sorted(members, key=lambda r: (-quality(r),
            -(timestamp(r["published_at"]).timestamp() if timestamp(r["published_at"]) else 0), r["article_id"]))[0]
        reasons = []
        for unit in cluster:
            if len(unit) > 1:
                reasons.append({"kind": "exact_url_or_normalized_title",
                                "article_ids": [r["article_id"] for r in unit]})
        for i in range(len(cluster)):
            for j in range(i):
                why = related(cluster[i][0], cluster[j][0], config)
                if why:
                    reasons.append(dict(why, article_ids=[cluster[i][0]["article_id"], cluster[j][0]["article_id"]]))
        groups.append({"group_id": stable_id("event_", "|".join(r["article_id"] for r in members)),
                       "representative": representative, "members": members, "reasons": reasons,
                       "exact_units": len(cluster)})
    return groups


def rank_groups(groups, interests, as_of, config):
    if not as_of.tzinfo or any(c not in CATEGORIES for c in interests):
        raise ValueError("invalid_selection_request")
    weights = config["weights"]
    output = []
    for group in groups:
        members = group["members"]
        categories = sorted({c for m in members for c in m["categories"] if c in CATEGORIES})
        sources = sorted({s for m in members for s in m["sources"]})
        publishers = {publisher(s, config) for s in sources}
        times = [timestamp(m["published_at"]) for m in members]
        valid = [d for d in times if d and d <= as_of]
        age = max(0, (as_of-max(valid)).total_seconds()/3600) if valid else None
        # At most two distinct title reports per publisher, then saturation at four.
        coverage = {}
        for m in members:
            for source in m["sources"]:
                coverage.setdefault(publisher(source, config), set()).add(normalize(m["title"]))
        count = sum(min(2, len(titles)) for titles in coverage.values())
        features = {"recency": 2**(-age/24) if age is not None else 0,
                    "coverage": min(4, count)/4,
                    "diversity": min(3, len(publishers))/3,
                    "interest": float(bool(set(categories) & set(interests))),
                    "quality": sum(sum([bool(m["title"].strip()), bool(m["description"].strip()),
                        bool(timestamp(m["published_at"]) and timestamp(m["published_at"]) <= as_of),
                        bool(m["categories"]), bool(m["sources"])])/5 for m in members)/len(members)}
        contributions = {k: round(weights[k]*v, 6) for k, v in features.items()}
        rep = group["representative"]
        output.append(dict(group_id=group["group_id"], article_id=rep["article_id"], title=rep["title"],
                           source=rep["sources"][0] if rep["sources"] else "", sources=sources,
                           category=categories[0] if categories else "", categories=categories,
                           published_at=rep["published_at"], source_url=rep["source_url"],
                           importance_score=round(sum(contributions.values()), 6),
                           score_components=contributions, related_article_ids=[m["article_id"] for m in members],
                           grouping_reasons=group["reasons"], ai_eligible=False, summary_status="not_available"))
    return output


def balanced_select(ranked, interests, limit, penalty):
    remaining = list(ranked)
    chosen, counts = [], {c: 0 for c in CATEGORIES}
    while remaining and len(chosen) < limit:
        def key(r):
            cats = [c for c in r["categories"] if c in interests] or r["categories"]
            count = min((counts.get(c, 0) for c in cats), default=0)
            return (-int(bool(set(r["categories"]) & set(interests))),
                    -(r["importance_score"] - penalty*count), r["group_id"])
        item = min(remaining, key=key)
        remaining.remove(item)
        cats = [c for c in item["categories"] if c in interests] or item["categories"]
        assigned = min(cats, key=lambda c: (counts.get(c, 0), c)) if cats else None
        if assigned: counts[assigned] += 1
        chosen.append(dict(item, rank=len(chosen)+1,
                           selection_reason={"interest_match": bool(set(item["categories"]) & set(interests)),
                                             "balance_category": assigned, "fallback": bool(interests) and not bool(set(item["categories"]) & set(interests))}))
    return chosen
