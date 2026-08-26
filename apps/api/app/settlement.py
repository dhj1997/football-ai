"""Idempotent final-score settlement and prediction performance metrics."""

import uuid
from datetime import UTC, datetime
from typing import Any

from .prediction import settle_asian_handicap


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
        for prediction in self.repository.predictions_for_fixture(fixture["id"], competition_id=self.competition_id):
            settlement = self.repository.settlement_for_prediction(prediction["id"])
            if settlement is None:
                probabilities = prediction["probabilities"]
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
                        "phase": prediction.get("phase"),
                        "evidence_snapshot_id": prediction.get("evidence_snapshot_id"),
                        "data_completeness": prediction.get("data_completeness"),
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
        return {
            "sample_size": len(rows),
            "correct_count": correct,
            "accuracy": round(correct / len(rows), 4) if rows else 0.0,
            "average_brier_score": (
                round(sum(float(row["brier_score"]) for row in rows) / len(rows), 4)
                if rows
                else None
            ),
            "average_data_completeness": (
                round(sum(completeness) / len(completeness), 4) if completeness else None
            ),
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
