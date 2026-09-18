"""Pure deterministic probability metrics for Round 6 evaluation."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any


OUTCOMES: tuple[str, ...] = ("home", "draw", "away")
METRICS_VERSION = "round6-probability-metrics-v1"
LOG_LOSS_EPSILON = 1e-15
LOG_LOSS_EPSILON_VERSION = "round6-log-loss-epsilon-v1"
PROBABILITY_SUM_TOLERANCE = 1e-9
CALIBRATION_BIN_COUNT = 10
MIN_SAMPLES = 30
DEFAULT_MIN_SAMPLES = MIN_SAMPLES


class ProbabilityEvaluationError(ValueError):
    """Raised when an evaluation input is incomplete or invalid."""


def normalize_probability_vector(values: Mapping[str, Any]) -> dict[str, float]:
    """Validate a complete 1X2 vector and normalize only tiny sum drift."""

    if not isinstance(values, Mapping) or set(values) != set(OUTCOMES):
        raise ProbabilityEvaluationError(
            "probability vector must contain exactly home, draw, and away"
        )

    parsed: dict[str, float] = {}
    for outcome in OUTCOMES:
        value = values[outcome]
        if isinstance(value, (bool, str, bytes, bytearray)):
            raise ProbabilityEvaluationError(
                "probabilities must be finite numbers between zero and one"
            )
        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise ProbabilityEvaluationError(
                "probabilities must be finite numbers between zero and one"
            ) from error
        if not math.isfinite(number) or number < 0.0 or number > 1.0:
            raise ProbabilityEvaluationError(
                "probabilities must be finite numbers between zero and one"
            )
        parsed[outcome] = number

    total = math.fsum(parsed.values())
    if not math.isclose(
        total,
        1.0,
        rel_tol=0.0,
        abs_tol=PROBABILITY_SUM_TOLERANCE,
    ):
        raise ProbabilityEvaluationError(
            "probability vector must sum to one within the published tolerance"
        )
    return {outcome: parsed[outcome] / total for outcome in OUTCOMES}


class ProbabilityEvaluationService:
    """Calculate and aggregate descriptive 1X2 probability metrics."""

    def __init__(self, *, min_samples: int = DEFAULT_MIN_SAMPLES) -> None:
        if (
            isinstance(min_samples, bool)
            or not isinstance(min_samples, int)
            or min_samples <= 0
        ):
            raise ValueError("min_samples must be a positive integer")
        self.min_samples = min_samples

    @staticmethod
    def normalize(probabilities: Mapping[str, Any]) -> dict[str, float]:
        """Expose strict probability normalization for temporal consumers."""

        return normalize_probability_vector(probabilities)

    def score(
        self,
        probabilities: Mapping[str, Any],
        actual_outcome: str,
    ) -> dict[str, Any]:
        """Score one probability vector using the published metric contract."""

        return self.evaluate(probabilities, actual_outcome)

    def evaluate(
        self,
        probabilities: Mapping[str, Any],
        actual_outcome: str,
    ) -> dict[str, Any]:
        """Evaluate one already-produced probability vector against its result."""

        normalized = normalize_probability_vector(probabilities)
        actual = self._validate_outcome(actual_outcome)
        return self._score_normalized(normalized, actual)

    def aggregate(
        self,
        observations: Iterable[Mapping[str, Any]],
        *,
        probability_key: str = "probabilities",
        outcome_key: str = "actual_outcome",
    ) -> dict[str, Any]:
        """Aggregate strict observations without skipping or imputing rows."""

        prepared = self._prepare(
            observations,
            probability_key=probability_key,
            outcome_key=outcome_key,
        )
        return self._summarize_prepared(prepared)

    def summarize(
        self,
        rows: Iterable[tuple[Mapping[str, Any], str]],
    ) -> dict[str, Any]:
        """Aggregate ``(probability vector, outcome)`` pairs."""

        prepared = [
            (normalize_probability_vector(probabilities), self._validate_outcome(actual))
            for probabilities, actual in rows
        ]
        return self._summarize_prepared(prepared)

    def _summarize_prepared(
        self,
        prepared: list[tuple[dict[str, float], str]],
    ) -> dict[str, Any]:
        scores = [
            self._score_normalized(probabilities, actual)
            for probabilities, actual in prepared
        ]
        count = len(scores)
        return {
            "status": self._sample_status(count),
            "sample_count": count,
            "minimum_samples": self.min_samples,
            "metrics_version": METRICS_VERSION,
            "log_loss_epsilon": LOG_LOSS_EPSILON,
            "log_loss_epsilon_version": LOG_LOSS_EPSILON_VERSION,
            "log_loss": self._mean(scores, "log_loss"),
            "brier": self._mean(scores, "brier"),
            "rps": self._mean(scores, "rps"),
            "accuracy": self._mean(scores, "accuracy"),
            "calibration": self._calibration_from_prepared(prepared),
        }

    def calibration(
        self,
        observations: Iterable[Mapping[str, Any]],
        *,
        probability_key: str = "probabilities",
        outcome_key: str = "actual_outcome",
    ) -> dict[str, Any]:
        """Build ten-bin one-vs-rest reliability summaries for each outcome."""

        prepared = self._prepare(
            observations,
            probability_key=probability_key,
            outcome_key=outcome_key,
        )
        return self._calibration_from_prepared(prepared)

    @staticmethod
    def coverage(*, eligible_count: int, available_count: int) -> dict[str, Any]:
        """Describe layer availability without filling missing probabilities."""

        for name, value in (
            ("eligible_count", eligible_count),
            ("available_count", available_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if available_count > eligible_count:
            raise ValueError("available_count cannot exceed eligible_count")
        return {
            "eligible_count": eligible_count,
            "available_count": available_count,
            "missing_count": eligible_count - available_count,
            "coverage": (
                available_count / eligible_count if eligible_count else None
            ),
        }

    def _prepare(
        self,
        observations: Iterable[Mapping[str, Any]],
        *,
        probability_key: str,
        outcome_key: str,
    ) -> list[tuple[dict[str, float], str]]:
        prepared: list[tuple[dict[str, float], str]] = []
        for index, observation in enumerate(observations):
            if not isinstance(observation, Mapping):
                raise ProbabilityEvaluationError(
                    f"observation {index} must be a mapping"
                )
            if probability_key not in observation or outcome_key not in observation:
                raise ProbabilityEvaluationError(
                    f"observation {index} is missing evaluation fields"
                )
            prepared.append(
                (
                    normalize_probability_vector(observation[probability_key]),
                    self._validate_outcome(observation[outcome_key]),
                )
            )
        return prepared

    def _calibration_from_prepared(
        self,
        prepared: list[tuple[dict[str, float], str]],
    ) -> dict[str, Any]:
        bins_by_outcome: dict[str, list[dict[str, Any]]] = {}
        ece_by_outcome: dict[str, float | None] = {}
        sample_count = len(prepared)

        for outcome in OUTCOMES:
            working = [
                {"predicted_sum": 0.0, "actual_sum": 0.0, "sample_count": 0}
                for _ in range(CALIBRATION_BIN_COUNT)
            ]
            for probabilities, actual in prepared:
                probability = probabilities[outcome]
                bin_index = min(
                    CALIBRATION_BIN_COUNT - 1,
                    int(probability * CALIBRATION_BIN_COUNT),
                )
                bucket = working[bin_index]
                bucket["predicted_sum"] += probability
                bucket["actual_sum"] += 1.0 if actual == outcome else 0.0
                bucket["sample_count"] += 1

            clean_bins: list[dict[str, Any]] = []
            weighted_error = 0.0
            for index, bucket in enumerate(working):
                count = int(bucket["sample_count"])
                predicted_mean = (
                    bucket["predicted_sum"] / count if count else None
                )
                actual_frequency = bucket["actual_sum"] / count if count else None
                gap = (
                    actual_frequency - predicted_mean
                    if actual_frequency is not None and predicted_mean is not None
                    else None
                )
                if gap is not None and sample_count:
                    weighted_error += count / sample_count * abs(gap)
                clean_bins.append(
                    {
                        "bin_index": index,
                        "lower": index / CALIBRATION_BIN_COUNT,
                        "upper": (index + 1) / CALIBRATION_BIN_COUNT,
                        "sample_count": count,
                        "mean_predicted_probability": predicted_mean,
                        "actual_frequency": actual_frequency,
                        "gap": gap,
                    }
                )
            bins_by_outcome[outcome] = clean_bins
            ece_by_outcome[outcome] = weighted_error if sample_count else None

        outcome_errors = [
            value for value in ece_by_outcome.values() if value is not None
        ]
        return {
            "status": self._sample_status(sample_count),
            "sample_count": sample_count,
            "minimum_samples": self.min_samples,
            "bin_count": CALIBRATION_BIN_COUNT,
            "bins": bins_by_outcome,
            "ece_by_outcome": ece_by_outcome,
            "ece": (
                math.fsum(outcome_errors) / len(outcome_errors)
                if outcome_errors
                else None
            ),
        }

    @staticmethod
    def _validate_outcome(actual_outcome: Any) -> str:
        if actual_outcome not in OUTCOMES:
            raise ProbabilityEvaluationError(
                "actual_outcome must be home, draw, or away"
            )
        return str(actual_outcome)

    @staticmethod
    def _score_normalized(
        probabilities: Mapping[str, float],
        actual: str,
    ) -> dict[str, Any]:
        one_hot = {
            outcome: 1.0 if outcome == actual else 0.0
            for outcome in OUTCOMES
        }
        log_loss = -math.log(max(LOG_LOSS_EPSILON, probabilities[actual]))
        brier = math.fsum(
            (probabilities[outcome] - one_hot[outcome]) ** 2
            for outcome in OUTCOMES
        )
        probability_cumulative = 0.0
        outcome_cumulative = 0.0
        rps_terms: list[float] = []
        for outcome in OUTCOMES[:-1]:
            probability_cumulative += probabilities[outcome]
            outcome_cumulative += one_hot[outcome]
            rps_terms.append((probability_cumulative - outcome_cumulative) ** 2)
        rps = math.fsum(rps_terms) / (len(OUTCOMES) - 1)
        predicted = max(OUTCOMES, key=lambda outcome: probabilities[outcome])
        correct = predicted == actual
        return {
            "metrics_version": METRICS_VERSION,
            "log_loss_epsilon": LOG_LOSS_EPSILON,
            "log_loss_epsilon_version": LOG_LOSS_EPSILON_VERSION,
            "probabilities": dict(probabilities),
            "actual_outcome": actual,
            "predicted_outcome": predicted,
            "correct": correct,
            "log_loss": log_loss,
            "brier": brier,
            "rps": rps,
            "accuracy": 1.0 if correct else 0.0,
        }

    def _sample_status(self, sample_count: int) -> str:
        return "ok" if sample_count >= self.min_samples else "insufficient_data"

    @staticmethod
    def _mean(rows: list[Mapping[str, Any]], key: str) -> float | None:
        if not rows:
            return None
        return math.fsum(float(row[key]) for row in rows) / len(rows)


__all__ = [
    "CALIBRATION_BIN_COUNT",
    "DEFAULT_MIN_SAMPLES",
    "LOG_LOSS_EPSILON",
    "LOG_LOSS_EPSILON_VERSION",
    "METRICS_VERSION",
    "MIN_SAMPLES",
    "OUTCOMES",
    "PROBABILITY_SUM_TOLERANCE",
    "ProbabilityEvaluationError",
    "ProbabilityEvaluationService",
    "normalize_probability_vector",
]
