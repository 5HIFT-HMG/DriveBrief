"""Explicit selected-ID -> separately supplied, permission-checked full-text input boundary."""
from .review import InputArticle


def selected_inputs(selected_ids, catalog):
    if not isinstance(selected_ids, list) or any(not isinstance(i, str) for i in selected_ids):
        raise ValueError("invalid_selected_ids")
    if len(set(selected_ids)) != len(selected_ids):
        raise ValueError("duplicate_selected_id")
    originals = [InputArticle.model_validate(raw) for raw in catalog]
    if len({r.article.id for r in originals}) != len(originals):
        raise ValueError("duplicate_catalog_id")
    by_id = {r.article.id: r for r in originals}
    output = []
    for article_id in selected_ids:
        if article_id not in by_id:
            # RSS metadata alone is never turned into a full-text Article.
            raise ValueError("verified_full_text_missing")
        output.append(by_id[article_id].checked().model_dump())
    return output
