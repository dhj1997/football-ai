"""Cutoff-safe, deterministic Round 5 Market Prior and probability fusion."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from statistics import fmean
from typing import Any, Iterable, Mapping

from .market_intelligence import devig_market, normalize_quote
from .no_ml_guard import assert_v2_numeric_path_allowed
from .prediction_intelligence import parse_timestamp


OUTCOMES: tuple[str, ...] = ("home", "draw", "away")
MARKET_MODEL_VERSION = "market-prior-v1"
MARKET_CALCULATION_VERSION = "round5-market-prior-v1"
FUSION_VERSION = "round5-fixed-fusion-v1"
AUDIT_VERSION = "round5-probability-audit-v1"


class MarketPriorError(ValueError):
    """Raised when Round 5 cannot safely validate its fixed calculation."""


@dataclass(frozen=True)
class MarketPriorConfig:
    """Published policy constants; none are learned or historically fitted."""

    market_model_version: str = MARKET_MODEL_VERSION
    calculation_version: str = MARKET_CALCULATION_VERSION
    fusion_version: str = FUSION_VERSION
    model_weight: float = 0.60
    market_weight: float = 0.40

    def __post_init__(self) -> None:
        weights = (self.model_weight, self.market_weight)
        if any(not math.isfinite(value) or value < 0 for value in weights):
            raise ValueError("fusion weights must be finite and non-negative")
        if not math.isclose(sum(weights), 1.0, abs_tol=1e-12):
            raise ValueError("fusion weights must sum to one")
        if not self.market_model_version or not self.calculation_version or not self.fusion_version:
            raise ValueError("Round 5 versions are required")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def config_hash(self) -> str:
        encoded = _canonical_json(self.as_dict()).encode()
        return f"round5-config:{hashlib.sha256(encoded).hexdigest()[:24]}"


def implied_probability(decimal_odds: Any) -> float:
    """Return ``1 / decimal_odds`` after strict decimal-price validation."""

    if isinstance(decimal_odds, bool) or decimal_odds is None:
        raise MarketPriorError("decimal odds must be a finite number greater than one")
    try:
        price = float(decimal_odds)
    except (TypeError, ValueError) as error:
        raise MarketPriorError("decimal odds must be a finite number greater than one") from error
    if not math.isfinite(price) or price <= 1.0:
        raise MarketPriorError("decimal odds must be a finite number greater than one")
    return 1.0 / price


def multiplicative_devig(prices: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the repository's proportional de-vig primitive to one 1X2 book."""

    if not isinstance(prices, Mapping) or set(prices) != set(OUTCOMES):
        raise MarketPriorError("a complete 1X2 market is required")
    normalized_prices: dict[str, float] = {}
    for selection in OUTCOMES:
        implied_probability(prices[selection])
        normalized_prices[selection] = float(prices[selection])
    rows = [
        {
            "is_valid": True,
            "market": "1x2",
            "selection": selection,
            "decimal_odds": normalized_prices[selection],
            "snapshot_id": "calculation",
            "fixture_id": "calculation",
            "bookmaker": "calculation",
            "source": "calculation",
            "captured_at": "1970-01-01T00:00:00+00:00",
            "captured_at_parsed": parse_timestamp("1970-01-01T00:00:00+00:00"),
        }
        for selection in OUTCOMES
    ]
    result = devig_market(rows, market="1x2")
    if not result or not result.get("is_valid"):
        reason = (result or {}).get("invalid_reason") or "invalid_1x2_market"
        raise MarketPriorError(str(reason))
    return {
        "prices": normalized_prices,
        "raw_implied_probability": {
            selection: implied_probability(normalized_prices[selection])
            for selection in OUTCOMES
        },
        "market_margin": float(result["overround"]),
        "probabilities": _normalize_distribution(result["normalized_probabilities"]),
    }


