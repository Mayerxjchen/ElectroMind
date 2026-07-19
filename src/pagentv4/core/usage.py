from __future__ import annotations

from typing import Any


def usage_to_dict(usage: object | None) -> dict[str, Any] | None:
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage
    model_dump = getattr(usage, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    as_dict = getattr(usage, "dict", None)
    if callable(as_dict):
        return as_dict()
    out: dict[str, Any] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = getattr(usage, key, None)
        if value is not None:
            out[key] = value
    for key in ("prompt_tokens_details", "completion_tokens_details"):
        details = getattr(usage, key, None)
        if details is None:
            continue
        if isinstance(details, dict):
            nested = details
        elif hasattr(details, "__dict__"):
            nested = {
                item_key: item_value
                for item_key, item_value in vars(details).items()
                if not item_key.startswith("_")
            }
        else:
            nested = usage_to_dict(details)
        if nested:
            out[key] = nested
    return out or None
