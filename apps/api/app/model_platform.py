"""P10 unified model platform: one interface over all model families.

Adapters wrap the existing prediction chain without rewriting it. Every
model returns the same result type with explicit readiness and failure
states — a model that cannot produce a prediction never borrows another
model's output. Ensemble weights are learned on the training split only;
calibration is fitted on the validation split only; the test split is
used exclusively for final evaluation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .elo import HOME_ADVANTAGE, INITIAL_RATING, expected_goal_shift
from .model_registry import dataset_fingerprint
from .prediction_intelligence import (
    CALIBRATION_VERSION,
    ENSEMBLE_VERSION,
    FEATURE_VERSION,
    PROBABILITY_KEYS,
    apply_temperature,
    evaluate_probabilities,
    fit_temperature,
    normalize_probabilities,
    split_time_ordered,
)

POISSON_V2_VERSION = "poisson-v2"
DIXON_COLES_VERSION = "dixon-coles-v1"
ELO_PRIOR_VERSION = "elo-prior-v1"
BASELINE_VERSION = "baseline-market-devig-v1"
LLM_CONTRACT_VERSION = "p10-llm-v1"
MAX_GOALS = 8
DEFAULT_DIXON_COLES_RHO = -0.10
# Base goal rates for the Elo prior before the rating shift is applied.
ELO_BASE_HOME_XG = 1.35
ELO_BASE_AWAY_XG = 1.15


@dataclass(frozen=True)
class ModelPrediction:
    """Unified model output with explicit readiness and failure states."""

    model_key: str
    model_version: str
    probabilities: Mapping[str, float] | None
    readiness: str = "ready"
    confidence: float | None = None
    failure_reason: str | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.readiness == "ready" and self.probabilities is not None

    @classmethod
    def not_ready(cls, model_key: str, model_version: str, reason: str, provenance: Mapping[str, Any] | None = None) -> "ModelPrediction":
        return cls(model_key, model_version, None, readiness="insufficient_evidence", failure_reason=reason, provenance=provenance or {})

    @classmethod
    def failed(cls, model_key: str, model_version: str, reason: str, provenance: Mapping[str, Any] | None = None) -> "ModelPrediction":
        return cls(model_key, model_version, None, readiness="failed", failure_reason=reason, provenance=provenance or {})


def _poisson_matrix_probabilities(home_xg: float, away_xg: float, rho: float = 0.0) -> dict[str, float]:
    """1X2 probabilities from a (optionally Dixon-Coles corrected) Poisson matrix."""

    if not all(math.isfinite(value) and value > 0 for value in (home_xg, away_xg)):
        raise ValueError("expected goals must be positive finite numbers")

    def poisson(lam: float, goals: int) -> float:
        return math.exp(-lam) * lam**goals / math.factorial(goals)

    def tau(home_goals: int, away_goals: int) -> float:
        if rho == 0.0:
            return 1.0
        if home_goals == 0 and away_goals == 0:
            return 1.0 - home_xg * away_xg * rho
        if home_goals == 0 and away_goals == 1:
            return 1.0 + home_xg * rho
        if home_goals == 1 and away_goals == 0:
            return 1.0 + away_xg * rho
        if home_goals == 1 and away_goals == 1:
            return 1.0 - rho
        return 1.0

    matrix: list[tuple[int, int, float]] = []
    for home in range(MAX_GOALS):
        for away in range(MAX_GOALS):
            matrix.append((home, away, poisson(home_xg, home) * poisson(away_xg, away) * max(0.0, tau(home, away))))
    total = sum(probability for _, _, probability in matrix)
    home_probability = sum(probability for home, away, probability in matrix if home > away) / total
    draw_probability = sum(probability for home, away, probability in matrix if home == away) / total
    return {
        "home": round(home_probability, 6),
        "draw": round(draw_probability, 6),
        "away": round(max(0.0, 1.0 - home_probability - draw_probability), 6),
    }


def _context_xg(context: Mapping[str, Any]) -> tuple[float, float] | None:
    xg = context.get("expected_goals")
    if not isinstance(xg, Mapping):
        return None
    try:
        home_xg = float(xg.get("home"))
        away_xg = float(xg.get("away"))
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(home_xg) and math.isfinite(away_xg) and home_xg > 0 and away_xg > 0):
        return None
    return home_xg, away_xg


class PoissonModel:
    """Independent-Poisson family over explicit expected goals."""

    model_key = "poisson"
    model_version = POISSON_V2_VERSION

    def predict(self, context: Mapping[str, Any]) -> ModelPrediction:
        xg = _context_xg(context)
        if xg is None:
            return ModelPrediction.not_ready(self.model_key, self.model_version, "missing expected_goals context")
        home_xg, away_xg = xg
        return ModelPrediction(
            self.model_key,
            self.model_version,
            _poisson_matrix_probabilities(home_xg, away_xg, rho=0.0),
            provenance={"feature_version": FEATURE_VERSION, "inputs": {"expected_goals": {"home": home_xg, "away": away_xg}}},
        )


class DixonColesModel(PoissonModel):
    """Poisson with the low-score correlation correction."""

    model_key = "dixon_coles"
    model_version = DIXON_COLES_VERSION
    rho = DEFAULT_DIXON_COLES_RHO

    def predict(self, context: Mapping[str, Any]) -> ModelPrediction:
        base = super().predict(context)
        if not base.ok:
            return ModelPrediction.not_ready(self.model_key, self.model_version, base.failure_reason or "not ready")
        xg = _context_xg(context) or (0.0, 0.0)
        return ModelPrediction(
            self.model_key,
            self.model_version,
            _poisson_matrix_probabilities(xg[0], xg[1], rho=self.rho),
            provenance={"feature_version": FEATURE_VERSION, "rho": self.rho, "inputs": {"expected_goals": {"home": xg[0], "away": xg[1]}}},
        )


class EloModel:
    """Elo rating differential converted into a Poisson prior."""

    model_key = "elo"
    model_version = ELO_PRIOR_VERSION

    def predict(self, context: Mapping[str, Any]) -> ModelPrediction:
        ratings = context.get("elo_ratings")
        fixture = context.get("fixture") or {}
        home_name = str(((fixture.get("home_team") or {}).get("name")) or "")
        away_name = str(((fixture.get("away_team") or {}).get("name")) or "")
        if not isinstance(ratings, Mapping) or home_name not in ratings or away_name not in ratings:
            return ModelPrediction.not_ready(self.model_key, self.model_version, "missing Elo ratings for both teams")
        home_xg, away_xg = expected_goal_shift(float(ratings[home_name]), float(ratings[away_name]))
        home_xg = min(3.2, max(0.35, ELO_BASE_HOME_XG + home_xg))
        away_xg = min(2.8, max(0.3, ELO_BASE_AWAY_XG + away_xg))
        return ModelPrediction(
            self.model_key,
            self.model_version,
            _poisson_matrix_probabilities(home_xg, away_xg, rho=0.0),
            provenance={
                "feature_version": FEATURE_VERSION,
                "home_advantage": HOME_ADVANTAGE,
                "initial_rating": INITIAL_RATING,
                "inputs": {"expected_goals": {"home": round(home_xg, 4), "away": round(away_xg, 4)}},
            },
        )


class BaselineModel:
    """De-vig market prior; refuses to guess without real odds."""

    model_key = "baseline"
    model_version = BASELINE_VERSION

    def predict(self, context: Mapping[str, Any]) -> ModelPrediction:
        odds = context.get("odds")
        prices = {}
        if isinstance(odds, Mapping):
            for key in PROBABILITY_KEYS:
                try:
                    value = float(odds.get(key))
                except (TypeError, ValueError):
                    value = 0.0
                if value > 1.0:
                    prices[key] = value
        if len(prices) != len(PROBABILITY_KEYS):
            return ModelPrediction.not_ready(self.model_key, self.model_version, "missing 1X2 market odds")
        implied = {key: 1.0 / value for key, value in prices.items()}
        total = sum(implied.values())
        probabilities = {key: round(value / total, 6) for key, value in implied.items()}
        return ModelPrediction(
            self.model_key,
            self.model_version,
            probabilities,
            provenance={"feature_version": FEATURE_VERSION, "inputs": {"odds": prices, "bookmaker_margin": round(total - 1.0, 6)}},
        )


class LlmModelAdapter:
    """Wrap one stored LLM prediction payload under the unified contract.

    The payload must carry the structured schema fields; anything else is
    an explicit failure for this model only. It never substitutes another
    model's probabilities.
    """

    def __init__(self, model_key: str) -> None:
        self.model_key = model_key
        self.model_version = LLM_CONTRACT_VERSION

    def predict(self, context: Mapping[str, Any]) -> ModelPrediction:
        payload = context.get("prediction_payload")
        if not isinstance(payload, Mapping) or not payload:
            return ModelPrediction.not_ready(self.model_key, self.model_version, "no stored prediction payload")
        probabilities = normalize_probabilities(payload.get("probabilities") or payload.get("model_probabilities"))
        model_version = str(payload.get("model_version") or "")
        summary = str(payload.get("analysis_summary") or "")
        if probabilities is None:
            return ModelPrediction.failed(
                self.model_key,
                model_version or self.model_version,
                "LLM payload probabilities missing or invalid (schema failure)",
                provenance={"prompt_version": payload.get("prompt_version")},
            )
        if not model_version or not summary:
            return ModelPrediction.failed(
                self.model_key,
                self.model_version,
                "LLM payload missing model_version or analysis_summary (schema failure)",
            )
        confidence = None
        try:
            confidence = float(payload.get("forecast_confidence"))
        except (TypeError, ValueError):
            confidence = None
        return ModelPrediction(
            self.model_key,
            model_version,
            probabilities,
            confidence=confidence,
            provenance={
                "feature_version": FEATURE_VERSION,
                "prompt_version": payload.get("prompt_version"),
                "predicted_outcome": payload.get("predicted_outcome"),
                "risk_factors": list(payload.get("risk_factors") or []),
            },
        )


class EnsembleModel:
    """Combine member models with explicit weights; missing members shrink out."""

    model_key = "ensemble"
    model_version = ENSEMBLE_VERSION

    def __init__(self, members: Sequence[Any], weights: Mapping[str, float]) -> None:
        self.members = tuple(members)
        self.weights = {key: max(0.0, float(value)) for key, value in weights.items()}

    def predict(self, context: Mapping[str, Any]) -> ModelPrediction:
        available: dict[str, ModelPrediction] = {}
        for member in self.members:
            result = member.predict(context)
            if result.ok:
                available[result.model_key] = result
        total = sum(self.weights.get(key, 0.0) for key in available)
        if not available or total <= 0:
            return ModelPrediction.not_ready(
                self.model_key,
                self.model_version,
                "no member model produced a prediction",
                provenance={"weights": dict(self.weights)},
            )
        probabilities = {
            key: round(
                sum(available[model].probabilities[key] * self.weights.get(model, 0.0) for model in available) / total,
                6,
            )
            for key in PROBABILITY_KEYS
        }
        probabilities = normalize_probabilities(probabilities) or probabilities
        return ModelPrediction(
            self.model_key,
            self.model_version,
            probabilities,
            provenance={
                "feature_version": FEATURE_VERSION,
                "members": {model: result.model_version for model, result in available.items()},
                "effective_weights": {model: round(self.weights.get(model, 0.0) / total, 6) for model in available},
            },
        )


class CalibratedEnsembleModel:
    """Ensemble plus validation-fitted temperature; calibration is explicit."""

    model_key = "calibrated_ensemble"
    model_version = f"{ENSEMBLE_VERSION}+{CALIBRATION_VERSION}"

    def __init__(self, ensemble: EnsembleModel, temperature: float) -> None:
        if not temperature or temperature <= 0:
            raise ValueError("temperature must be a positive fitted value")
        self.ensemble = ensemble
        self.temperature = float(temperature)

    def predict(self, context: Mapping[str, Any]) -> ModelPrediction:
        base = self.ensemble.predict(context)
        if not base.ok:
            return ModelPrediction.not_ready(self.model_key, self.model_version, base.failure_reason or "ensemble not ready")
        return ModelPrediction(
            self.model_key,
            self.model_version,
            apply_temperature(base.probabilities or {}, self.temperature),
            provenance={
                **base.provenance,
                "calibration_version": CALIBRATION_VERSION,
                "temperature": self.temperature,
            },
        )


def learn_ensemble_weights(
    train_rows: Iterable[Mapping[str, Any]],
    model_keys: Iterable[str],
) -> dict[str, float]:
    """Learn inverse-Brier weights from the training split only.

    Rows carry ``models``: {model_key: probabilities} plus
    ``actual_outcome``. Models without training rows get zero weight.
    """

    errors: dict[str, list[float]] = {}
    for row in train_rows:
        models = row.get("models") if isinstance(row.get("models"), Mapping) else {}
        actual = row.get("actual_outcome")
        if actual not in PROBABILITY_KEYS:
            continue
        for model_key in model_keys:
            probabilities = normalize_probabilities(models.get(model_key))
            if probabilities is None:
                continue
            brier = sum((probabilities[key] - (1.0 if key == actual else 0.0)) ** 2 for key in PROBABILITY_KEYS)
            errors.setdefault(model_key, []).append(brier)
    weights = {
        model_key: round(1.0 / max(1e-9, sum(values) / len(values)), 8)
        for model_key, values in errors.items()
        if values
    }
    return weights


def _ensemble_row_probabilities(row: Mapping[str, Any], weights: Mapping[str, float]) -> dict[str, float] | None:
    models = row.get("models") if isinstance(row.get("models"), Mapping) else {}
    available = {
        model_key: probabilities
        for model_key in weights
        if (probabilities := normalize_probabilities(models.get(model_key))) is not None
    }
    total = sum(weights.get(model_key, 0.0) for model_key in available)
    if not available or total <= 0:
        return None
    probabilities = {
        key: sum(available[model][key] * weights.get(model, 0.0) for model in available) / total
        for key in PROBABILITY_KEYS
    }
    return normalize_probabilities(probabilities)


def run_model_protocol(
    rows: Iterable[Mapping[str, Any]],
    model_keys: Iterable[str],
    *,
    calibration_reader: Any = None,
) -> dict[str, Any]:
    """Train/validation/test protocol: weights from train, calibration from
    validation, final metrics from test. The test labels never touch the
    weights or the temperature."""

    rows = [dict(row) for row in rows if isinstance(row, Mapping)]
    model_keys = tuple(model_keys)
    if not rows:
        return {
            "status": "insufficient_sample",
            "dataset_fingerprint": dataset_fingerprint([]),
            "weights": {},
            "temperature": None,
            "metrics": {},
            "splits": {"train": 0, "validation": 0, "test": 0},
        }
    train, validation, test = split_time_ordered(rows)
    weights = learn_ensemble_weights(train, model_keys)
    temperature_result = fit_temperature(
        validation,
        probability_reader=lambda row: _ensemble_row_probabilities(row, weights),
    )
    temperature = temperature_result.get("temperature")
    metrics: dict[str, Any] = {}
    for model_key in model_keys:
        metrics[model_key] = evaluate_probabilities(
            test,
            lambda row, key=model_key: normalize_probabilities((row.get("models") or {}).get(key)),
        )
    ensemble_metrics = evaluate_probabilities(test, lambda row: _ensemble_row_probabilities(row, weights))
    metrics["ensemble"] = ensemble_metrics
    if temperature:
        metrics["calibrated_ensemble"] = evaluate_probabilities(
            test,
            lambda row: (
                apply_temperature(candidates, temperature)
                if (candidates := _ensemble_row_probabilities(row, weights))
                else None
            ),
        )
        metrics["calibrated_ensemble"]["calibration_status"] = "ok"
    else:
        metrics["calibrated_ensemble"] = {"status": "insufficient_sample", "calibration_status": "calibration_unavailable"}
    return {
        "status": "ok",
        "dataset_fingerprint": dataset_fingerprint(rows),
        "feature_version": FEATURE_VERSION,
        "ensemble_version": ENSEMBLE_VERSION,
        "calibration_version": CALIBRATION_VERSION,
        "weights": weights,
        "temperature": temperature,
        "temperature_fit": {
            "sample_size": temperature_result.get("sample_size"),
            "status": temperature_result.get("status"),
        },
        "metrics": metrics,
        "splits": {"train": len(train), "validation": len(validation), "test": len(test)},
    }