def build_market_prior(
    fixture_id: str,
    prediction_cutoff_at: Any,
    odds_snapshots: Iterable[Mapping[str, Any]],
    *,
    config: MarketPriorConfig | None = None,
) -> dict[str, Any]:
    """Build one as-of 1X2 prior from each bookmaker's latest complete capture."""

    policy = config or MarketPriorConfig()
    fixture_key = str(fixture_id or "")
    cutoff = parse_timestamp(prediction_cutoff_at)
    if not fixture_key:
        raise MarketPriorError("fixture_id is required")
    if cutoff is None:
        raise MarketPriorError("prediction_cutoff_at is required and must be valid")

    candidates: list[dict[str, Any]] = []
    exclusions: list[dict[str, str]] = []
    for raw_snapshot in odds_snapshots or []:
        if not isinstance(raw_snapshot, Mapping):
            exclusions.append({"snapshot_id": "", "reason": "invalid_snapshot"})
            continue
        snapshot_id = str(raw_snapshot.get("id") or raw_snapshot.get("snapshot_id") or "")
        snapshot_fixture_id = str(raw_snapshot.get("fixture_id") or "")
        if not snapshot_id:
            exclusions.append({"snapshot_id": "", "reason": "missing_snapshot_id"})
            continue
        if snapshot_fixture_id != fixture_key:
            exclusions.append({"snapshot_id": snapshot_id, "reason": "fixture_id_mismatch"})
            continue
        quotes = raw_snapshot.get("quotes")
        if not isinstance(quotes, list) or not quotes:
            exclusions.append({"snapshot_id": snapshot_id, "reason": "missing_quotes"})
            continue
        captured_raw = raw_snapshot.get("captured_at") or next(
            (quote.get("captured_at") for quote in quotes if isinstance(quote, Mapping) and quote.get("captured_at")),
            None,
        )
        captured_at = parse_timestamp(captured_raw)
        if captured_at is None:
            exclusions.append({"snapshot_id": snapshot_id, "reason": "invalid_available_at"})
            continue
        # Future captures are outside the as-of input set. Do not include their
        # identities in the audit, so later ingestion cannot change old replay.
        if captured_at > cutoff:
            continue

        snapshot_source_updated_raw = raw_snapshot.get("source_updated_at")
        if snapshot_source_updated_raw not in (None, ""):
            snapshot_source_updated_at = parse_timestamp(snapshot_source_updated_raw)
            if snapshot_source_updated_at is None:
                exclusions.append({"snapshot_id": snapshot_id, "reason": "invalid_source_updated_at"})
                continue
            if snapshot_source_updated_at > cutoff:
                exclusions.append({"snapshot_id": snapshot_id, "reason": "future_source_updated_at"})
                continue

        normalized_rows: list[dict[str, Any]] = []
        invalid_reason: str | None = None
        for quote in quotes:
            if not isinstance(quote, Mapping):
                invalid_reason = "invalid_quote"
                break
            quote_source_updated_at = quote.get("source_updated_at")
            if quote_source_updated_at in (None, ""):
                quote_source_updated_at = snapshot_source_updated_raw
            row = normalize_quote(
                {
                    **raw_snapshot,
                    **quote,
                    "snapshot_id": snapshot_id,
                    "fixture_id": snapshot_fixture_id,
                    "captured_at": quote.get("captured_at") or captured_at.isoformat(),
                    "source_updated_at": quote_source_updated_at,
                }
            )
            if row.get("market") != "1x2":
                continue
            if row.get("selection") not in OUTCOMES:
                invalid_reason = "invalid_1x2_selection"
                break
            try:
                implied_probability(row.get("decimal_odds"))
            except MarketPriorError:
                invalid_reason = "invalid_decimal_odds"
                break
            quote_captured_at = row.get("captured_at_parsed")
            if quote_captured_at is None or quote_captured_at > cutoff:
                invalid_reason = "invalid_or_future_available_at"
                break
            source_updated_raw = row.get("source_updated_at")
            if source_updated_raw not in (None, ""):
                source_updated_at = parse_timestamp(source_updated_raw)
                if source_updated_at is None:
                    invalid_reason = "invalid_source_updated_at"
                    break
                if source_updated_at > cutoff:
                    invalid_reason = "future_source_updated_at"
                    break
            normalized_rows.append(row)
        if invalid_reason:
            exclusions.append({"snapshot_id": snapshot_id, "reason": invalid_reason})
            continue

        selections = [str(row.get("selection")) for row in normalized_rows]
        if len(normalized_rows) != len(OUTCOMES) or set(selections) != set(OUTCOMES):
            exclusions.append({"snapshot_id": snapshot_id, "reason": "incomplete_1x2_market"})
            continue
        source = str(normalized_rows[0].get("source") or "")
        bookmaker = str(normalized_rows[0].get("bookmaker") or "")
        if source.casefold() == "unknown" or bookmaker.casefold() == "unknown" or not source or not bookmaker:
            exclusions.append({"snapshot_id": snapshot_id, "reason": "missing_source_or_bookmaker"})
            continue
        if any(str(row.get("source") or "") != source or str(row.get("bookmaker") or "") != bookmaker for row in normalized_rows):
            exclusions.append({"snapshot_id": snapshot_id, "reason": "mixed_source_or_bookmaker"})
            continue
        prices = {str(row["selection"]): float(row["decimal_odds"]) for row in normalized_rows}
        try:
            devig = multiplicative_devig(prices)
        except MarketPriorError as error:
            exclusions.append({"snapshot_id": snapshot_id, "reason": str(error)})
            continue
        source_updates = [
            parse_timestamp(row.get("source_updated_at"))
            for row in normalized_rows
            if row.get("source_updated_at") not in (None, "")
        ]
        source_updated_at = max((item for item in source_updates if item is not None), default=None)
        candidates.append(
            {
                "snapshot_id": snapshot_id,
                "source": source,
                "bookmaker": bookmaker,
                "captured_at": captured_at.isoformat(),
                "captured_at_parsed": captured_at,
                "source_updated_at": source_updated_at.isoformat() if source_updated_at else None,
                "odds": devig["prices"],
                "raw_implied_probability": devig["raw_implied_probability"],
                "de_vig_probability": devig["probabilities"],
                "market_margin": devig["market_margin"],
            }
        )

    latest_by_bookmaker: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate in candidates:
        key = (candidate["source"].casefold(), candidate["bookmaker"].casefold())
        previous = latest_by_bookmaker.get(key)
        rank = (candidate["captured_at_parsed"], candidate["snapshot_id"])
        previous_rank = (
            (previous or {}).get("captured_at_parsed"),
            (previous or {}).get("snapshot_id", ""),
        )
        if previous is None or rank > previous_rank:
            latest_by_bookmaker[key] = candidate

    selected = sorted(
        latest_by_bookmaker.values(),
        key=lambda item: (item["source"].casefold(), item["bookmaker"].casefold(), item["snapshot_id"]),
    )
    superseded_snapshot_count = len(candidates) - len(selected)
    if not selected:
        return _unavailable_prior(
            fixture_key,
            cutoff.isoformat(),
            policy,
            exclusions,
            "no_complete_cutoff_safe_1x2_market",
        )

    averaged = {
        outcome: fmean(float(item["de_vig_probability"][outcome]) for item in selected)
        for outcome in OUTCOMES
    }
    probabilities = _normalize_distribution(averaged)
    margin = round(fmean(float(item["market_margin"]) for item in selected), 12)
    latest_capture = max(item["captured_at_parsed"] for item in selected)
    oldest_capture = min(item["captured_at_parsed"] for item in selected)
    public_selected = [
        {key: value for key, value in item.items() if key != "captured_at_parsed"}
        for item in selected
    ]
    prior_core = {
        "fixture_id": fixture_key,
        "prediction_cutoff_at": cutoff.isoformat(),
        "market": "1x2",
        "market_model_version": policy.market_model_version,
        "calculation_version": policy.calculation_version,
        "config_hash": policy.config_hash,
        "source_odds_snapshot_ids": [item["snapshot_id"] for item in public_selected],
        "probabilities": probabilities,
        "market_margin": margin,
    }
    prior_id = f"market-prior:{hashlib.sha256(_canonical_json(prior_core).encode()).hexdigest()[:32]}"
    return {
        "status": "available",
        "missing_reason": None,
        "market_prior_id": prior_id,
        **prior_core,
        "bookmaker_count": len(public_selected),
        "source_count": len({item["source"] for item in public_selected}),
        "eligible_snapshot_count": len(candidates),
        "superseded_snapshot_count": superseded_snapshot_count,
        "latest_available_at": latest_capture.isoformat(),
        "selected_bookmakers": public_selected,
        "excluded_snapshots": sorted(exclusions, key=lambda item: (item["snapshot_id"], item["reason"])),
        "quality": {
            "state": "PASS",
            "odds_completeness": "complete",
            "provider_available": True,
            "bookmaker_count": len(public_selected),
            "eligible_snapshot_count": len(candidates),
            "superseded_snapshot_count": superseded_snapshot_count,
            "freshness_seconds": {
                "newest": max(0.0, (cutoff - latest_capture).total_seconds()),
                "oldest": max(0.0, (cutoff - oldest_capture).total_seconds()),
            },
            "market_margin": margin,
        },
    }


