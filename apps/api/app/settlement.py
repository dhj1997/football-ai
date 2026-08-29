"""Idempotent final-score settlement and prediction performance metrics."""

import uuid
import math
from datetime import UTC, datetime
from typing import Any

from .prediction import settle_asian_handicap
from .prompt_contract import DEFAULT_PROMPT_CONTRACT


QUALITY_POLICY = {
    "min_settled_fixtures": 20,
    "min_prediction_samples": 20,
    "min_market_comparison_samples": 20,
    "min_clv_samples": 10,
    "min_roi": 0.0,
    "min_average_clv": 0.0,
    "min_brier_improvement_vs_market": 0.0,
    "max_drawdown": 0.30,
}
CALIBRATION_BIN_COUNT = 10
MIN_CALIBRATION_SAMPLES = 30


def calculate_clv(bet_odds: Any, closing_odds: Any) -> float | None:
    """Calculate decimal-odds CLV without using model probabilities."""

    try:
        bet_price = float(bet_odds)
        close_price = float(closing_odds)
    except (TypeError, ValueError):
        return None
    if bet_price <= 0 or close_price <= 0:
        return None
    return round(bet_price / close_price - 1.0, 4)


def calculate_calibration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build ten-bin one-vs-rest calibration reports for home/draw/away."""

    outcomes = ("home", "draw", "away")
    bins_by_outcome: dict[str, list[dict[str, Any]]] = {}
    ece: dict[str, float | None] = {}
    for outcome in outcomes:
        bins = [
            {
                "bin": f"{index / CALIBRATION_BIN_COUNT:.1f}-{(index + 1) / CALIBRATION_BIN_COUNT:.1f}",
                "lower": round(index / CALIBRATION_BIN_COUNT, 1),
                "upper": round((index + 1) / CALIBRATION_BIN_COUNT, 1),
                "sample_count": 0,
                "_predicted_sum": 0.0,
                "_actual_sum": 0.0,
            }
            for index in range(CALIBRATION_BIN_COUNT)
        ]
        for row in rows:
            probabilities = _forecast_probabilities(row)
            try:
                probability = min(1.0, max(0.0, float(probabilities.get(outcome))))
            except (TypeError, ValueError):
                continue
            index = min(CALIBRATION_BIN_COUNT - 1, int(probability * CALIBRATION_BIN_COUNT))
            bucket = bins[index]
            bucket["sample_count"] += 1
            bucket["_predicted_sum"] += probability
            bucket["_actual_sum"] += 1.0 if row.get("actual_outcome") == outcome else 0.0
        total = sum(int(bucket["sample_count"]) for bucket in bins)
        clean_bins: list[dict[str, Any]] = []
        weighted_error = 0.0
        for bucket in bins:
            count = int(bucket.pop("sample_count"))
            predicted = bucket.pop("_predicted_sum")
            actual = bucket.pop("_actual_sum")
            average = predicted / count if count else None
            frequency = actual / count if count else None
            gap = frequency - average if average is not None and frequency is not None else None
            if gap is not None and total:
                weighted_error += count / total * abs(gap)
            clean_bins.append(
                {
                    **bucket,
                    "sample_count": count,
                    "average_predicted_probability": round(average, 4) if average is not None else None,
                    "actual_frequency": round(frequency, 4) if frequency is not None else None,
                    "calibration_gap": round(gap, 4) if gap is not None else None,
                }
            )
        bins_by_outcome[outcome] = clean_bins
        ece[outcome] = round(weighted_error, 4) if total else None
    status = "ok" if len(rows) >= MIN_CALIBRATION_SAMPLES else "insufficient_sample"
    return {
        "sample_size": len(rows),
        "status": status,
        "minimum_samples": MIN_CALIBRATION_SAMPLES,
        "bins": bins_by_outcome,
        "home": bins_by_outcome["home"],
        "draw": bins_by_outcome["draw"],
        "away": bins_by_outcome["away"],
        "ece": ece,
    }


calibration_report = calculate_calibration


def _metric_summary(
    rows: list[dict[str, Any]],
    probability_reader: Any,
) -> dict[str, Any]:
    valid = [
        row
        for row in rows
        if set(probability_reader(row) or {}) >= {"home", "draw", "away"}
    ]
    if not valid:
        return {
            "samples": 0,
            "accuracy": None,
            "brier": None,
            "log_loss": None,
            "rps": None,
            "ece": None,
            "calibration": calculate_calibration([]),
        }
    probabilities = [probability_reader(row) for row in valid]
    accuracy = sum(
        max(item, key=item.get) == row.get("actual_outcome")
        for row, item in zip(valid, probabilities)
    ) / len(valid)
    brier = sum(_brier(item, row["actual_outcome"]) for row, item in zip(valid, probabilities)) / len(valid)
    log_loss = sum(_log_loss(item, row["actual_outcome"]) for row, item in zip(valid, probabilities)) / len(valid)
    rps = sum(_rps(item, row["actual_outcome"]) for row, item in zip(valid, probabilities)) / len(valid)
    calibration_rows = [
        {"model_probabilities": item, "actual_outcome": row["actual_outcome"]}
        for row, item in zip(valid, probabilities)
    ]
    calibration = calculate_calibration(calibration_rows)
    return {
        "samples": len(valid),
        "accuracy": round(accuracy, 4),
        "brier": round(brier, 4),
        "log_loss": round(log_loss, 4),
        "rps": round(rps, 4),
        "ece": round(sum(value for value in calibration["ece"].values() if value is not None) / 3, 4),
        "calibration": calibration,
    }


class SettlementService:
    def __init__(self, repository: Any, competition_id: str | None = None) -> None:
        self.repository = repository
        self.competition_id = competition_id

    def settle_fixture(self, fixture: dict[str, Any]) -> dict[str, Any]:
        score = fixture.get("score") or {}
        if fixture.get("status") != "finished" or score.get("home") is None or score.get("away") is None:
            raise ValueError("Fixture does not have a final score")
        home_score = int(score["home"])
        away_score = int(score["away"])
        actual = "home" if home_score > away_score else "draw" if home_score == away_score else "away"
        settled_at = datetime.now(UTC).isoformat()
        league_snapshots = self.repository.league_snapshots(fixture["league_key"])
        season_data = (league_snapshots[0].get("season") or {}) if league_snapshots else {}
        season = str(season_data.get("name") or season_data.get("year") or "unknown")
        results = []
        for prediction in self.repository.current_predictions_for_fixture(
            fixture["id"],
            DEFAULT_PROMPT_CONTRACT.version,
            self.competition_id,
        ):
            settlement = self.repository.settlement_for_prediction(prediction["id"])
            bet = self.repository.bet_for_prediction(prediction["id"])
            clv_data = _bet_clv_data(self.repository, fixture, prediction, bet)
            if settlement is None:
                probabilities = prediction.get("model_probabilities") or prediction["probabilities"]
                brier = sum(
                    (float(probabilities[key]) - (1.0 if key == actual else 0.0)) ** 2
                    for key in ("home", "draw", "away")
                )
                predicted = prediction.get("predicted_outcome") or max(probabilities, key=probabilities.get)
                settlement = self.repository.save_fixture_settlement(
                    {
                        "id": str(uuid.uuid4()),
                        "prediction_id": prediction["id"],
                        "fixture_id": fixture["id"],
                        "fixture_date": fixture["fixture_date"],
                        "league_key": fixture["league_key"],
                        "season": season,
                        "model_version": prediction["model_version"],
                        "model_key": prediction.get("model_key") or (prediction.get("ai") or {}).get("provider") or "deepseek",
                        "competition_id": prediction.get("competition_id") or self.competition_id,
                        "settled_at": settled_at,
                        "actual_outcome": actual,
                        "predicted_outcome": predicted,
                        "correct": predicted == actual,
                        "brier_score": round(brier, 4),
                        "score": {"home": home_score, "away": away_score},
                        "probabilities": probabilities,
                        "model_probabilities": probabilities,
                        "baseline": prediction.get("baseline"),
                        "phase": prediction.get("phase"),
                        "prediction_created_at": prediction.get("created_at"),
                        "evidence_snapshot_id": prediction.get("evidence_snapshot_id"),
                        "evidence_hash": prediction.get("evidence_hash"),
                        "evidence_version": prediction.get("evidence_version") or (prediction.get("ai") or {}).get("evidence_version"),
                        "odds_snapshot_id": prediction.get("odds_snapshot_id"),
                        **clv_data,
                        "data_completeness": prediction.get("data_completeness"),
                        "decision": prediction.get("decision"),
                        "experiment": prediction.get("experiment"),
                        "market_assessment": prediction.get("market_assessment"),
                        "log_loss": _log_loss(probabilities, actual),
                        "rps": _rps(probabilities, actual),
                        "market_probabilities": _market_probabilities(prediction.get("market_assessment")),
                    }
                )
            if bet and bet.get("status") == "placed":
                result, return_amount = _bet_return(bet, home_score - away_score, actual)
                bet = self.repository.settle_bet(
                    bet["id"],
                    settled_at,
                    result,
                    return_amount,
                    settlement_metadata=clv_data,
                )
            results.append({"prediction": settlement, "bet": bet})
        return {"fixture_id": fixture["id"], "settled_count": len(results), "items": results}

    def settle_finished(self) -> dict[str, int]:
        fixture_count = 0
        prediction_count = 0
        for fixture in self.repository.list_fixtures():
            if fixture.get("status") != "finished" or not fixture.get("score"):
                continue
            result = self.settle_fixture(fixture)
            fixture_count += 1
            prediction_count += result["settled_count"]
        return {"fixture_count": fixture_count, "prediction_count": prediction_count}

    def metrics(
        self,
        league_key: str | None = None,
        season: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        model_version: str | None = None,
        model_key: str | None = None,
        competition_id: str | None = None,
    ) -> dict[str, Any]:
        rows = self.repository.fixture_settlements(
            league_key,
            season,
            start_date,
            end_date,
            model_version,
            model_key,
            competition_id or self.competition_id,
        )
        correct = sum(1 for row in rows if row["correct"])
        completeness = [
            float(row["data_completeness"])
            for row in rows
            if isinstance(row.get("data_completeness"), (int, float))
        ]
        prediction_ids = {row["prediction_id"] for row in rows}
        asian_counts = {
            key: 0 for key in ("full_win", "half_win", "push", "half_loss", "full_loss")
        }
        for bet in self.repository.bets(
            status="settled",
            model_key=model_key,
            competition_id=competition_id or self.competition_id,
        ):
            if bet.get("prediction_id") not in prediction_ids or bet.get("market") != "asian_handicap":
                continue
            result = bet.get("settlement_result")
            if result in asian_counts:
                asian_counts[result] += 1
        log_losses = [
            _log_loss(_forecast_probabilities(row), row["actual_outcome"])
            for row in rows
        ]
        rps_scores = [
            _rps(_forecast_probabilities(row), row["actual_outcome"])
            for row in rows
        ]
        market_rows = _dedupe_fixture_rows(
            [
                row for row in rows
                if isinstance(row.get("market_probabilities"), dict)
                and set(row["market_probabilities"]) >= {"home", "draw", "away"}
            ]
        )
        market_brier = [
            _brier(row["market_probabilities"], row["actual_outcome"])
            for row in market_rows
        ]
        market_log_loss = [
            _log_loss(row["market_probabilities"], row["actual_outcome"])
            for row in market_rows
        ]
        prediction_brier = [
            _brier(_forecast_probabilities(row), row["actual_outcome"])
            for row in rows
        ]
        paired_model_brier = [
            _brier(_forecast_probabilities(row), row["actual_outcome"])
            for row in market_rows
        ]
        paired_model_log_loss = [
            _log_loss(_forecast_probabilities(row), row["actual_outcome"])
            for row in market_rows
        ]
        model_metrics = _metric_summary(rows, _forecast_probabilities)
        market_metrics = _metric_summary(
            market_rows,
            lambda row: row.get("market_probabilities") or {},
        )
        market_metrics["ece"] = None
        market_metrics["calibration"] = None
        poisson_metrics = _metric_summary(
            _dedupe_fixture_rows(
                [
                    {**row, "model_probabilities": (row.get("baseline") or {}).get("probabilities")}
                    for row in rows
                    if (row.get("baseline") or {}).get("probabilities")
                ]
            ),
            _forecast_probabilities,
        )
        settled_bets = [
            bet for bet in self.repository.bets(
                status="settled",
                model_key=model_key,
                competition_id=competition_id or self.competition_id,
            )
            if bet.get("prediction_id") in prediction_ids
        ]
        clv_values = [
            float(bet["clv"])
            for bet in settled_bets if bet.get("clv") is not None
        ]
        portfolio = _portfolio_metrics(settled_bets)
        executed_prediction_ids = {str(bet.get("prediction_id")) for bet in settled_bets}
        decision_statuses = [
            str((row.get("decision") or {}).get("status") or (
                "bet" if str(row.get("prediction_id")) in executed_prediction_ids else "unknown"
            ))
            for row in rows
        ]
        decision_counts = {
            "bet": sum(status == "bet" for status in decision_statuses),
            "no_bet": sum(status == "no_bet" for status in decision_statuses),
            "insufficient_data": sum(status == "insufficient_data" for status in decision_statuses),
            "unknown": sum(status == "unknown" for status in decision_statuses),
        }
        quality = _quality_gate(
            settled_fixtures=len({row["fixture_id"] for row in rows}),
            prediction_samples=len(rows),
            market_comparison_samples=len(market_rows),
            clv_samples=len(clv_values),
            roi=portfolio["roi"],
            average_clv=(sum(clv_values) / len(clv_values)) if clv_values else None,
            brier_improvement=(
                sum(market_brier) / len(market_brier) - sum(paired_model_brier) / len(paired_model_brier)
                if market_brier and paired_model_brier else None
            ),
            max_drawdown=portfolio["max_drawdown"],
        )
        return {
            "sample_size": len(rows),
            "correct_count": correct,
            "accuracy": round(correct / len(rows), 4) if rows else 0.0,
            "average_brier_score": (
                round(sum(prediction_brier) / len(prediction_brier), 4)
                if rows
                else None
            ),
            "average_data_completeness": (
                round(sum(completeness) / len(completeness), 4) if completeness else None
            ),
            "average_log_loss": round(sum(log_losses) / len(log_losses), 4) if log_losses else None,
            "average_rps": round(sum(rps_scores) / len(rps_scores), 4) if rps_scores else None,
            "model_brier": model_metrics["brier"],
            "model_log_loss": model_metrics["log_loss"],
            "model_rps": model_metrics["rps"],
            "ece": model_metrics["ece"],
            "calibration": model_metrics["calibration"],
            "models": _model_reports(rows, model_metrics, poisson_metrics),
            "paired_samples": _paired_sample_count(rows),
            "paired_comparison": _paired_model_comparison(rows),
            "clv_samples": portfolio["clv_samples"],
            "average_clv": portfolio["average_clv"],
            "market_comparison": {
                "sample_size": len(market_rows),
                "market_brier_score": round(sum(market_brier) / len(market_brier), 4) if market_brier else None,
                "market_log_loss": round(sum(market_log_loss) / len(market_log_loss), 4) if market_log_loss else None,
                "market_brier": market_metrics["brier"],
                "market_rps": market_metrics["rps"],
                "brier_improvement": (
                    round(sum(market_brier) / len(market_brier) - sum(paired_model_brier) / len(paired_model_brier), 4)
                    if market_brier and paired_model_brier else None
                ),
                "log_loss_improvement": (
                    round(sum(market_log_loss) / len(market_log_loss) - sum(paired_model_log_loss) / len(paired_model_log_loss), 4)
                    if market_log_loss and paired_model_log_loss else None
                ),
                "rps_improvement": _improvement(market_metrics["rps"], model_metrics["rps"]),
            },
            "decision_counts": decision_counts,
            "portfolio": portfolio,
            "quality_gate": quality,
            "experiment": _experiment_summary(rows, model_key),
            "asian_handicap_results": asian_counts,
            "filters": {
                "league_key": league_key,
                "season": season,
                "start_date": start_date,
                "end_date": end_date,
                "model_version": model_version,
            },
            "items": rows,
        }


def _bet_return(bet: dict[str, Any], goal_difference: int, actual: str) -> tuple[str, float]:
    stake = float(bet["stake"])
    odds = float(bet["odds"])
    if bet["market"] == "1x2":
        won = bet["selection"] == actual
        return ("full_win", round(stake * odds, 2)) if won else ("full_loss", 0.0)
    line = float(bet["handicap_line"])
    if bet["selection"] == "away_handicap":
        weights = settle_asian_handicap(-goal_difference, -line)
    else:
        weights = settle_asian_handicap(goal_difference, line)
    result = max(weights, key=weights.get)
    return result, _asian_return(stake, odds, result)


def _bet_clv_data(
    repository: Any,
    fixture: dict[str, Any],
    prediction: dict[str, Any],
    bet: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolve kickoff-before closing odds and calculate bet-level CLV."""

    if not bet:
        return {
            "bet_odds": None,
            "closing_odds": None,
            "clv": None,
            "closing_odds_captured_at": None,
            "line_at_bet": None,
            "line_at_close": None,
            "line_changed": False,
            "odds_snapshot_id": prediction.get("odds_snapshot_id"),
        }
    bet_odds = bet.get("bet_odds") or bet.get("odds")
    line_at_bet = bet.get("line_at_bet")
    if line_at_bet is None:
        line_at_bet = bet.get("handicap_line")
    reader = getattr(repository, "closing_odds_for_bet", None)
    if callable(reader):
        try:
            closing = reader(fixture["id"], fixture.get("kickoff"), bet, allow_line_change=True)
        except TypeError:
            closing = reader(fixture["id"], fixture.get("kickoff"), bet)
    else:
        closing = None
    closing_odds = closing.get("price") if closing else None
    line_at_close = closing.get("line") if closing else None
    line_changed = bool(
        str(line_at_bet) != str(line_at_close)
        if line_at_bet is not None and line_at_close is not None
        else False
    )
    return {
        "bet_odds": bet_odds,
        "closing_odds": closing_odds,
        "clv": calculate_clv(bet_odds, closing_odds),
        "closing_odds_captured_at": closing.get("captured_at") if closing else None,
        "line_at_bet": line_at_bet,
        "line_at_close": line_at_close,
        "line_changed": line_changed,
        "odds_snapshot_id": bet.get("odds_snapshot_id") or prediction.get("odds_snapshot_id"),
    }


