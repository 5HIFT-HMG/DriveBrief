import json
import math
import os
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "pipeline_config.json"
OPTIONS = ("짧게", "중간", "길게")


def load_config(path=None):
    path = Path(path or os.getenv("DRIVEBRIEF_PIPELINE_CONFIG", str(DEFAULT_CONFIG)))
    cfg = json.loads(path.read_text(encoding="utf-8"))
    def number(value, lo, hi):
        return type(value) in (int, float) and math.isfinite(value) and lo <= value <= hi
    if (cfg["policy_status"] != "development_placeholder_not_team_policy"
            or set(cfg["length_seconds"]) != set(OPTIONS)
            or any(not number(n, 1, 3600) for n in cfg["length_seconds"].values())
            or not number(cfg["characters_per_second"], 0.5, 30)
            or not number(cfg["sentence_pause_seconds"], 0, 5)
            or type(cfg["max_articles"]) is not int or not 1 <= cfg["max_articles"] <= 10
            or type(cfg["input_limit"]) is not int or not 25 <= cfg["input_limit"] <= 5000):
        raise ValueError("invalid_pipeline_config")
    ev = cfg["event"]
    if (not number(ev["window_hours"], 1, 168)
            or not number(ev["title_similarity"], .1, 1)
            or not number(ev["description_similarity"], .1, 1)
            or type(ev["min_shared_tokens"]) is not int or not 2 <= ev["min_shared_tokens"] <= 20
            or not number(ev["balance_penalty"], 0, 1)):
        raise ValueError("invalid_event_config")
    if not isinstance(ev.get("location_terms", []), list) or any(not isinstance(t, str) or not t.strip() for t in ev.get("location_terms", [])):
        raise ValueError("invalid_location_terms")
    if set(cfg["weights"]) != {"recency", "coverage", "diversity", "interest", "quality"}:
        raise ValueError("invalid_weights")
    if any(not number(n, 0, 1) for n in cfg["weights"].values()) or abs(sum(cfg["weights"].values())-1) > 1e-6:
        raise ValueError("invalid_weights")
    if not isinstance(cfg["source_aliases"], dict) or any(not isinstance(k, str) or not isinstance(v, str) or not v.strip()
                                                        for k, v in cfg["source_aliases"].items()):
        raise ValueError("invalid_source_aliases")
    return cfg
