from datetime import UTC, datetime

import pytest

from app.bankroll import BankrollService
from app.database import PredictionRepository
from app.portfolio import (
    ACTIVE_BET_STATUSES,
    BetCandidate,
    PortfolioConfig,
    build_candidates,
    calculate_drawdown,
    calculate_edge,
    calculate_ev,
    cash_balance,
    candidate_sort_key,
    equity,
    exposure_snapshot,
    is_candidate_eligible,
    is_active_bet,
    open_exposure,
    risk_gate,
    select_best_candidates,
    select_portfolio,
)
from app.settlement import calculate_clv


def candidate(
    fixture_id: str = "fixture-1",
    prediction_id: str = "prediction-1",
    league_key: str = "epl",
    model_key: str = "deepseek",
    correlation_group: str | None = None,
    edge: float = 0.10,
    ev: float = 0.20,
    score: float = 0.8,
) -> BetCandidate:
    return BetCandidate(
        fixture_id=fixture_id,
        fixture_date="2099-08-27",
        league_key=league_key,
        prediction_id=prediction_id,
        model_key=model_key,
        market="1x2",
        selection="home",
        line=None,
        odds=2.0,
        model_probability=0.6,
        market_probability=0.5,
        edge=edge,
        ev=ev,
        risk_score=0.1,
        data_quality=0.9,
        odds_age_minutes=0.0,
        confidence=0.8,
        correlation_group=correlation_group,
        candidate_score=score,
    )


def test_edge_and_ev_use_decimal_formulas() -> None:
    assert calculate_edge(0.60, 0.50) == pytest.approx(0.10)
    assert calculate_ev(0.60, 2.00) == pytest.approx(0.20)


def test_account_snapshot_uses_one_ledger_and_active_status_set() -> None:
    transactions = [
        {"amount": 1000},
        {"amount": -100},
        {"amount": 50},
    ]
    bets = [
        {"status": "placed", "stake": 40, "fixture_date": "2099-08-27", "league_key": "epl"},
        {"status": "pending", "stake": 20, "fixture_date": "2099-08-27", "league_key": "epl"},
        {"status": "executed", "stake": 10, "fixture_date": "2099-08-27", "league_key": "laliga"},
        {"status": "selected", "stake": 5, "fixture_date": "2099-08-28", "league_key": "epl"},
        {"status": "settled", "stake": 999, "fixture_date": "2099-08-27", "league_key": "epl"},
    ]

    snapshot = exposure_snapshot(
        bets,
        transactions,
        fixture_date="2099-08-27",
        league_key="epl",
    )

    assert ACTIVE_BET_STATUSES == frozenset({"placed", "pending", "executed", "selected"})
    assert all(is_active_bet(status) for status in ACTIVE_BET_STATUSES)
    assert not is_active_bet("settled")
    assert cash_balance(transactions) == 950.0
    assert open_exposure(bets) == 75.0
    assert snapshot == {
        "cash_balance": 950.0,
        "open_exposure": 75.0,
        "equity": 1025.0,
        "daily_exposure": 70.0,
        "league_exposure": 60.0,
        "total_exposure": 75.0,
    }


def test_candidate_tie_break_is_deterministic_by_model_and_prediction_id() -> None:
    selected = select_best_candidates(
        [
            candidate(model_key="deepseek", prediction_id="z-prediction", correlation_group="deep-group", score=0.8),
            candidate(model_key="chatgpt", prediction_id="a-prediction", correlation_group="gpt-group", score=0.8),
        ]
    )

    assert len(selected) == 1
    assert selected[0].model_key == "chatgpt"
    assert selected[0].prediction_id == "a-prediction"


def test_candidate_sort_key_has_no_fixture_tie_break_component() -> None:
    first = candidate(fixture_id="fixture-z", model_key="chatgpt", prediction_id="prediction-a", score=0.8)
    second = candidate(fixture_id="fixture-a", model_key="chatgpt", prediction_id="prediction-a", score=0.8)

    assert candidate_sort_key(first) == candidate_sort_key(second)


def test_candidate_filter_rejects_ev_below_p2_threshold() -> None:
    assert not is_candidate_eligible(candidate(ev=0.03), PortfolioConfig())
    assert is_candidate_eligible(candidate(), PortfolioConfig())


def test_risk_gate_failure_always_returns_zero_stake() -> None:
    result = risk_gate(candidate(ev=0.03), 10_000, config=PortfolioConfig())
    assert result["status"] == "FAIL"
    assert result["allowed_stake"] == 0.0


def test_single_bet_limit_is_one_percent_of_bankroll() -> None:
    result = risk_gate(candidate(), 10_000, config=PortfolioConfig())
    assert result["allowed_stake"] == 100.0


