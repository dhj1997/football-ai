"""P12 advanced backtesting: splitters, uncertainty, strategy, manifest."""

import pytest

from app.backtest_engine import (
    BACKTEST_MODES,
    build_manifest,
    bootstrap_confidence_interval,
    expanding_windows,
    run_backtest_engine,
    simulate_strategy,
)


def settlement_rows(count: int = 200, *, league_key: str = "epl", with_odds: bool = False, seed: int = 11) -> list[dict]:
    import random
    from datetime import UTC, datetime, timedelta

    rng = random.Random(seed)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for index in range(count):
        actual = rng.choice(["home", "draw", "away"])
        row = {
            "fixture_id": f"{league_key}-{index}",
            "prediction_id": f"{league_key}-p{index}",
            "league_key": league_key,
            "prediction_created_at": (start + timedelta(hours=index * 6)).isoformat(),
            "settled_at": (start + timedelta(hours=index * 6 + 30)).isoformat(),
            "model_key": "deepseek",
            "model_version": "deepseek:deepseek-v4-flash",
            "actual_outcome": actual,
            "model_probabilities": {key: 0.55 if key == actual else 0.225 for key in ("home", "draw", "away")},
        }
        if with_odds:
            row["market_odds"] = {"home": 2.2, "draw": 3.4, "away": 3.6}
            row["decision"] = {"market": "1x2", "selection": actual}
        rows.append(row)
    return rows


def test_expanding_windows_are_chronological_with_fixed_origin() -> None:
    windows = expanding_windows("2026-01-01T00:00:00+00:00", "2026-07-01T00:00:00+00:00", initial_train_days=60, test_days=30, step_days=30)

    assert windows
    assert all(window["train_start"] == "2026-01-01T00:00:00+00:00" for window in windows)
    assert windows[0]["train_end"] < windows[-1]["train_end"]
    for window in windows:
        assert window["train_end"] == window["test_start"]
        assert window["test_start"] < window["test_end"]


def test_bootstrap_interval_is_deterministic_per_seed() -> None:
    values = [0.3, 0.35, 0.4, 0.45, 0.5]

    first = bootstrap_confidence_interval(values, seed=42)
    second = bootstrap_confidence_interval(values, seed=42)
    other = bootstrap_confidence_interval(values, seed=43)

    assert first == second
    assert first["low"] <= first["high"]
    assert other["low"] == first["low"] or other["high"] != first["high"]
    assert bootstrap_confidence_interval([], seed=1)["low"] is None


def test_strategy_simulation_requires_complete_execution_chain() -> None:
    rows = settlement_rows(10, with_odds=True)
    probabilities = {row["fixture_id"]: {"home": 0.5, "draw": 0.3, "away": 0.2} for row in rows}

    complete = simulate_strategy(rows, probabilities_by_fixture=probabilities)
    assert complete["status"] == "ok"
    assert complete["bets"] == len(rows)
    assert len(complete["equity_curve"]) == complete["bets"]
    assert complete["max_drawdown"] <= 0

    missing_odds = simulate_strategy(settlement_rows(10), probabilities_by_fixture=probabilities)
    assert missing_odds["status"] == "unavailable"
    assert missing_odds["reason"] == "missing_odds"

    no_bets = simulate_strategy([])
    assert no_bets["status"] == "unavailable"


def test_strategy_accounts_for_commission_slippage_and_push() -> None:
    rows = [
        {
            "fixture_id": "f1",
            "actual_outcome": "home",
            "decision": {"selection": "home"},
            "market_odds": {"home": 3.0, "draw": 3.0, "away": 3.0},
            "model_probabilities": {"home": 0.5, "draw": 0.25, "away": 0.25},
        },
        {
            "fixture_id": "f2",
            "actual_outcome": "away",
            "decision": {"selection": "away"},
            "market_odds": {"home": 2.0, "draw": 3.0, "away": 3.0},
            "model_probabilities": {"home": 0.3, "draw": 0.3, "away": 0.4},
            "settlement_status": "push",
        },
    ]
    probabilities = {"f1": {"home": 0.5, "draw": 0.25, "away": 0.25}, "f2": {"home": 0.3, "draw": 0.3, "away": 0.4}}

    result = simulate_strategy(rows, stake=100.0, commission=0.05, slippage=0.1, probabilities_by_fixture=probabilities)

    assert result["status"] == "ok"
    assert result["bets"] == 2
    # Bet 1 wins: (3.0 - 0.1 - 1) * 100 * 0.95 = 180.5; bet 2 pushes: 0.
    assert result["total_profit"] == 180.5
    assert result["roi"] == round(180.5 / 200, 6)
    assert result["max_losing_streak"] == 0


