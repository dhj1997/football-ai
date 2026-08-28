from datetime import UTC, datetime, timedelta

import pytest

from app.market_decision import apply_market_decision


def prediction(
    probabilities: dict[str, float] | None = None,
    confidence: float = 0.8,
) -> dict:
    return {
        "probabilities": probabilities or {"home": 0.7, "draw": 0.2, "away": 0.1},
        "forecast_confidence": confidence,
        "asian_handicap": None,
        "ai": {"status": "completed", "evidence_version": "fixture-evidence-v3"},
        "model_recommendation": {
            "status": "bet",
            "market": "1x2",
            "selection": "home",
            "reason": "主胜方向值得进入后端赔率校验。",
        },
    }


def context(
    odds: dict | None,
    lineup_confirmed: bool = True,
    player_status: str = "complete",
) -> dict:
    return {
        "odds": odds,
        "lineup": {"confirmed": lineup_confirmed},
        "player_impact": {
            "home": {"data_status": player_status},
            "away": {"data_status": player_status},
        },
    }


def fresh_odds(home: float = 1.6, draw: float = 4.0, away: float = 7.0) -> dict:
    return {
        "bookmaker": "Test Book",
        "home": home,
        "draw": draw,
        "away": away,
        "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }


def test_backend_selects_a_positive_alternative_when_the_model_pick_has_negative_edge() -> None:
    result = apply_market_decision(
        prediction(confidence=0.5),
        context(fresh_odds(1.256, 6.5, 10.5), lineup_confirmed=False, player_status="partial"),
    )
    home = next(
        row
        for row in result["market_assessment"]["markets"]
        if row["market"] == "1x2" and row["selection"] == "home"
    )

    assert result["forecast"]["predicted_outcome"] == "home"
    assert home["break_even_probability"] == pytest.approx(0.7962, abs=0.0001)
    assert home["expected_edge"] == pytest.approx(-0.1208, abs=0.0001)
    assert result["decision"]["status"] == "bet"
    assert result["decision"]["market"] == "1x2"
    assert result["decision"]["selection"] == "draw"
    assert result["decision"]["expected_edge"] == pytest.approx(0.3)
    assert result["decision"]["stake_fraction"] == 0.25
    assert "low_confidence" not in result["decision"]["reason_codes"]
    assert "low_confidence" in result["decision"]["warning_codes"]
    assert "lineup_unconfirmed" not in result["decision"]["reason_codes"]
    assert "lineup_unconfirmed" in result["decision"]["warning_codes"]


def test_better_home_price_changes_deterministic_decision_when_evidence_is_ready() -> None:
    result = apply_market_decision(prediction(), context(fresh_odds(home=1.6)))

    assert result["decision"]["status"] == "bet"
    assert result["decision"]["market"] == "1x2"
    assert result["decision"]["selection"] == "home"
    assert result["decision"]["expected_edge"] == pytest.approx(0.12)
    assert result["decision"]["stake_fraction"] == 0.19


def test_three_percent_edge_uses_the_ten_percent_stake_floor() -> None:
    result = apply_market_decision(
        prediction(),
        context(fresh_odds(home=1.4714285714)),
    )

    assert result["decision"]["status"] == "bet"
    assert result["decision"]["expected_edge"] == pytest.approx(0.03)
    assert result["decision"]["stake_fraction"] == 0.10


def test_de_vig_probabilities_sum_to_one() -> None:
    result = apply_market_decision(prediction(), context(fresh_odds()))
    one_x_two = [row for row in result["market_assessment"]["markets"] if row["market"] == "1x2"]

    assert sum(row["de_vig_probability"] for row in one_x_two) == pytest.approx(1, abs=0.0002)


def test_missing_market_is_insufficient_but_missing_players_is_no_bet() -> None:
    no_market = apply_market_decision(prediction(), context(None))
    no_players = apply_market_decision(prediction(), context(fresh_odds(), player_status="insufficient"))

    assert no_market["decision"]["status"] == "insufficient_data"
    assert "no_matching_market" in no_market["decision"]["reason_codes"]
    assert no_players["decision"]["status"] == "no_bet"
    assert "missing_player_data" in no_players["decision"]["reason_codes"]


def test_stale_odds_blocks_one_model_without_cross_model_disagreement_rule() -> None:
    odds = fresh_odds()
    odds["updated_at"] = (datetime.now(UTC) - timedelta(hours=4)).isoformat()

    result = apply_market_decision(prediction(), context(odds), model_disagreement=0.15)

    assert result["decision"]["status"] == "no_bet"
    assert "stale_odds" in result["decision"]["reason_codes"]
    assert "model_disagreement" not in result["decision"]["reason_codes"]
    assert result["decision"]["stake_fraction"] == 0.19


def test_preliminary_prediction_can_bet_at_normal_size_before_lineup() -> None:
    item = prediction()
    item["phase"] = "preliminary"

    result = apply_market_decision(item, context(fresh_odds()))

    assert result["decision"]["status"] == "bet"
    assert result["decision"]["stake_fraction"] == 0.19
    assert "lineup_unconfirmed" not in result["decision"]["reason_codes"]
    assert "lineup_unconfirmed" in result["decision"]["warning_codes"]


def test_completed_low_confidence_prediction_can_bet_at_normal_size() -> None:
    result = apply_market_decision(prediction(confidence=0.55), context(fresh_odds(home=1.6)))

    assert result["decision"]["status"] == "bet"
    assert result["decision"]["stake_fraction"] == 0.19
    assert "low_confidence" not in result["decision"]["reason_codes"]
    assert "low_confidence" in result["decision"]["warning_codes"]


def test_failed_ai_keeps_low_confidence_as_a_hard_gate() -> None:
    item = prediction(confidence=0.55)
    item["ai"]["status"] = "failed"

    result = apply_market_decision(item, context(fresh_odds(home=1.6)))

    assert result["decision"]["status"] == "no_bet"
    assert "low_confidence" in result["decision"]["reason_codes"]


def test_ai_no_bet_remains_visible_but_does_not_veto_positive_backend_value() -> None:
    item = prediction()
    item["model_recommendation"] = {
        "status": "no_bet",
        "market": "no_bet",
        "selection": "none",
        "reason": "当前证据不足以支持下注。",
    }

    result = apply_market_decision(item, context(fresh_odds()))

    assert result["decision"]["status"] == "bet"
    assert result["decision"]["market"] == "1x2"
    assert result["decision"]["selection"] == "home"
    assert result["decision"]["stake_fraction"] == 0.19
    assert result["decision"]["reason_codes"] == []
    assert result["decision"]["model_recommendation_status"] == "no_bet"


def test_backend_selects_the_highest_edge_market_across_all_prices() -> None:
    item = prediction({"home": 0.55, "draw": 0.35, "away": 0.1})
    item["model_recommendation"] = {
        "status": "bet",
        "market": "1x2",
        "selection": "draw",
        "reason": "平局方向值得进入后端赔率校验。",
    }

    result = apply_market_decision(item, context(fresh_odds(home=2.0, draw=4.0, away=9.0)))

    assert result["decision"]["status"] == "bet"
    assert result["decision"]["selection"] == "draw"
    assert result["decision"]["expected_edge"] == pytest.approx(0.4)


def test_legacy_prompt_evidence_cannot_create_a_new_bet() -> None:
    item = prediction()
    item["ai"]["evidence_version"] = None

    result = apply_market_decision(item, context(fresh_odds()))

    assert result["decision"]["status"] == "no_bet"
    assert result["decision"]["stake_fraction"] == 0.19
    assert "missing_player_data" in result["decision"]["reason_codes"]


def test_asian_handicap_falls_back_to_poisson_settlement_without_model_forecast() -> None:
    item = prediction({"home": 0.55, "draw": 0.25, "away": 0.2})
    item["asian_handicap"] = {
        "line": -0.75,
        "home_settlement": {
            "full_win": 0.45,
            "half_win": 0.15,
            "push": 0.05,
            "half_loss": 0.1,
            "full_loss": 0.25,
        },
    }
    odds = {**fresh_odds(1.7, 3.8, 5.0), "asian_handicap": -0.75, "asian_handicap_home_odd": 2.1, "asian_handicap_away_odd": 1.8}

    result = apply_market_decision(item, context(odds))
    home = next(row for row in result["market_assessment"]["markets"] if row["selection"] == "home_handicap")

    assert home["model_probability"] == 0.6
    assert home["expected_edge"] == pytest.approx(0.2775)
    assert home["probability_source"] == "poisson_baseline"
    assert result["forecast"]["asian_handicap"]["home_cover_probability"] == 0.6


def test_barcelona_handicap_uses_gpt_cover_probability_instead_of_poisson_direction() -> None:
    item = prediction({"home": 0.78, "draw": 0.14, "away": 0.08})
    item["asian_handicap"] = {
        "line": -1.5,
        "home_settlement": {
            "full_win": 0.4251,
            "half_win": 0.0,
            "push": 0.0,
            "half_loss": 0.0,
            "full_loss": 0.5749,
        },
    }
    item["asian_handicap_forecast"] = {
        "available": True,
        "line": -1.5,
        "home_cover_probability": 0.56,
        "away_cover_probability": 0.44,
        "confidence": 0.61,
        "reason": "模型认为主队覆盖概率略高。",
    }
    odds = {
        **fresh_odds(1.235, 6.5, 11.0),
        "asian_handicap": -1.5,
        "asian_handicap_home_odd": 1.625,
        "asian_handicap_away_odd": 2.15,
    }

    result = apply_market_decision(item, context(odds))
    handicap = {
        row["selection"]: row
        for row in result["market_assessment"]["markets"]
        if row["market"] == "asian_handicap"
    }

    assert handicap["home_handicap"]["model_probability"] == 0.56
    assert handicap["home_handicap"]["expected_edge"] == pytest.approx(-0.09)
    assert handicap["away_handicap"]["model_probability"] == 0.44
    assert handicap["away_handicap"]["expected_edge"] == pytest.approx(-0.054)
    assert handicap["away_handicap"]["probability_source"] == "model_asian_handicap_forecast"
    assert result["decision"]["status"] == "no_bet"
    assert result["decision"]["selection"] == "none"


def test_model_direction_reweights_quarter_line_while_preserving_settlement_shape() -> None:
    item = prediction({"home": 0.55, "draw": 0.25, "away": 0.2})
    item["asian_handicap"] = {
        "line": -0.75,
        "home_settlement": {
            "full_win": 0.45,
            "half_win": 0.15,
            "push": 0.05,
            "half_loss": 0.1,
            "full_loss": 0.25,
        },
    }
    item["asian_handicap_forecast"] = {
        "available": True,
        "line": -0.75,
        "home_cover_probability": 0.7,
        "away_cover_probability": 0.3,
        "confidence": 0.65,
        "reason": "模型方向用于重权结算分布。",
    }
    odds = {
        **fresh_odds(1.7, 3.8, 5.0),
        "asian_handicap": -0.75,
        "asian_handicap_home_odd": 2.1,
        "asian_handicap_away_odd": 1.8,
    }

    result = apply_market_decision(item, context(odds))
    home = next(
        row for row in result["market_assessment"]["markets"]
        if row["selection"] == "home_handicap"
    )

    assert home["model_probability"] == 0.7
    assert home["probability_source"] == "model_asian_handicap_forecast"
    assert home["settlement"]["push"] == 0.05
    assert home["settlement"]["full_win"] / home["settlement"]["half_win"] == pytest.approx(3, abs=0.01)
    assert home["settlement"]["full_loss"] / home["settlement"]["half_loss"] == pytest.approx(2.5, abs=0.01)
    assert sum(home["settlement"].values()) == pytest.approx(1, abs=0.0002)
    assert home["expected_edge"] == pytest.approx(0.3958, abs=0.0001)


def test_stale_handicap_distribution_is_not_applied_to_a_new_line() -> None:
    item = prediction({"home": 0.55, "draw": 0.25, "away": 0.2})
    item["asian_handicap"] = {
        "line": -1.5,
        "home_settlement": {"full_win": 0.5, "half_win": 0, "push": 0, "half_loss": 0, "full_loss": 0.5},
    }
    odds = {**fresh_odds(), "asian_handicap": -2.5, "asian_handicap_home_odd": 2.1, "asian_handicap_away_odd": 1.8}

    result = apply_market_decision(item, context(odds))

    assert all(row["market"] == "1x2" for row in result["market_assessment"]["markets"])
    assert result["forecast"]["asian_handicap"] is None