def _asian_return(stake: float, odds: float, result: str) -> float:
    multiplier = {
        "full_win": odds,
        "half_win": (odds + 1) / 2,
        "push": 1.0,
        "half_loss": 0.5,
        "full_loss": 0.0,
    }[result]
    return round(stake * multiplier, 2)


def _log_loss(probabilities: dict[str, Any], actual: str) -> float:
    value = min(1 - 1e-15, max(1e-15, float(probabilities.get(actual) or 0)))
    return round(-math.log(value), 4)


def _brier(probabilities: dict[str, Any], actual: str) -> float:
    return sum(
        (float(probabilities.get(key) or 0) - (1.0 if key == actual else 0.0)) ** 2
        for key in ("home", "draw", "away")
    )


def _rps(probabilities: dict[str, Any], actual: str) -> float:
    order = ("home", "draw", "away")
    actual_index = order.index(actual)
    running = 0.0
    score = 0.0
    for index, key in enumerate(order[:-1]):
        running += float(probabilities.get(key) or 0)
        observed = 1.0 if actual_index <= index else 0.0
        score += (running - observed) ** 2
    return round(score / 2, 4)


def _market_probabilities(assessment: dict[str, Any] | None) -> dict[str, float] | None:
    rows = (assessment or {}).get("markets") or []
    one_x_two: dict[str, float] = {}
    for row in rows:
        probability = row.get("market_probability")
        if probability is None:
            probability = row.get("de_vig_probability")
        if (
            row.get("market") == "1x2"
            and row.get("selection") in {"home", "draw", "away"}
            and isinstance(probability, (int, float))
        ):
            one_x_two[row["selection"]] = float(probability)
    return one_x_two if set(one_x_two) == {"home", "draw", "away"} else None


