"""Fail-closed guard for strict no-ML v2 numeric production inputs."""

from __future__ import annotations

from typing import Any, Mapping


class NoMLNumericPathError(ValueError):
    """Raised when a legacy learned or LLM numeric path reaches v2."""


FORBIDDEN_MARKERS = frozenset(
    {
        "xgboost", "lightgbm", "random_forest", "random-forest", "svm", "neural",
        "transformer", "lstm", "gnn", "learned", "fitted", "platt", "isotonic",
        "temperature-fitting", "temperature_fitting", "stacking", "meta-model",
    }
)
LLM_PROVIDERS = frozenset({"deepseek", "chatgpt", "gpt", "llm", "openai"})
NUMERIC_FIELDS = frozenset(
    {"probabilities", "model_probabilities", "expected_goals", "stake", "stake_fraction", "weights"}
)


def assert_v2_numeric_path_allowed(payload: Mapping[str, Any], *, source: str | None = None) -> None:
    """Reject learned/fitted/LLM numeric output before v2 persistence or selection."""

    haystack = " ".join(
        str(payload.get(key) or "").casefold()
        for key in (
            "model_key", "model_version", "calibration_version", "weights_source",
            "probability_source", "expected_goals_source", "stake_source", "engine",
        )
    )
    haystack += " " + str(source or "").casefold()
    marker = next((item for item in FORBIDDEN_MARKERS if item in haystack), None)
    if marker:
        raise NoMLNumericPathError(f"v2 no-ML numeric path rejected: {marker}")

    numeric = _numeric_fields(payload)
    ai = payload.get("ai")
    provider = str((ai or {}).get("provider") if isinstance(ai, Mapping) else "").casefold()
    status = str((ai or {}).get("status") if isinstance(ai, Mapping) else "").casefold()
    source_name = str(source or payload.get("source") or "").casefold()
    source_is_llm = any(marker in source_name for marker in LLM_PROVIDERS)
    if numeric and (source_is_llm or (provider in LLM_PROVIDERS and status in {"completed", "ok", "success"})):
        raise NoMLNumericPathError(
            "v2 LLM numeric output rejected: " + ", ".join(sorted(numeric))
        )


def no_ml_audit_event(payload: Mapping[str, Any], *, source: str | None = None) -> dict[str, Any]:
    """Return an auditable, non-sensitive deny event without changing payload."""

    try:
        assert_v2_numeric_path_allowed(payload, source=source)
    except NoMLNumericPathError as error:
        return {"status": "DENY", "reason": str(error), "source": source}
    return {"status": "PASS", "source": source}


def _numeric_fields(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        found = {
            str(key)
            for key, item in value.items()
            if str(key) in NUMERIC_FIELDS and item not in (None, {}, [])
        }
        for item in value.values():
            found.update(_numeric_fields(item))
        return found
    if isinstance(value, (list, tuple)):
        found: set[str] = set()
        for item in value:
            found.update(_numeric_fields(item))
        return found
    return set()
