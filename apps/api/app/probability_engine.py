"""Deterministic, market-independent Round 4 probability calculations.

This module consumes only a persisted Round 3 Feature Snapshot.  It deliberately
does not call the legacy prediction/model-fitting paths, read odds, or ask an
LLM for numeric values.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from .no_ml_guard import NoMLNumericPathError, assert_v2_numeric_path_allowed
from .prediction import _dixon_coles_tau, _poisson
from .prediction_intelligence import parse_timestamp


PROBABILITY_MODEL_VERSION = "poisson-dc-v2.0.0"
CALCULATION_VERSION = "round4-probability-engine-v1"
FEATURE_VERSION = "round3-feature-engine-v2"
DEFAULT_MAX_GOALS = 10


class ProbabilityEngineError(ValueError):
    """Raised when a snapshot cannot safely produce a probability result."""


@dataclass(frozen=True)
class ProbabilityModelConfig:
    """Fixed, versioned parameters for the transparent calculation chain."""

    probability_model_version: str = PROBABILITY_MODEL_VERSION
    calculation_version: str = CALCULATION_VERSION
    feature_version: str = FEATURE_VERSION
    home_baseline_goals: float = 1.35
    away_baseline_goals: float = 1.10
    home_advantage_multiplier: float = 1.08
    elo_weight: float = 0.10
    fatigue_weight: float = 0.08
    strength_min: float = 0.67
    strength_max: float = 1.50
    raw_strength_min: float = 0.25
    raw_strength_max: float = 4.0
    player_impact_min: float = -0.20
    player_impact_max: float = 0.20
    lambda_min: float = 0.15
    lambda_max: float = 4.50
    dixon_coles_rho: float = -0.10
    max_goals: int = DEFAULT_MAX_GOALS

    def __post_init__(self) -> None:
        if self.home_baseline_goals <= 0 or self.away_baseline_goals <= 0:
            raise ValueError("goal baselines must be positive")
        if not 0 <= self.elo_weight <= 1 or not 0 <= self.fatigue_weight <= 1:
            raise ValueError("feature weights must be within [0, 1]")
        if self.strength_min <= 0 or self.strength_max < self.strength_min:
            raise ValueError("invalid strength bounds")
        if self.raw_strength_min <= 0 or self.raw_strength_max < self.raw_strength_min:
            raise ValueError("invalid raw strength bounds")
        if self.lambda_min <= 0 or self.lambda_max < self.lambda_min:
            raise ValueError("invalid lambda bounds")
        if not -0.2 <= self.dixon_coles_rho <= 0:
            raise ValueError("Dixon-Coles rho must be in the fixed safe range [-0.2, 0]")
        if self.max_goals < 2:
            raise ValueError("max_goals must leave room for low-score correction")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def config_hash(self) -> str:
        encoded = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")).encode()
        return f"config:{hashlib.sha256(encoded).hexdigest()[:24]}"


def poisson_goal_distribution(lam: float, *, max_goals: int = DEFAULT_MAX_GOALS) -> list[float]:
    """Return exact buckets 0..max_goals-1 and a max_goals+ tail bucket."""

    _validate_lambda(lam)
    if max_goals < 2:
        raise ValueError("max_goals must be at least 2")
    exact = [_poisson(lam, goals) for goals in range(max_goals)]
    tail = 1.0 - sum(exact)
    if tail < -1e-12:
        raise ProbabilityEngineError("Poisson tail became negative")
    exact.append(max(0.0, tail))
    total = sum(exact)
    if not math.isfinite(total) or total <= 0:
        raise ProbabilityEngineError("Poisson distribution is not normalizable")
    exact = [value / total for value in exact]
    exact[-1] = max(0.0, 1.0 - sum(exact[:-1]))
    return exact


def dixon_coles_correction(
    home_goals: int,
    away_goals: int,
    home_lambda: float,
    away_lambda: float,
    rho: float,
) -> float:
    """Return the fixed Dixon-Coles low-score multiplier.

    The final bucket is a tail bucket, so it is intentionally not corrected as
    though it represented one exact score.
    """

    _validate_lambda(home_lambda)
    _validate_lambda(away_lambda)
    try:
        rho_value = float(rho)
    except (TypeError, ValueError) as error:
        raise ProbabilityEngineError("Dixon-Coles rho must be numeric") from error
    if not math.isfinite(rho_value) or not -0.2 <= rho_value <= 0:
        raise ProbabilityEngineError("Dixon-Coles rho is outside the fixed safe range")
    if home_goals < 2 and away_goals < 2:
        factor = _dixon_coles_tau(home_goals, away_goals, home_lambda, away_lambda, rho_value)
    else:
        factor = 1.0
    if not math.isfinite(factor) or factor < 0:
        raise ProbabilityEngineError("Dixon-Coles correction produced a negative or invalid factor")
    return factor


def build_score_probability_matrix(
    home_lambda: float,
    away_lambda: float,
    *,
    rho: float = -0.10,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> list[dict[str, Any]]:
    """Build a normalized independent-Poisson x Dixon-Coles score matrix."""

    _validate_lambda(home_lambda)
    _validate_lambda(away_lambda)
    home_distribution = poisson_goal_distribution(home_lambda, max_goals=max_goals)
    away_distribution = poisson_goal_distribution(away_lambda, max_goals=max_goals)
    raw: list[dict[str, Any]] = []
    for home_goals, home_probability in enumerate(home_distribution):
        for away_goals, away_probability in enumerate(away_distribution):
            factor = dixon_coles_correction(
                home_goals,
                away_goals,
                home_lambda,
                away_lambda,
                rho,
            )
            raw.append(
                {
                    "home_goals": home_goals,
                    "away_goals": away_goals,
                    "home_goals_label": _goal_label(home_goals, max_goals),
                    "away_goals_label": _goal_label(away_goals, max_goals),
                    "probability": home_probability * away_probability * factor,
                    "dixon_coles_factor": factor,
                }
            )
    total = sum(float(item["probability"]) for item in raw)
    if not math.isfinite(total) or total <= 0:
        raise ProbabilityEngineError("Score matrix cannot be normalized")
    for item in raw:
        item["probability"] = float(item["probability"]) / total
    # Reconcile the last cell so serialized floating point values still sum to 1.
    subtotal = sum(float(item["probability"]) for item in raw[:-1])
    raw[-1]["probability"] = max(0.0, 1.0 - subtotal)
    if any(item["probability"] < 0 or not math.isfinite(item["probability"]) for item in raw):
        raise ProbabilityEngineError("Score matrix contains a negative or invalid probability")
    return raw


class TransparentProbabilityEngine:
    """Calculate all Round 4 probabilities from one immutable feature snapshot."""

    def __init__(self, config: ProbabilityModelConfig | None = None) -> None:
        self.config = config or ProbabilityModelConfig()

    def calculate(
        self,
        feature_snapshot: Mapping[str, Any],
        *,
        match_id: str | None = None,
        feature_snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        snapshot = _unwrap_snapshot(feature_snapshot)
        actual_snapshot_id = str(snapshot.get("snapshot_id") or snapshot.get("feature_snapshot_id") or "")
        if not actual_snapshot_id:
            raise ProbabilityEngineError("feature snapshot must contain a real feature_snapshot_id")
        if feature_snapshot_id not in (None, "") and str(feature_snapshot_id) != actual_snapshot_id:
            raise ProbabilityEngineError("feature_snapshot_id does not match snapshot")
        snapshot_id = actual_snapshot_id
        cutoff = parse_timestamp(snapshot.get("prediction_cutoff_at"))
        if cutoff is None:
            raise ProbabilityEngineError("prediction_cutoff_at is required and must be valid")
        fixture_id = str(snapshot.get("fixture_id") or snapshot.get("canonical_fixture_id") or "")
        requested_match_id = str(match_id or fixture_id)
        if not fixture_id or (match_id and requested_match_id not in {fixture_id, str(snapshot.get("canonical_fixture_id") or "")}):
            raise ProbabilityEngineError("feature snapshot does not belong to match_id")
        if snapshot.get("feature_version") != self.config.feature_version:
            raise ProbabilityEngineError("unsupported feature snapshot version")
        if snapshot.get("leakage_detected") is not False:
            raise ProbabilityEngineError("feature snapshot leakage_detected must be false")
        leakage_check = snapshot.get("leakage_check")
        if not isinstance(leakage_check, Mapping):
            raise ProbabilityEngineError("feature snapshot leakage audit is required")
        if leakage_check.get("passed") is not True:
            raise ProbabilityEngineError("feature snapshot leakage audit failed")
        if "status" in leakage_check and str(leakage_check.get("status") or "").upper() != "PASS":
            raise ProbabilityEngineError("feature snapshot leakage audit is not PASS")
        violations = leakage_check.get("violations")
        if not isinstance(violations, Sequence) or isinstance(violations, (str, bytes)) or violations:
            raise ProbabilityEngineError("feature snapshot leakage audit contains violations")
        rejected_future_fields = leakage_check.get("rejected_future_fields")
        if rejected_future_fields:
            raise ProbabilityEngineError("feature snapshot leakage audit contains rejected future fields")

        features = snapshot.get("features")
        if not isinstance(features, Sequence) or isinstance(features, (str, bytes)) or not features:
            raise ProbabilityEngineError("feature snapshot has no feature values")
        self._validate_feature_boundaries(features, cutoff)
        feature_index = self._index_features(features)
        inputs, quality = self._derive_expected_goals(feature_index)
        home_lambda, away_lambda = self._expected_goals(inputs)
        matrix = build_score_probability_matrix(
            home_lambda,
            away_lambda,
            rho=self.config.dixon_coles_rho,
            max_goals=self.config.max_goals,
        )
        probabilities = _aggregate_1x2(matrix)
        over_under = _aggregate_over_under(matrix, self.config.max_goals)
        btts = _aggregate_btts(matrix, self.config.max_goals)
        top_scores = sorted(matrix, key=lambda item: item["probability"], reverse=True)[:6]
        output = {
            "match_id": requested_match_id,
            "fixture_id": fixture_id,
            "prediction_cutoff_at": cutoff.isoformat(),
            "feature_snapshot_id": snapshot_id,
            "calculation_version": self.config.calculation_version,
            "probability_model_version": self.config.probability_model_version,
            "home_expected_goals": home_lambda,
            "away_expected_goals": away_lambda,
            "total_expected_goals": home_lambda + away_lambda,
            "lambda_home": home_lambda,
            "lambda_away": away_lambda,
            "expected_goals": {"home": home_lambda, "away": away_lambda, "total": home_lambda + away_lambda},
            "home_win_probability": probabilities["home"],
            "draw_probability": probabilities["draw"],
            "away_win_probability": probabilities["away"],
            "probabilities": dict(probabilities),
            "over_under_probabilities": over_under,
            "btts_probability": dict(btts),
            "btts_yes_probability": btts["yes"],
            "btts_no_probability": btts["no"],
            "score_probability_matrix": matrix,
            "score_matrix": matrix,
            "top_scorelines": [
                {
                    "home_goals": item["home_goals"],
                    "away_goals": item["away_goals"],
                    "probability": item["probability"],
                }
                for item in top_scores
            ],
            "model_input_quality": quality,
            "probability_explanation": self._explanation(inputs, quality, home_lambda, away_lambda),
        }
        output["probability_audit"] = self._audit(output, snapshot, cutoff, len(features))
        output["audit"] = output["probability_audit"]
        return output

    def _validate_feature_boundaries(self, features: Sequence[Any], cutoff: datetime) -> None:
        for row in features:
            if not isinstance(row, Mapping):
                raise ProbabilityEngineError("feature snapshot contains an invalid feature row")
            row_cutoff_raw = row.get("prediction_cutoff_at")
            if row_cutoff_raw in (None, ""):
                raise ProbabilityEngineError("feature row prediction_cutoff_at is required")
            row_cutoff = parse_timestamp(row_cutoff_raw)
            if row_cutoff is None or row_cutoff != cutoff:
                raise ProbabilityEngineError("feature row cutoff does not match snapshot cutoff")
            if row.get("feature_version") != self.config.feature_version:
                raise ProbabilityEngineError("feature row version does not match snapshot version")
            status = str(row.get("status") or "available").casefold()
            if status in {"future", "calculation_failed", "unverifiable"}:
                raise ProbabilityEngineError(f"feature row is not production-safe: {status}")
            available_raw = row.get("available_at")
            available_at = parse_timestamp(available_raw) if available_raw not in (None, "") else None
            if available_raw not in (None, "") and available_at is None:
                raise ProbabilityEngineError("feature available_at is invalid")
            if available_at is not None and available_at > cutoff:
                raise ProbabilityEngineError("feature available_at is after prediction cutoff")
            if row.get("feature_value") is not None and available_at is None and status not in {"missing", "unavailable"}:
                raise ProbabilityEngineError("non-missing feature has no available_at")

    @staticmethod
    def _index_features(features: Sequence[Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
        indexed: dict[tuple[str, str], Mapping[str, Any]] = {}
        for row in features:
            name = str(row.get("feature_name") or "")
            side = str(row.get("side") or "").casefold()
            if not name or side not in {"home", "away"}:
                continue
            indexed.setdefault((name, side), row)
        return indexed

    def _derive_expected_goals(
        self,
        index: Mapping[tuple[str, str], Mapping[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        values: dict[str, Any] = {}
        fallbacks: list[dict[str, Any]] = []
        valid_core = {"home": 0, "away": 0}
        quality_values: list[float] = []

        def read(name: str, side: str) -> float | None:
            row = index.get((name, side))
            if row is None:
                fallbacks.append({"feature": name, "side": side, "reason": "feature_missing"})
                return None
            raw = row.get("feature_value")
            status = str(row.get("status") or "available").casefold()
            try:
                value = float(raw)
            except (TypeError, ValueError):
                value = None
            if value is None or not math.isfinite(value) or status in {"missing", "unavailable"}:
                fallbacks.append({"feature": name, "side": side, "reason": row.get("missing_reason") or "feature_missing"})
                return None
            source = str(row.get("source") or "").casefold()
            if any(marker in source for marker in ("deepseek", "chatgpt", "openai", "llm", "learned", "fitted", "odds", "market")):
                raise NoMLNumericPathError(f"Round 4 feature source rejected: {source}")
            if name in {"attack_strength", "defense_strength"} and not self.config.raw_strength_min <= value <= self.config.raw_strength_max:
                fallbacks.append({"feature": name, "side": side, "reason": "feature_value_out_of_range"})
            elif name == "team_elo" and not 500 <= value <= 2500:
                fallbacks.append({"feature": name, "side": side, "reason": "feature_value_out_of_range"})
            elif name == "fatigue_score" and not 0 <= value <= 1:
                fallbacks.append({"feature": name, "side": side, "reason": "feature_value_out_of_range"})
            elif name == "player_impact" and not self.config.player_impact_min <= value <= self.config.player_impact_max:
                fallbacks.append({"feature": name, "side": side, "reason": "feature_value_out_of_range"})
            quality = row.get("quality_score")
            try:
                if quality is not None and math.isfinite(float(quality)):
                    quality_values.append(max(0.0, min(1.0, float(quality))))
            except (TypeError, ValueError):
                pass
            values[f"{side}_{name}"] = value
            if name in {"attack_strength", "defense_strength", "team_elo"}:
                valid_core[side] += 1
            return value

        for side in ("home", "away"):
            for name in ("attack_strength", "defense_strength", "team_elo", "fatigue_score", "player_impact"):
                read(name, side)
        if not valid_core["home"] or not valid_core["away"]:
            raise ProbabilityEngineError("insufficient critical feature evidence for both teams")
        quality_score = sum(quality_values) / len(quality_values) if quality_values else 0.0
        fallback_count = len(fallbacks)
        quality_state = "complete" if fallback_count == 0 else "degraded"
        if quality_score < 0.4 or (valid_core["home"] + valid_core["away"] < 2):
            quality_state = "insufficient"
        quality = {
            "state": quality_state,
            "score": round(max(0.0, quality_score - min(0.3, fallback_count * 0.03)), 6),
            "features_checked": 10,
            "fallbacks": fallbacks,
        }
        return values, quality

    def _expected_goals(self, values: Mapping[str, Any]) -> tuple[float, float]:
        def ratio(side: str, name: str) -> float:
            raw = values.get(f"{side}_{name}")
            if raw is None or not self.config.raw_strength_min <= raw <= self.config.raw_strength_max:
                return 1.0
            return _clamp(raw, self.config.strength_min, self.config.strength_max)

        def defense_factor(side: str) -> float:
            raw = values.get(f"{side}_defense_strength")
            if raw is None or not self.config.raw_strength_min <= raw <= self.config.raw_strength_max:
                return 1.0
            return _clamp(1.0 / raw, self.config.strength_min, self.config.strength_max)

        home_attack = ratio("home", "attack_strength")
        away_attack = ratio("away", "attack_strength")
        home_defense_for_opponent = defense_factor("home")
        away_defense_for_opponent = defense_factor("away")
        home_elo = _valid_elo(values.get("home_team_elo"))
        away_elo = _valid_elo(values.get("away_team_elo"))
        elo_delta = _clamp((home_elo - away_elo) / 400.0, -1.0, 1.0) if home_elo is not None and away_elo is not None else 0.0
        home_elo_factor = 1.0 + self.config.elo_weight * elo_delta
        away_elo_factor = 1.0 - self.config.elo_weight * elo_delta
        home_fatigue = _bounded_or_default(values.get("home_fatigue_score"), 0.0, 1.0, 0.0)
        away_fatigue = _bounded_or_default(values.get("away_fatigue_score"), 0.0, 1.0, 0.0)
        home_player = _bounded_or_default(values.get("home_player_impact"), self.config.player_impact_min, self.config.player_impact_max, 0.0)
        away_player = _bounded_or_default(values.get("away_player_impact"), self.config.player_impact_min, self.config.player_impact_max, 0.0)
        home_raw = (
            self.config.home_baseline_goals
            * self.config.home_advantage_multiplier
            * home_attack
            * away_defense_for_opponent
            * home_elo_factor
            * (1.0 - self.config.fatigue_weight * home_fatigue)
            * (1.0 + home_player)
        )
        away_raw = (
            self.config.away_baseline_goals
            * away_attack
            * home_defense_for_opponent
            * away_elo_factor
            * (1.0 - self.config.fatigue_weight * away_fatigue)
            * (1.0 + away_player)
        )
        return (
            round(_clamp(home_raw, self.config.lambda_min, self.config.lambda_max), 8),
            round(_clamp(away_raw, self.config.lambda_min, self.config.lambda_max), 8),
        )

    def _explanation(
        self,
        values: Mapping[str, Any],
        quality: Mapping[str, Any],
        home_lambda: float,
        away_lambda: float,
    ) -> dict[str, Any]:
        return {
            "source": "feature_snapshot_only",
            "formula": "lambda_home=1.35*1.08*attack_home*inverse(defense_away)*elo_home_factor*fatigue_home_factor*player_home_factor; lambda_away=1.10*attack_away*inverse(defense_home)*elo_away_factor*fatigue_away_factor*player_away_factor",
            "steps": [
                "read cutoff-safe attack, defense, Elo, fatigue and player features",
                "apply fixed bounds and explicit neutral fallbacks",
                "calculate expected goals",
                "apply independent Poisson buckets and fixed Dixon-Coles low-score correction",
                "normalize the score matrix and aggregate 1X2, O/U and BTTS",
            ],
            "inputs": dict(values),
            "outputs": {"home_expected_goals": home_lambda, "away_expected_goals": away_lambda},
            "quality": dict(quality),
            "market_independent": True,
            "llm_numeric": False,
        }

    def _audit(
        self,
        output: Mapping[str, Any],
        snapshot: Mapping[str, Any],
        cutoff: datetime,
        features_checked: int,
    ) -> dict[str, Any]:
        assert_v2_numeric_path_allowed(
            {"engine": "transparent-probability-engine", "model_version": self.config.probability_model_version},
            source="feature_snapshot",
        )
        matrix_total = sum(float(row["probability"]) for row in output["score_probability_matrix"])
        one_x_two_total = sum(float(output[key]) for key in ("home_win_probability", "draw_probability", "away_win_probability"))
        return {
            "status": "PASS",
            "match_id": output["match_id"],
            "prediction_cutoff_at": cutoff.isoformat(),
            "feature_snapshot_id": output["feature_snapshot_id"],
            "probability_model_version": self.config.probability_model_version,
            "calculation_version": self.config.calculation_version,
            "config_hash": self.config.config_hash,
            "lambda_home": output["home_expected_goals"],
            "lambda_away": output["away_expected_goals"],
            "home_win_probability": output["home_win_probability"],
            "draw_probability": output["draw_probability"],
            "away_win_probability": output["away_win_probability"],
            "features_checked": features_checked,
            "violations": [],
            "checks": {
                "score_matrix_sum": matrix_total,
                "one_x_two_sum": one_x_two_total,
                "market_independent": True,
                "no_ml": True,
            },
            # Use the immutable snapshot timestamp for deterministic replay.
            "created_at": str(snapshot.get("computed_at") or cutoff.isoformat()),
        }


def _aggregate_1x2(matrix: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    result = {
        "home": sum(float(item["probability"]) for item in matrix if item["home_goals"] > item["away_goals"]),
        "draw": sum(float(item["probability"]) for item in matrix if item["home_goals"] == item["away_goals"]),
        "away": sum(float(item["probability"]) for item in matrix if item["home_goals"] < item["away_goals"]),
    }
    total = sum(result.values())
    if not math.isfinite(total) or total <= 0:
        raise ProbabilityEngineError("1X2 probabilities cannot be normalized")
    return {key: value / total for key, value in result.items()}


def _aggregate_over_under(matrix: Sequence[Mapping[str, Any]], max_goals: int) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for line in (0.5, 1.5, 2.5, 3.5):
        over = sum(
            float(item["probability"])
            for item in matrix
            if _bucket_total(item, max_goals) > line
        )
        result[str(line)] = {"over": over, "under": max(0.0, 1.0 - over)}
    return result


def _aggregate_btts(matrix: Sequence[Mapping[str, Any]], max_goals: int) -> dict[str, float]:
    yes = sum(
        float(item["probability"])
        for item in matrix
        if _bucket_positive(item["home_goals"], max_goals) and _bucket_positive(item["away_goals"], max_goals)
    )
    return {"yes": yes, "no": max(0.0, 1.0 - yes)}


def _bucket_total(item: Mapping[str, Any], max_goals: int) -> int:
    home = max_goals if int(item["home_goals"]) == max_goals else int(item["home_goals"])
    away = max_goals if int(item["away_goals"]) == max_goals else int(item["away_goals"])
    return home + away


def _bucket_positive(value: Any, max_goals: int) -> bool:
    return int(value) > 0 or int(value) == max_goals


def _unwrap_snapshot(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = snapshot.get("feature_snapshot") if isinstance(snapshot, Mapping) else None
    return nested if isinstance(nested, Mapping) else snapshot


def _goal_label(value: int, max_goals: int) -> str:
    return f"{max_goals}+" if value == max_goals else str(value)


def _validate_lambda(value: Any) -> None:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as error:
        raise ProbabilityEngineError("expected goals must be numeric") from error
    if not math.isfinite(numeric) or numeric < 0:
        raise ProbabilityEngineError("expected goals must be finite and non-negative")


def _valid_elo(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) and 500 <= numeric <= 2500 else None


def _bounded_or_default(value: Any, lower: float, upper: float, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(numeric) or numeric < lower or numeric > upper:
        return default
    return numeric


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


__all__ = [
    "CALCULATION_VERSION",
    "FEATURE_VERSION",
    "PROBABILITY_MODEL_VERSION",
    "ProbabilityEngineError",
    "ProbabilityModelConfig",
    "TransparentProbabilityEngine",
    "build_score_probability_matrix",
    "dixon_coles_correction",
    "poisson_goal_distribution",
]