def deterministic_fusion(
    model_probability: Mapping[str, Any],
    market_probability: Mapping[str, Any],
    *,
    config: MarketPriorConfig | None = None,
) -> dict[str, float]:
    """Fuse model and market once with the fixed published Round 5 weights."""

    policy = config or MarketPriorConfig()
    model = _validated_probability_distribution(model_probability)
    market = _validated_probability_distribution(market_probability)
    return _normalize_distribution(
        {
            outcome: policy.model_weight * model[outcome] + policy.market_weight * market[outcome]
            for outcome in OUTCOMES
        }
    )


class Round5ProbabilityEngine:
    """Combine one untouched Round 4 result with one cutoff-safe Market Prior."""

    def __init__(self, config: MarketPriorConfig | None = None) -> None:
        self.config = config or MarketPriorConfig()

    def calculate(
        self,
        round4_result: Mapping[str, Any],
        odds_snapshots: Iterable[Mapping[str, Any]],
        *,
        kickoff: Any = None,
    ) -> dict[str, Any]:
        if not isinstance(round4_result, Mapping):
            raise MarketPriorError("Round 4 result is required")
        if any(
            key in round4_result
            for key in ("round5_probability_audit", "fusion_version", "market_fusion_applied")
        ):
            raise MarketPriorError("Market Prior has already been applied to this probability payload")
        round4_audit = round4_result.get("probability_audit") or round4_result.get("audit")
        audit_checks = round4_audit.get("checks") if isinstance(round4_audit, Mapping) else None
        if not isinstance(audit_checks, Mapping) or audit_checks.get("market_independent") is not True:
            raise MarketPriorError("Round 4 probability must be explicitly market-independent")
        if audit_checks.get("no_ml") is not True:
            raise MarketPriorError("Round 4 probability must pass the no-ML audit")
        assert_v2_numeric_path_allowed(round4_result, source="round4-transparent-probability")

        fixture_id = str(round4_result.get("fixture_id") or round4_result.get("match_id") or "")
        cutoff = parse_timestamp(round4_result.get("prediction_cutoff_at"))
        if not fixture_id or cutoff is None:
            raise MarketPriorError("Round 4 fixture_id and prediction_cutoff_at are required")
        required_provenance = (
            "feature_snapshot_id",
            "probability_model_version",
            "calculation_version",
        )
        missing_provenance = [
            field for field in required_provenance if not round4_result.get(field)
        ]
        if missing_provenance:
            raise MarketPriorError(
                f"Round 4 provenance is missing {', '.join(missing_provenance)}"
            )
        model_probability = _validated_probability_distribution(
            round4_result.get("probabilities") or {}
        )
        prior = build_market_prior(
            fixture_id,
            cutoff,
            odds_snapshots,
            config=self.config,
        )
        kickoff_at = parse_timestamp(kickoff) if kickoff not in (None, "") else None
        if kickoff not in (None, "") and kickoff_at is None:
            prior = _disable_prior(prior, "invalid_kickoff")
        elif kickoff_at is not None and cutoff >= kickoff_at:
            prior = _disable_prior(prior, "prediction_cutoff_not_before_kickoff")

        fusion_applied = prior.get("status") == "available"
        if fusion_applied:
            final_probability = deterministic_fusion(
                model_probability,
                prior["probabilities"],
                config=self.config,
            )
            market_probability: dict[str, float] | None = dict(prior["probabilities"])
            market_status = "MODEL_PLUS_MARKET"
        else:
            final_probability = dict(model_probability)
            market_probability = None
            market_status = "MODEL_ONLY"

        audit_core = {
            "audit_version": AUDIT_VERSION,
            "fixture_id": fixture_id,
            "prediction_cutoff_at": cutoff.isoformat(),
            "feature_snapshot_id": round4_result.get("feature_snapshot_id"),
            "probability_model_version": round4_result.get("probability_model_version"),
            "probability_calculation_version": round4_result.get("calculation_version"),
            "market_prior_id": prior.get("market_prior_id"),
            "source_odds_snapshot_ids": prior.get("source_odds_snapshot_ids") or [],
            "market_model_version": self.config.market_model_version,
            "market_calculation_version": self.config.calculation_version,
            "fusion_version": self.config.fusion_version,
            "fusion_config_hash": self.config.config_hash,
            "fusion_weights": {
                "model": self.config.model_weight,
                "market": self.config.market_weight,
            },
            "model_probability": model_probability,
            "market_probability": market_probability,
            "final_probability": final_probability,
            "market_margin": prior.get("market_margin"),
            "market_status": market_status,
            "market_fusion_applied": fusion_applied,
            "market_fusion_count": 1 if fusion_applied else 0,
            "no_ml": True,
            "no_llm_numeric_probability": True,
            "reproducible": True,
            "created_at": cutoff.isoformat(),
        }
        snapshot_payload = {
            "snapshot_type": "round5_probability_audit",
            "audit": audit_core,
            "market_prior": prior,
        }
        snapshot_id = f"round5-market:{hashlib.sha256(_canonical_json(snapshot_payload).encode()).hexdigest()[:32]}"
        audit_core = {**audit_core, "market_snapshot_id": snapshot_id}
        snapshot_payload["audit"] = audit_core
        market_snapshot = {
            "market_snapshot_id": snapshot_id,
            "fixture_id": fixture_id,
            "market": "1x2",
            "captured_at": prior["latest_available_at"] if fusion_applied else cutoff.isoformat(),
            "overround": prior["market_margin"],
            "prediction_cutoff_at": cutoff.isoformat(),
            "market_model_version": self.config.market_model_version,
            "calculation_version": self.config.calculation_version,
            "fusion_version": self.config.fusion_version,
            "payload": snapshot_payload,
        }

        output = {
            "model_probability": model_probability,
            "market_prior": market_probability,
            "market_prior_detail": prior,
            "final_probability": final_probability,
            "market_status": market_status,
            "market_margin": prior.get("market_margin"),
            "market_model_version": self.config.market_model_version,
            "market_calculation_version": self.config.calculation_version,
            "fusion_version": self.config.fusion_version,
            "fusion_config": {
                "model_weight": self.config.model_weight,
                "market_weight": self.config.market_weight,
                "config_hash": self.config.config_hash,
                "policy": "fixed_not_historically_optimized",
            },
            "market_fusion_applied": fusion_applied,
            "round5_probability_audit": audit_core,
            "market_snapshot": market_snapshot,
        }
        assert_v2_numeric_path_allowed(output, source="round5-market-prior")
        return output