def test_daily_and_league_limits_clamp_requested_stake() -> None:
    config = PortfolioConfig()
    daily = risk_gate(candidate(), 10_000, daily_exposure=480, requested_stake=50, config=config)
    league = risk_gate(candidate(), 10_000, league_exposure=200, requested_stake=50, config=config)
    assert daily["status"] == "PASS"
    assert daily["allowed_stake"] == 20.0
    assert league["status"] == "FAIL"
    assert league["allowed_stake"] == 0.0


def test_total_exposure_clamps_requested_stake() -> None:
    result = risk_gate(candidate(), 10_000, total_exposure=950, requested_stake=100, config=PortfolioConfig())
    assert result["status"] == "PASS"
    assert result["allowed_stake"] == 50.0


def test_fixture_correlation_keeps_only_highest_ranked_candidate() -> None:
    selected = select_portfolio(
        [candidate(score=0.8, prediction_id="p1"), candidate(score=0.7, prediction_id="p2")],
        10_000,
        config=PortfolioConfig(),
    )
    assert len(selected) == 1
    assert selected[0]["prediction_id"] == "p1"


def test_drawdown_at_limit_blocks_new_execution() -> None:
    config = PortfolioConfig(max_drawdown=0.30)
    result = risk_gate(candidate(), 10_000, drawdown=0.30, config=config)
    assert result["status"] == "FAIL"
    assert result["allowed_stake"] == 0.0
    assert calculate_drawdown([{"balance": 10_000}, {"balance": 7_000}]) == pytest.approx(0.30)


def test_clv_is_calculated_from_frozen_bet_and_closing_price() -> None:
    assert calculate_clv(2.0, 1.8) == pytest.approx(0.1111, abs=0.0001)


def test_p2_bankroll_freezes_execution_and_uses_one_percent_stake(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "p2.db"), "p2", ("deepseek",))
    repository.initialize()
    service = BankrollService(repository, PortfolioConfig()).configure("deepseek", "p2")
    fixture = {
        "id": "fixture-1",
        "fixture_date": "2099-08-27",
        "kickoff": "2099-08-27T12:00:00+00:00",
        "status": "scheduled",
        "league_key": "epl",
        "home_team": {"name": "Home"},
        "away_team": {"name": "Away"},
    }
    prediction = {
        "id": "prediction-1",
        "fixture_id": "fixture-1",
        "model_key": "deepseek",
        "model_version": "deepseek:test",
        "probabilities": {"home": 0.6, "draw": 0.25, "away": 0.15},
        "forecast_confidence": 0.8,
        "data_completeness": 0.9,
        "ai": {"status": "completed"},
        "decision": {"status": "bet", "market": "1x2", "selection": "home", "model_confidence": 0.8},
    }
    context = {
        "odds": {
            "home": 2.0,
            "draw": 3.2,
            "away": 4.0,
            "bookmaker": "Test Book",
            "updated_at": datetime.now(UTC).isoformat(),
        }
    }

    placed = service.place_for_prediction(prediction, fixture, context)

    assert placed is not None
    assert placed["stake"] == 10.0
    assert placed["execution_id"]
    execution = repository.bet_execution(placed["execution_id"])
    assert execution is not None and execution["status"] == "EXECUTED"
    settled = repository.settle_bet_execution(
        placed["execution_id"],
        result="full_win",
        profit_loss=10.0,
        settled_at="2099-08-27T13:00:00+00:00",
        metadata={"odds": 9.0, "stake": 1.0, "selection": "away", "clv": 0.1111},
    )
    assert settled is not None
    assert settled["odds"] == 2.0
    assert settled["stake"] == 10.0
    assert settled["selection"] == "home"
    assert settled["clv"] == pytest.approx(0.1111)


def test_build_candidates_exposes_edge_and_ev_separately() -> None:
    fixture = {"id": "f1", "fixture_date": "2099-08-27", "league_key": "epl", "status": "scheduled"}
    prediction = {
        "id": "p1",
        "model_key": "deepseek",
        "data_completeness": 0.9,
        "forecast_confidence": 0.8,
        "ai": {"status": "completed"},
        "market_assessment": {
            "odds_status": "fresh",
            "odds_updated_at": datetime.now(UTC).isoformat(),
            "markets": [
                {
                    "market": "1x2",
                    "selection": "home",
                    "price": 2.0,
                    "model_probability": 0.6,
                    "market_probability": 0.5,
                }
            ],
        },
    }
    rows = build_candidates(prediction, fixture)
    assert len(rows) == 1
    assert rows[0].edge == pytest.approx(0.1)
    assert rows[0].ev == pytest.approx(0.2)
