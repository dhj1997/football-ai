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
                        "phase": prediction.get("phase"),
                        "prediction_created_at": prediction.get("created_at"),
                        "evidence_snapshot_id": prediction.get("evidence_snapshot_id"),
                        "evidence_hash": prediction.get("evidence_hash"),
                        "evidence_version": prediction.get("evidence_version") or (prediction.get("ai") or {}).get("evidence_version"),
                        "odds_snapshot_id": prediction.get("odds_snapshot_id"),
                        "data_completeness": prediction.get("data_completeness"),
                        "decision": prediction.get("decision"),
                        "experiment": prediction.get("experiment"),
                        "market_assessment": prediction.get("market_assessment"),
                        "log_loss": _log_loss(probabilities, actual),
                        "rps": _rps(probabilities, actual),
                        "market_probabilities": _market_probabilities(prediction.get("market_assessment")),
                    }
                )
            bet = self.repository.bet_for_prediction(prediction["id"])
            if bet and bet.get("status") == "placed":
                result, return_amount = _bet_return(bet, home_score - away_score, actual)
                bet = self.repository.settle_bet(
                    bet["id"],
                    settled_at,
                    result,
                    return_amount,
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
        market_rows = [
            row for row in rows
            if isinstance(row.get("market_probabilities"), dict)
            and set(row["market_probabilities"]) >= {"home", "draw", "away"}
        ]
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
        market_prediction_brier = [
            _brier(_forecast_probabilities(row), row["actual_outcome"])
            for row in market_rows
        ]
        market_prediction_log_loss = [
            _log_loss(_forecast_probabilities(row), row["actual_outcome"])
            for row in market_rows
        ]
        settled_bets = [
            bet for bet in self.repository.bets(
                status="settled",
                model_key=model_key,
                competition_id=competition_id or self.competition_id,
            )
            if bet.get("prediction_id") in prediction_ids
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
            clv_samples=0,
            roi=portfolio["roi"],
            average_clv=None,
            brier_improvement=(
                sum(market_brier) / len(market_brier) - sum(market_prediction_brier) / len(market_prediction_brier)
                if market_brier and market_prediction_brier else None
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
            "market_comparison": {
                "sample_size": len(market_rows),
                "market_brier_score": round(sum(market_brier) / len(market_brier), 4) if market_brier else None,
                "market_log_loss": round(sum(market_log_loss) / len(market_log_loss), 4) if market_log_loss else None,
                "brier_improvement": (
                    round(sum(market_brier) / len(market_brier) - sum(market_prediction_brier) / len(market_prediction_brier), 4)
                    if market_brier and market_prediction_brier else None
                ),
                "log_loss_improvement": (
                    round(sum(market_log_loss) / len(market_log_loss) - sum(market_prediction_log_loss) / len(market_prediction_log_loss), 4)
                    if market_log_loss and market_prediction_log_loss else None
                ),
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
    one_x_two = {
        row.get("selection"): float(row.get("market_probability") or row.get("de_vig_probability"))
        for row in rows
        if row.get("market") == "1x2" and row.get("selection") in {"home", "draw", "away"}
        and isinstance(row.get("de_vig_probability"), (int, float))
    }
    return one_x_two if set(one_x_two) == {"home", "draw", "away"} else None


def _forecast_probabilities(row: dict[str, Any]) -> dict[str, Any]:
    """Read the frozen pure-model probabilities from a settlement row."""

    return row.get("model_probabilities") or row.get("probabilities") or {}


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
        "clv_samples": 0,
        "average_clv": None,
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
    return {
        "mode": "EXECUTABLE" if not failures else "SHADOW_ONLY",
        "status": (
            "READY"
            if not failures
            else "INSUFFICIENT_SAMPLE"
            if any(item in sample_failures for item in failures)
            else "QUALITY_FAILED"
        ),
        "failures": failures,
        "counts": counts,
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