def persist_round5_market_snapshot(repository: Any, result: Mapping[str, Any]) -> str | None:
    """Persist the content-addressed Round 5 audit through the existing store."""

    record = result.get("market_snapshot") if isinstance(result, Mapping) else None
    saver = getattr(repository, "save_market_snapshot", None)
    if not isinstance(record, Mapping) or not callable(saver):
        return None
    saver(dict(record))
    return str(record["market_snapshot_id"])


def _validated_probability_distribution(values: Mapping[str, Any]) -> dict[str, float]:
    """Validate an already-normalized source without changing its probabilities."""

    if not isinstance(values, Mapping) or set(values) != set(OUTCOMES):
        raise MarketPriorError("probability distribution must contain home, draw, and away")
    result: dict[str, float] = {}
    for outcome in OUTCOMES:
        value = values[outcome]
        if isinstance(value, bool):
            raise MarketPriorError("probabilities must be finite and non-negative")
        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise MarketPriorError("probabilities must be finite and non-negative") from error
        if not math.isfinite(number) or number < 0:
            raise MarketPriorError("probabilities must be finite and non-negative")
        result[outcome] = number
    if not math.isclose(sum(result.values()), 1.0, abs_tol=1e-9):
        raise MarketPriorError("probability distribution must already sum to one")
    return result


