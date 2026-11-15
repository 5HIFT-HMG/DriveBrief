"""Offline candidates only. Live selection/planning/API contracts remain unchanged."""
import copy
import math
import re
from .selection import group_events, rank_groups, balanced_select, normalize
from .planning import plan, estimate


def normalized_candidate(items, config):
    """Keep ORIGINAL exact dedup; normalization only enters time-gated complete-link."""
    from .selection import related, stable_id
    items = sorted(copy.deepcopy(items), key=lambda r: r["article_id"])
    adjusted = copy.deepcopy(items)
    for row in adjusted:
        for field in ("title", "description"):
            row[field] = re.sub(r"([가-힣]{3,}?)(에서는|에서|으로|에게|은|는|을|를)(?=\s|[,.:!?]|$)",
                                r"\1", normalize(row[field]))
    by_id = {r["article_id"]: r for r in adjusted}
    exact_cfg = copy.deepcopy(config)
    # Disable similarity merges ONLY to obtain the existing original exact units.
    exact_cfg["event"]["title_similarity"] = 2
    units = group_events(items, exact_cfg)
    clusters = []
    for unit in units:
        for cluster in clusters:
            if all(related(by_id[a["article_id"]], by_id[b["article_id"]], config)
                   for a in unit["members"] for old in cluster for b in old["members"]):
                cluster.append(unit)
                break
        else:
            clusters.append([unit])
    output = []
    for cluster in clusters:
        members = sorted([m for unit in cluster for m in unit["members"]], key=lambda r:r["article_id"])
        output.append({"group_id": stable_id("event_", "|".join(m["article_id"] for m in members)),
                       "members": members, "representative": members[0],
                       "reasons": [{"kind": "experimental_particle_complete_link"}]})
    return output


def candidate_ranks(items, config, as_of, interests, limit=20):
    """Contrast reduced coverage/diversity weights and lower balancing penalty, not a policy."""
    from pathlib import Path
    from .pipeline_settings import load_config
    candidate = load_config(Path(__file__).resolve().parents[1] / "samples/algorithm_v2_candidate.json")
    cfg = copy.deepcopy(config)
    cfg["weights"] = candidate["weights"]
    cfg["event"]["balance_penalty"] = candidate["event"]["balance_penalty"]
    groups = group_events(items, cfg)
    return balanced_select(rank_groups(groups, interests, as_of, cfg), interests, limit,
                           cfg["event"]["balance_penalty"]), cfg


def prefix_digest(article):
    from .quality import fingerprint
    return fingerprint(article["tts_sentences"])


def budget_candidate(document, option, interests, config, as_of, category_map=None, constraints=None, objective="utility"):
    """Multiple-choice knapsack of intact approved prefixes, offline and bounded.

    A constraint pins a minimum prefix to the exact approved text hash + a named reviewer.
    No automatic importance/semantic coverage labels are inferred.
    """
    if objective not in ('utility','time'):
        raise ValueError('invalid_budget_objective')
    cfg = copy.deepcopy(config)
    # Reuse ALL existing approval/fictional/duplicate/schema checks and ordering.
    cfg["length_seconds"] = {key: 3600 for key in cfg["length_seconds"]}
    full = plan(document, option, interests, cfg, as_of, category_map)
    target = config["length_seconds"][option]
    capacity = math.floor(target*1000)
    originals = {a["article_id"]: a for a in document["articles"]}
    constraints = constraints or {}
    if set(constraints)-set(originals):
        raise ValueError("unknown_constraint_article")
    for aid, value in constraints.items():
        original = originals[aid]
        if (not value.get("reviewer", "").strip() or
            value.get("approved_text_hash") != prefix_digest(original) or
            type(value.get("minimum_prefix")) is not int or
            not 1 <= value["minimum_prefix"] <= len(original["tts_sentences"])):
            raise ValueError("unreviewed_or_stale_prefix_constraint")
    occurrences = {}
    for article in full['articles']:
        for sentence in set(originals[article['article_id']]['tts_sentences']):
            occurrences[sentence] = occurrences.get(sentence,0)+1
    shared_texts = {text for text,count in occurrences.items() if count>1}
    # Only shared text can constrain future articles; unique text need not expand state identity.
    states = {(0, frozenset()): (0., ())}
    for rank, article in enumerate(full["articles"]):
        original = originals[article["article_id"]]
        sentences = original["tts_sentences"]
        minimum = constraints.get(article["article_id"], {}).get("minimum_prefix", 1)
        options = []
        for n in range(minimum, len(sentences)+1):
            prefix = sentences[:n]
            if len(set(prefix)) != n:
                continue
            cost = sum(math.ceil(estimate(s, config)*1000) for s in prefix)
            # Explicit experimental utility: article priority + diminishing context value.
            utility = (1 + article["importance_score"])/(rank+1) * (1 + math.log2(n))
            options.append((n, cost, utility, frozenset(prefix)))
        next_states = dict(states)
        for (used, texts), (score, choices) in states.items():
            for n, cost, utility, prefix in options:
                if used+cost > capacity or texts & prefix:
                    continue
                key = (used+cost, texts | (prefix & shared_texts))
                candidate = (score+utility, choices+((article["article_id"], n),))
                old = next_states.get(key)
                if old is None or candidate[0] > old[0] or (candidate[0] == old[0] and candidate[1] < old[1]):
                    next_states[key] = candidate
        if len(next_states) > 50000:
            raise ValueError("offline_state_limit_exceeded")
        states = next_states
    key, best = min(states.items(), key=(lambda pair: (-pair[0][0],-pair[1][0],pair[1][1]))
                    if objective == 'time' else (lambda pair: (-pair[1][0],-pair[0][0],pair[1][1])))
    selected = []
    for aid, n in best[1]:
        original = originals[aid]
        selected.append(dict(original, tts_sentences=original["tts_sentences"][:n],
                             sentence_indices=list(range(n)), partial_tts=n < len(original["tts_sentences"])))
    seconds = sum(estimate(s, config) for a in selected for s in a["tts_sentences"])
    return {"experiment_only": True, "not_service_contract": True,
            "option": option, "objective": objective, "target_seconds": target, "estimated_seconds": round(seconds, 3),
            "unused_seconds": round(target-seconds, 3), "utility": best[0], "articles": selected,
            "constraints_explicitly_reviewed": sorted(constraints),
            "coverage_not_semantically_verified": True}