def test_engine_rolling_mode_is_reproducible_and_benchmarked() -> None:
    rows = settlement_rows(300)

    first = run_backtest_engine(rows, mode="rolling", train_days=45, test_days=15, step_days=15)
    second = run_backtest_engine(rows, mode="rolling", train_days=45, test_days=15, step_days=15)

    assert first["status"] == "ok"
    assert first["window_count"] >= 1
    assert first["manifest"]["dataset_fingerprint"]
    assert first["manifest"]["random_seed"]
    assert first["manifest"]["environment"]["python"]
    assert first["manifest"]["manifest_fingerprint"] == second["manifest"]["manifest_fingerprint"]
    assert first["ensemble_brier"] == second["ensemble_brier"]
    assert first["improvement"]["naive_baseline"] is not None
    assert first["improvement"]["naive_baseline"]["brier_improvement"] > 0
    assert first["strategy"]["status"] == "unavailable"
    assert first["strategy"]["reason"] == "missing_odds"
    for window in first["windows"]:
        assert window["weights"]  # learned on the training slice only
        assert "naive_baseline" in window
        assert window["market_baseline"]["status"] == "unavailable"


def test_engine_market_baseline_needs_complete_odds() -> None:
    rows = settlement_rows(300, with_odds=True)

    result = run_backtest_engine(rows, mode="model_comparison", train_days=45, test_days=15, step_days=15)

    assert result["market_baseline_brier"].get("sample_size", 0) >= 0
    assert result["strategy"]["status"] == "ok"
    assert result["strategy"]["bets"] >= 0

    without_odds = run_backtest_engine(settlement_rows(300), mode="model_comparison", train_days=45, test_days=15, step_days=15)
    assert without_odds["market_baseline_brier"]["status"] == "unavailable"
    assert without_odds["market_baseline_brier"]["reason"] == "missing_market_odds"


def test_engine_expanding_and_cross_competition_modes() -> None:
    rows = settlement_rows(300)

    expanding = run_backtest_engine(rows, mode="expanding", initial_train_days=45, test_days=15, step_days=15)
    assert expanding["window_count"] >= 1
    assert expanding["mode"] == "expanding"

    mixed = settlement_rows(150, league_key="lal", seed=13) + rows
    cross = run_backtest_engine(mixed, mode="cross_competition", train_days=45, test_days=15, step_days=15)
    assert set(cross["leagues"]) == {"epl", "lal"}
    assert sum(cross["coverage"].values()) == 450


def test_engine_rejects_unknown_mode_and_empty_rows() -> None:
    with pytest.raises(ValueError):
        run_backtest_engine(settlement_rows(10), mode="bogus")

    result = run_backtest_engine([], mode="rolling")
    assert result["status"] == "insufficient_sample"


def test_manifest_freezes_versions_and_params() -> None:
    rows = settlement_rows(30)

    manifest = build_manifest(rows, mode="rolling", params={"train_days": 30}, seed=7, model_version="m1")

    assert manifest["mode"] == "rolling"
    assert manifest["dataset_fingerprint"].startswith("dataset:")
    assert manifest["feature_version"] and manifest["calibration_version"] and manifest["strategy_version"]
    assert manifest["random_seed"] == 7
    assert manifest["params"] == {"train_days": 30}
    assert manifest["manifest_fingerprint"].startswith("manifest:")
    assert BACKTEST_MODES