def _forecast_probabilities(row: dict[str, Any]) -> dict[str, Any]:
    """Read the frozen pure-model probabilities from a settlement row."""

    return row.get("model_probabilities") or row.get("probabilities") or {}


def _market_forecast_probabilities(row: dict[str, Any]) -> dict[str, Any]:
    return row.get("market_probabilities") or {}


def _improvement(market_value: float | None, model_value: float | None) -> float | None:
    if market_value is None or model_value is None:
        return None
    return round(market_value - model_value, 4)


def _dedupe_fixture_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        fixture_id = str(row.get("fixture_id") or row.get("prediction_id") or "")
        if fixture_id in seen:
            continue
        seen.add(fixture_id)
        result.append(row)
    return result


def _model_reports(
    rows: list[dict[str, Any]],
    model_metrics: dict[str, Any],
    poisson_metrics: dict[str, Any],
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = str(row.get("model_key") or (row.get("experiment") or {}).get("model_key") or "deepseek")
        groups.setdefault(key, []).append(row)
    reports: dict[str, Any] = {}
    for key, group in groups.items():
        model_report = _metric_summary(group, _forecast_probabilities)
        paired_market = [row for row in group if _market_forecast_probabilities(row)]
        paired_market_report = _metric_summary(paired_market, _market_forecast_probabilities)
        reports[key] = {
            **model_report,
            "market_brier": paired_market_report["brier"],
            "market_log_loss": paired_market_report["log_loss"],
            "market_rps": paired_market_report["rps"],
            "paired_samples": paired_market_report["samples"],
            "brier_improvement": _improvement(paired_market_report["brier"], model_report["brier"]),
            "log_loss_improvement": _improvement(paired_market_report["log_loss"], model_report["log_loss"]),
            "rps_improvement": _improvement(paired_market_report["rps"], model_report["rps"]),
        }
    if rows and not reports:
        reports["deepseek"] = model_metrics
    if "chatgpt" in reports:
        reports["gpt"] = reports["chatgpt"]
    poisson_rows = _dedupe_fixture_rows(
        [
            {**row, "model_probabilities": (row.get("baseline") or {}).get("probabilities")}
            for row in rows
            if (row.get("baseline") or {}).get("probabilities")
        ]
    )
    poisson_market = _metric_summary(
        [row for row in poisson_rows if _market_forecast_probabilities(row)],
        _market_forecast_probabilities,
    )
    reports["poisson"] = {
        **poisson_metrics,
        "market_brier": poisson_market["brier"],
        "market_log_loss": poisson_market["log_loss"],
        "market_rps": poisson_market["rps"],
        "paired_samples": poisson_market["samples"],
        "brier_improvement": _improvement(poisson_market["brier"], poisson_metrics["brier"]),
        "log_loss_improvement": _improvement(poisson_market["log_loss"], poisson_metrics["log_loss"]),
        "rps_improvement": _improvement(poisson_market["rps"], poisson_metrics["rps"]),
    }
    market_report = _metric_summary(
        _dedupe_fixture_rows([row for row in rows if _market_forecast_probabilities(row)]),
        _market_forecast_probabilities,
    )
    market_report["ece"] = None
    market_report["calibration"] = None
    reports["market"] = market_report
    return reports


def _paired_sample_count(rows: list[dict[str, Any]]) -> int:
    grouped: dict[str, set[str]] = {}
    for row in rows:
        key = str(row.get("model_key") or (row.get("experiment") or {}).get("model_key") or "deepseek")
        if set(_forecast_probabilities(row) or {}) >= {"home", "draw", "away"}:
            grouped.setdefault(key, set()).add(str(row.get("fixture_id") or ""))
    if not grouped:
        return 0
    return len(set.intersection(*grouped.values())) if len(grouped) > 1 else len(next(iter(grouped.values())))


def _paired_model_comparison(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        key = str(row.get("model_key") or (row.get("experiment") or {}).get("model_key") or "deepseek")
        probabilities = _forecast_probabilities(row)
        fixture_id = str(row.get("fixture_id") or "")
        if fixture_id and set(probabilities or {}) >= {"home", "draw", "away"}:
            grouped.setdefault(key, {})[fixture_id] = row
    left = grouped.get("deepseek", {})
    right = grouped.get("chatgpt", {})
    paired_ids = sorted(set(left) & set(right))
    differences = [
        _brier(_forecast_probabilities(left[fixture_id]), left[fixture_id]["actual_outcome"])
        - _brier(_forecast_probabilities(right[fixture_id]), right[fixture_id]["actual_outcome"])
        for fixture_id in paired_ids
    ]
    return {
        "models": ["deepseek", "chatgpt"],
        "paired_samples": len(paired_ids),
        "mean_brier_difference": round(sum(differences) / len(differences), 4) if differences else None,
    }


def _portfolio_metrics(bets: list[dict[str, Any]]) -> dict[str, Any]:
    settled_staked = round(sum(float(item.get("stake") or 0) for item in bets), 2)
    profit = round(sum(float(item.get("net_profit") or 0) for item in bets), 2)
    balance = 1000.0
    peak = balance
    max_drawdown = 0.0
    for bet in sorted(bets, key=lambda item: (str(item.get("settled_at") or ""), str(item.get("id") or ""))):
        balance = round(balance + float(bet.get("net_profit") or 0), 2)
        peak = max(peak, balance)
        max_drawdown = max(max_drawdown, (peak - balance) / peak if peak else 0.0)
    return {
        "settled_position_count": len(bets),
        "wins": sum(float(item.get("net_profit") or 0) > 0 for item in bets),
        "losses": sum(float(item.get("net_profit") or 0) < 0 for item in bets),
        "settled_staked": settled_staked,
        "realized_pnl": profit,
        "roi": round(profit / settled_staked, 4) if settled_staked else 0.0,
        "max_drawdown": round(max_drawdown, 4),
        "clv_samples": sum(1 for item in bets if item.get("clv") is not None),
        "average_clv": (
            round(sum(float(item["clv"]) for item in bets if item.get("clv") is not None) / sum(1 for item in bets if item.get("clv") is not None), 4)
            if any(item.get("clv") is not None for item in bets)
            else None
        ),
    }


def _quality_gate(
    *,
    settled_fixtures: int,
    prediction_samples: int,
    market_comparison_samples: int,
    clv_samples: int,
    roi: float,
    average_clv: float | None,
    brier_improvement: float | None,
    max_drawdown: float,
) -> dict[str, Any]:
    counts = {
        "settled_fixtures": settled_fixtures,
        "prediction_samples": prediction_samples,
        "market_comparison_samples": market_comparison_samples,
        "clv_samples": clv_samples,
    }
    checks = {
        "samples": {
            "value": prediction_samples,
            "required": QUALITY_POLICY["min_prediction_samples"],
            "passed": prediction_samples >= QUALITY_POLICY["min_prediction_samples"],
        },
        "settled_fixtures": {
            "value": settled_fixtures,
            "required": QUALITY_POLICY["min_settled_fixtures"],
            "passed": settled_fixtures >= QUALITY_POLICY["min_settled_fixtures"],
        },
        "market_comparison_samples": {
            "value": market_comparison_samples,
            "required": QUALITY_POLICY["min_market_comparison_samples"],
            "passed": market_comparison_samples >= QUALITY_POLICY["min_market_comparison_samples"],
        },
        "clv_samples": {
            "value": clv_samples,
            "required": QUALITY_POLICY["min_clv_samples"],
            "passed": clv_samples >= QUALITY_POLICY["min_clv_samples"],
        },
        "brier_improvement": {
            "value": brier_improvement,
            "required": QUALITY_POLICY["min_brier_improvement_vs_market"],
            "passed": brier_improvement is not None and brier_improvement >= QUALITY_POLICY["min_brier_improvement_vs_market"],
        },
        "average_clv": {
            "value": average_clv,
            "required": QUALITY_POLICY["min_average_clv"],
            "passed": average_clv is not None and average_clv >= QUALITY_POLICY["min_average_clv"],
        },
        "roi": {
            "value": roi,
            "required": QUALITY_POLICY["min_roi"],
            "passed": roi >= QUALITY_POLICY["min_roi"],
        },
        "drawdown": {
            "value": max_drawdown,
            "maximum": QUALITY_POLICY["max_drawdown"],
            "passed": max_drawdown <= QUALITY_POLICY["max_drawdown"],
        },
    }
    failures: list[str] = []
    for key, threshold_key in (
        ("settled_fixtures", "min_settled_fixtures"),
        ("prediction_samples", "min_prediction_samples"),
        ("market_comparison_samples", "min_market_comparison_samples"),
        ("clv_samples", "min_clv_samples"),
    ):
        if counts[key] < QUALITY_POLICY[threshold_key]:
            failures.append(f"MIN_{key.upper()}")
    if roi < QUALITY_POLICY["min_roi"]:
        failures.append("MIN_ROI")
    if average_clv is None or average_clv < QUALITY_POLICY["min_average_clv"]:
        failures.append("MIN_AVERAGE_CLV")
    if brier_improvement is None or brier_improvement < QUALITY_POLICY["min_brier_improvement_vs_market"]:
        failures.append("MIN_BRIER_IMPROVEMENT_VS_MARKET")
    if max_drawdown > QUALITY_POLICY["max_drawdown"]:
        failures.append("MAX_DRAWDOWN")
    sample_failures = {
        "MIN_SETTLED_FIXTURES",
        "MIN_PREDICTION_SAMPLES",
        "MIN_MARKET_COMPARISON_SAMPLES",
        "MIN_CLV_SAMPLES",
    }
    insufficient = any(item in sample_failures for item in failures)
    legacy_status = "READY" if not failures else "INSUFFICIENT_SAMPLE" if insufficient else "QUALITY_FAILED"
    quality_state = "VALIDATED" if not failures else "SHADOW" if insufficient else "OBSERVATION"
    return {
        "mode": "EXECUTABLE" if not failures else "SHADOW_ONLY",
        "status": legacy_status,
        "quality_state": quality_state,
        "state": quality_state,
        "passed": not failures,
        "failures": failures,
        "counts": counts,
        "checks": checks,
        "policy": QUALITY_POLICY,
    }


def _experiment_summary(rows: list[dict[str, Any]], model_key: str | None) -> dict[str, Any]:
    values = [row.get("experiment") or {} for row in rows]
    first = values[0] if values else {}
    return {
        "model_key": first.get("model_key") or model_key,
        "strategy_id": first.get("strategy_id") or "baseline",
        "strategy_version": first.get("strategy_version") or "v1",
        "strategy_name": first.get("strategy_name") or "基准",
        "prompt_version": first.get("prompt_version"),
        "decision_policy_version": first.get("decision_policy_version") or "football-sim-portfolio-v1",
        "ai_view_version": first.get("ai_view_version") or "football-ai-view-v1",
        "execution_config_version": first.get("execution_config_version"),
    }