def _normalize_distribution(values: Mapping[str, Any]) -> dict[str, float]:
    if not isinstance(values, Mapping) or set(values) != set(OUTCOMES):
        raise MarketPriorError("probability distribution must contain home, draw, and away")
    normalized_values: dict[str, float] = {}
    for outcome in OUTCOMES:
        value = values[outcome]
        if isinstance(value, bool):
            raise MarketPriorError("probabilities must be finite and non-negative")
        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise MarketPriorError("probabilities must be finite and non-negative") from error
        if not math.isfinite(number) or number < 0:
            raise MarketPriorError("probabilities must be finite and non-negative")
        normalized_values[outcome] = number
    total = sum(normalized_values.values())
    if not math.isfinite(total) or total <= 0:
        raise MarketPriorError("probability distribution cannot be normalized")
    result = {
        outcome: round(normalized_values[outcome] / total, 12)
        for outcome in OUTCOMES[:-1]
    }
    result[OUTCOMES[-1]] = round(1.0 - sum(result.values()), 12)
    if result[OUTCOMES[-1]] < 0:
        raise MarketPriorError("probability normalization produced a negative value")
    return result


def _unavailable_prior(
    fixture_id: str,
    cutoff: str,
    config: MarketPriorConfig,
    exclusions: list[dict[str, str]],
    reason: str,
) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "missing_reason": reason,
        "market_prior_id": None,
        "fixture_id": fixture_id,
        "prediction_cutoff_at": cutoff,
        "market": "1x2",
        "market_model_version": config.market_model_version,
        "calculation_version": config.calculation_version,
        "config_hash": config.config_hash,
        "source_odds_snapshot_ids": [],
        "probabilities": None,
        "market_margin": None,
        "bookmaker_count": 0,
        "source_count": 0,
        "eligible_snapshot_count": 0,
        "superseded_snapshot_count": 0,
        "latest_available_at": None,
        "selected_bookmakers": [],
        "excluded_snapshots": sorted(exclusions, key=lambda item: (item["snapshot_id"], item["reason"])),
        "quality": {
            "state": "UNAVAILABLE",
            "odds_completeness": "missing",
            "provider_available": False,
            "bookmaker_count": 0,
            "eligible_snapshot_count": 0,
            "superseded_snapshot_count": 0,
            "freshness_seconds": None,
            "market_margin": None,
        },
    }


def _disable_prior(prior: Mapping[str, Any], reason: str) -> dict[str, Any]:
    disabled = dict(prior)
    disabled.update(
        {
            "status": "unavailable",
            "missing_reason": reason,
            "market_prior_id": None,
            "source_odds_snapshot_ids": [],
            "probabilities": None,
            "market_margin": None,
            "bookmaker_count": 0,
            "source_count": 0,
            "eligible_snapshot_count": 0,
            "superseded_snapshot_count": 0,
            "selected_bookmakers": [],
            "quality": {
                **dict(prior.get("quality") or {}),
                "state": "UNAVAILABLE",
                "provider_available": False,
                "market_margin": None,
            },
        }
    )
    return disabled


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
