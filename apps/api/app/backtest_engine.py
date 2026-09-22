"""P12 Advanced Backtesting: reproducible walk-forward research engine.

Modes share one contract: chronological windows with auditable
boundaries, ensemble weights learned per window from the training slice
only, temperature from validation only, and final metrics from test.
Betting simulation requires the full historical execution chain
(prediction + odds + decision + settlement); incomplete chains report
``unavailable`` instead of an estimate. Run manifests freeze every
version input so the same manifest rebuilds the same result.
"""

from __future__ import annotations

import hashlib
import json
import platform
import random
import sys
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable, Mapping

from .model_platform import learn_ensemble_weights
from .model_registry import dataset_fingerprint
from .prediction_intelligence import (
    CALIBRATION_VERSION,
    FEATURE_VERSION,
    PROBABILITY_KEYS,
    build_backtest_rows,
    evaluate_probabilities,
    normalize_probabilities,
    parse_timestamp,
)
from .historical_validation import rolling_windows

BACKTEST_ENGINE_VERSION = "p12-backtest-v1"
STRATEGY_VERSION = "flat-stake-v1"
BACKTEST_MODES: tuple[str, ...] = (
    "expanding",
    "rolling",
    "walk_forward",
    "cross_competition",
    "model_comparison",
    "strategy",
)
DEFAULT_SEED = 20260913


def expanding_windows(
    start: Any,
    end: Any,
    *,
    initial_train_days: int = 180,
    test_days: int = 30,
    step_days: int = 30,
) -> list[dict[str, Any]]:
    """Windows whose training slice grows from a fixed origin."""

    start_at = parse_timestamp(start)
    end_at = parse_timestamp(end)
    if start_at is None or end_at is None:
        raise ValueError("start and end must be ISO timestamps")
    if min(initial_train_days, test_days, step_days) <= 0:
        raise ValueError("initial_train_days, test_days, and step_days must be positive")
    cursor = start_at + timedelta(days=initial_train_days)
    windows: list[dict[str, Any]] = []
    index = 1
    while cursor + timedelta(days=test_days) <= end_at:
        windows.append(
            {
                "window_id": f"window-{index:04d}",
                "train_start": start_at.isoformat(),
                "train_end": cursor.isoformat(),
                "test_start": cursor.isoformat(),
                "test_end": (cursor + timedelta(days=test_days)).isoformat(),
            }
        )
        cursor += timedelta(days=step_days)
        index += 1
    return windows


def _row_time(row: Mapping[str, Any]) -> datetime | None:
    return parse_timestamp(row.get("prediction_created_at") or row.get("evaluation_timestamp"))


def _slice_window(
    rows: list[dict[str, Any]], window: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    train_start = parse_timestamp(window["train_start"])
    train_end = parse_timestamp(window["train_end"])
    test_start = parse_timestamp(window["test_start"])
    test_end = parse_timestamp(window["test_end"])
    train = [
        row
        for row in rows
        if train_start and train_end and train_start <= (_row_time(row) or datetime.min.replace(tzinfo=UTC)) <= train_end
    ]
    test = [
        row
        for row in rows
        if test_start and test_end and test_start < (_row_time(row) or datetime.max.replace(tzinfo=UTC)) <= test_end
    ]
    return train, test


def _models_of(row: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    models: dict[str, dict[str, float]] = {}
    for key, value in (row.get("models") or row.get("base_predictions") or {}).items():
        normalized = normalize_probabilities(value)
        if normalized:
            models[str(key)] = normalized
    return models


def _ensemble_probabilities(row: Mapping[str, Any], weights: Mapping[str, float]) -> dict[str, float] | None:
    models = _models_of(row)
    available = {key: value for key, value in models.items() if key in weights}
    total = sum(weights.get(key, 0.0) for key in available)
    if not available or total <= 0:
        return None
    probabilities = {
        key: sum(available[model][key] * weights.get(model, 0.0) for model in available) / total
        for key in PROBABILITY_KEYS
    }
    return normalize_probabilities(probabilities)


def _train_class_frequencies(train_rows: list[dict[str, Any]]) -> dict[str, float]:
    counts = {key: 0 for key in PROBABILITY_KEYS}
    total = 0
    for row in train_rows:
        outcome = row.get("actual_outcome")
        if outcome in counts:
            counts[outcome] += 1
            total += 1
    if not total:
        return {key: round(1 / 3, 6) for key in PROBABILITY_KEYS}
    return {key: round(count / total, 6) for key, count in counts.items()}


def _devig_market_probabilities(row: Mapping[str, Any]) -> dict[str, float] | None:
    odds = row.get("market_odds")
    if not isinstance(odds, Mapping):
        return None
    implied = {}
    for key in PROBABILITY_KEYS:
        try:
            price = float(odds.get(key))
        except (TypeError, ValueError):
            return None
        if price <= 1.0:
            return None
        implied[key] = 1.0 / price
    total = sum(implied.values())
    return {key: round(value / total, 6) for key, value in implied.items()}


def bootstrap_confidence_interval(
    values: Iterable[float],
    *,
    seed: int = DEFAULT_SEED,
    iterations: int = 1000,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Deterministic percentile bootstrap interval."""

    sample = [float(value) for value in values]
    if not sample:
        return {"low": None, "high": None, "iterations": iterations, "seed": seed, "sample_size": 0}
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(max(1, int(iterations))):
        draw = [sample[rng.randrange(len(sample))] for _ in range(len(sample))]
        means.append(sum(draw) / len(draw))
    means.sort()
    low_index = max(0, int(len(means) * alpha / 2))
    high_index = min(len(means) - 1, int(len(means) * (1 - alpha / 2)))
    return {
        "low": round(means[low_index], 6),
        "high": round(means[high_index], 6),
        "iterations": iterations,
        "seed": seed,
        "sample_size": len(sample),
    }


def _brier_by_fixture(rows: list[dict[str, Any]], probabilities_by_fixture: dict[str, Mapping[str, float]]) -> dict[str, float]:
    """Per-fixture Brier scores so cross-model statistics stay row-paired."""

    values: dict[str, float] = {}
    for row in rows:
        fixture_id = str(row.get("fixture_id") or "")
        probabilities = probabilities_by_fixture.get(fixture_id)
        outcome = row.get("actual_outcome")
        if not fixture_id or not probabilities or outcome not in PROBABILITY_KEYS:
            continue
        values[fixture_id] = sum(
            (probabilities[key] - (1.0 if key == outcome else 0.0)) ** 2 for key in PROBABILITY_KEYS
        )
    return values


def _brier_per_row(rows: list[dict[str, Any]], probabilities_by_fixture: dict[str, Mapping[str, float]]) -> list[float]:
    values = []
    for row in rows:
        probabilities = probabilities_by_fixture.get(str(row.get("fixture_id") or ""))
        outcome = row.get("actual_outcome")
        if not probabilities or outcome not in PROBABILITY_KEYS:
            continue
        values.append(
            sum((probabilities[key] - (1.0 if key == outcome else 0.0)) ** 2 for key in PROBABILITY_KEYS)
        )
    return values


def simulate_strategy(
    rows: Iterable[Mapping[str, Any]],
    *,
    stake: float = 1.0,
    commission: float = 0.0,
    slippage: float = 0.0,
    probabilities_by_fixture: dict[str, Mapping[str, float]] | None = None,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Flat-stake simulation over the complete execution chain only.

    A row needs model probabilities, a decision (selection + odds) and a
    settlement outcome. Rows missing any link are skipped and counted;
    when nothing qualifies the result is ``unavailable`` — never an
    estimate.
    """

    _ = seed  # reserved for future stake-rule stochasticity; deterministic today
    equity = 0.0
    curve: list[float] = []
    returns: list[float] = []
    losing_streak = 0
    max_losing_streak = 0
    skipped: dict[str, int] = {"missing_odds": 0, "missing_decision": 0, "missing_settlement": 0}
    bets: list[dict[str, Any]] = []
    for row in rows:
        fixture_id = str(row.get("fixture_id") or "")
        probabilities = (probabilities_by_fixture or {}).get(fixture_id) or _row_probabilities(row)
        decision = row.get("decision") if isinstance(row.get("decision"), Mapping) else None
        odds = row.get("market_odds") if isinstance(row.get("market_odds"), Mapping) else None
        settled = row.get("actual_outcome")
        if probabilities is None:
            skipped["missing_settlement"] += 1
            continue
        if not odds:
            skipped["missing_odds"] += 1
            continue
        if not decision or not decision.get("selection"):
            skipped["missing_decision"] += 1
            continue
        if settled not in PROBABILITY_KEYS:
            skipped["missing_settlement"] += 1
            continue
        selection = str(decision["selection"])
        try:
            price = float(odds.get(selection))
        except (TypeError, ValueError):
            skipped["missing_odds"] += 1
            continue
        effective_price = price - max(0.0, float(slippage))
        if effective_price <= 1.0:
            skipped["missing_odds"] += 1
            continue
        stake_for_bet = float(stake)
        settlement = row.get("settlement_status") or ("void" if row.get("void") else None)
        if settlement in {"void", "push"}:
            profit = 0.0
        elif settled == selection:
            profit = stake_for_bet * (effective_price - 1.0) * (1.0 - max(0.0, float(commission)))
        else:
            profit = -stake_for_bet
        equity += profit
        curve.append(round(equity, 6))
        returns.append(profit / stake_for_bet)
        losing_streak = losing_streak + 1 if profit < 0 else 0
        max_losing_streak = max(max_losing_streak, losing_streak)
        bets.append({"fixture_id": fixture_id, "selection": selection, "profit": round(profit, 6)})
    if not bets:
        reason = next((key for key, count in skipped.items() if count), "no_executable_bets")
        return {"status": "unavailable", "reason": reason, "skipped": skipped, "bets": 0}
    peak = 0.0
    drawdown = 0.0
    for value in curve:
        peak = max(peak, value)
        drawdown = min(drawdown, value - peak)
    mean_return = sum(returns) / len(returns)
    volatility = (sum((value - mean_return) ** 2 for value in returns) / len(returns)) ** 0.5
    return {
        "status": "ok",
        "strategy_version": STRATEGY_VERSION,
        "bets": len(bets),
        "skipped": skipped,
        "roi": round(equity / (len(bets) * stake), 6),
        "total_profit": round(equity, 6),
        "equity_curve": curve,
        "max_drawdown": round(drawdown, 6),
        "volatility": round(volatility, 6),
        "max_losing_streak": max_losing_streak,
    }


def _row_probabilities(row: Mapping[str, Any]) -> dict[str, float] | None:
    """Any available model probabilities for the row (existence check)."""

    models = _models_of(row)
    return next(iter(models.values())) if models else None


def _environment_fingerprint() -> dict[str, str]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }


def build_manifest(
    rows: list[dict[str, Any]],
    *,
    mode: str,
    params: Mapping[str, Any],
    seed: int = DEFAULT_SEED,
    competition_scope: str = "all",
    model_version: str | None = None,
    feature_version: str = FEATURE_VERSION,
    calibration_version: str = CALIBRATION_VERSION,
    strategy_version: str = STRATEGY_VERSION,
    code_version: str = BACKTEST_ENGINE_VERSION,
) -> dict[str, Any]:
    """Freeze every versioned input of a backtest run."""

    times = sorted(str(_row_time(row) or "") for row in rows if _row_time(row))
    manifest = {
        "engine_version": code_version,
        "mode": mode,
        "competition_scope": competition_scope,
        "dataset_fingerprint": dataset_fingerprint(rows),
        "as_of_range": {"start": times[0] if times else None, "end": times[-1] if times else None},
        "feature_version": feature_version,
        "model_version": model_version,
        "calibration_version": calibration_version,
        "strategy_version": strategy_version,
        "random_seed": seed,
        "params": dict(params),
        "environment": _environment_fingerprint(),
        "row_count": len(rows),
    }
    digest = hashlib.sha256(json_stable(manifest).encode()).hexdigest()[:24]
    manifest["manifest_fingerprint"] = f"manifest:{digest}"
    return manifest


def json_stable(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def run_backtest_engine(
    settlement_rows: Iterable[Mapping[str, Any]],
    *,
    mode: str = "rolling",
    start: Any = None,
    end: Any = None,
    initial_train_days: int = 180,
    train_days: int = 180,
    test_days: int = 30,
    step_days: int = 30,
    model_keys: Iterable[str] | None = None,
    stake: float = 1.0,
    commission: float = 0.0,
    slippage: float = 0.0,
    seed: int = DEFAULT_SEED,
    competition_scope: str = "all",
    code_version: str = BACKTEST_ENGINE_VERSION,
) -> dict[str, Any]:
    """Run one reproducible backtest over persisted settlement rows.

    Weights are learned per window from the training slice only; test
    labels never influence model selection or weighting.
    """

    if mode not in BACKTEST_MODES:
        raise ValueError(f"Unknown backtest mode: {mode}")
    rows = build_backtest_rows(settlement_rows)
    # build_backtest_rows keeps the evaluation core; the execution-chain
    # fields the strategy simulator needs live on the settlement rows.
    extra_by_fixture: dict[str, dict[str, Any]] = {}
    for row in settlement_rows:
        fixture_id = str(row.get("fixture_id") or "")
        extra = {key: row[key] for key in ("market_odds", "decision", "settlement_status", "void") if key in row}
        if fixture_id and extra:
            extra_by_fixture.setdefault(fixture_id, {}).update(extra)
    rows = [
        dict(row, models=_models_of(row), **extra_by_fixture.get(str(row.get("fixture_id") or ""), {}))
        for row in rows
    ]
    rows = [row for row in rows if row["models"] and row.get("actual_outcome") in PROBABILITY_KEYS]
    if not rows:
        return {"status": "insufficient_sample", "reason": "no settled model rows", "mode": mode}
    times = sorted(_row_time(row) for row in rows if _row_time(row))
    start = start or times[0]
    end = end or times[-1]
    resolved_models = tuple(model_keys) if model_keys else tuple(sorted({key for row in rows for key in row["models"]}))

    if mode == "cross_competition":
        leagues = sorted({str(row.get("league_key") or "unknown") for row in rows})
        per_league: dict[str, Any] = {}
        for league in leagues:
            league_rows = [row for row in rows if str(row.get("league_key") or "unknown") == league]
            league_times = sorted(_row_time(row) for row in league_rows if _row_time(row))
            per_league[league] = _run_windows(
                league_rows,
                resolved_models,
                windows=rolling_windows(league_times[0], league_times[-1], train_days=train_days, test_days=test_days, step_days=step_days),
                seed=seed,
            )
        return {
            "status": "ok",
            "mode": mode,
            "manifest": build_manifest(
                rows,
                mode=mode,
                competition_scope="per_league",
                params={"train_days": train_days, "test_days": test_days, "step_days": step_days},
                seed=seed,
                code_version=code_version,
            ),
            "leagues": per_league,
            "coverage": {league: len([row for row in rows if str(row.get("league_key") or "unknown") == league]) for league in leagues},
        }

    windows = (
        rolling_windows(start, end, train_days=train_days, test_days=test_days, step_days=step_days)
        if mode in {"rolling", "model_comparison", "strategy"}
        else expanding_windows(start, end, initial_train_days=initial_train_days, test_days=test_days, step_days=step_days)
    )
    result = _run_windows(rows, resolved_models, windows=windows, seed=seed)
    result["mode"] = mode
    result["manifest"] = build_manifest(
        rows,
        mode=mode,
        params={
            "train_days": train_days,
            "initial_train_days": initial_train_days,
            "test_days": test_days,
            "step_days": step_days,
        },
        seed=seed,
        competition_scope=competition_scope,
        code_version=code_version,
    )
    probabilities = result.pop("_test_probabilities", {})
    # The strategy simulation reports "unavailable" unless the execution
    # chain (odds + decision + settlement) is complete per row.
    result["strategy"] = simulate_strategy(
        rows,
        stake=stake,
        commission=commission,
        slippage=slippage,
        probabilities_by_fixture=probabilities,
        seed=seed,
    )
    return result


def _run_windows(
    rows: list[dict[str, Any]],
    model_keys: tuple[str, ...],
    *,
    windows: list[dict[str, Any]],
    seed: int,
) -> dict[str, Any]:
    windows_report: list[dict[str, Any]] = []
    test_probabilities: dict[str, dict[str, float]] = {}
    ensemble_briers: list[float] = []
    model_briers: dict[str, list[float]] = {key: [] for key in model_keys}
    baseline_briers: list[float] = []
    # Fixture-keyed Briers keep the improvement statistic paired: comparing
    # two independently sorted float lists would scramble which rows differ.
    ensemble_briers_by_fixture: dict[str, float] = {}
    baseline_briers_by_fixture: dict[str, float] = {}
    market_briers: list[float] = []
    market_row_count = 0
    for window in windows:
        train, test = _slice_window(rows, window)
        if not train or not test:
            continue
        weights = learn_ensemble_weights([{"models": row["models"], "actual_outcome": row.get("actual_outcome")} for row in train], model_keys)
        naive = _train_class_frequencies(train)
        window_ensemble: dict[str, dict[str, float]] = {}
        for row in test:
            probabilities = _ensemble_probabilities(row, weights)
            if probabilities:
                window_ensemble[str(row.get("fixture_id") or "")] = probabilities
                test_probabilities[str(row.get("fixture_id") or "")] = probabilities
        ensemble_metrics = evaluate_probabilities(test, lambda row: window_ensemble.get(str(row.get("fixture_id") or "")))
        per_model = {
            key: evaluate_probabilities(test, lambda row, key=key: _models_of(row).get(key))
            for key in model_keys
        }
        naive_metrics = evaluate_probabilities(test, lambda row: naive)
        market_rows = [dict(row, market_normalized=_devig_market_probabilities(row)) for row in test]
        market_evaluated = [row for row in market_rows if row["market_normalized"]]
        market_metrics = (
            evaluate_probabilities(market_evaluated, lambda row: row["market_normalized"])
            if market_evaluated
            else {"status": "unavailable", "reason": "missing_market_odds"}
        )
        windows_report.append(
            {
                "window_id": window["window_id"],
                "train_end": window["train_end"],
                "test_start": window["test_start"],
                "test_end": window["test_end"],
                "train_size": len(train),
                "test_size": len(test),
                "weights": {key: round(value, 6) for key, value in weights.items()},
                "ensemble": ensemble_metrics,
                "models": per_model,
                "naive_baseline": naive_metrics,
                "market_baseline": market_metrics,
            }
        )
        ensemble_briers.extend(_brier_per_row(test, window_ensemble))
        ensemble_briers_by_fixture.update(_brier_by_fixture(test, window_ensemble))
        for key in model_keys:
            model_briers[key].extend(_brier_per_row(test, {str(row.get("fixture_id") or ""): probs for row in test if (probs := _models_of(row).get(key))}))
        baseline_briers.extend(_brier_per_row(test, {str(row.get("fixture_id") or ""): naive}))
        baseline_briers_by_fixture.update(_brier_by_fixture(test, {str(row.get("fixture_id") or ""): naive}))
        if market_evaluated:
            market_row_count += len(market_evaluated)
            market_briers.extend(_brier_per_row(market_evaluated, {str(row.get("fixture_id") or ""): row["market_normalized"] for row in market_evaluated}))
    aggregate_ensemble = bootstrap_confidence_interval(ensemble_briers, seed=seed)
    improvement: dict[str, Any] = {"naive_baseline": None}
    if ensemble_briers and baseline_briers:
        paired_fixtures = sorted(set(ensemble_briers_by_fixture) & set(baseline_briers_by_fixture))
        improvements = [
            baseline_briers_by_fixture[fixture_id] - ensemble_briers_by_fixture[fixture_id]
            for fixture_id in paired_fixtures
        ]
        improvement["naive_baseline"] = {
            "brier_improvement": round(sum(improvements) / len(improvements), 6) if improvements else None,
            "confidence_interval": bootstrap_confidence_interval(improvements, seed=seed + 1),
            "paired_samples": len(improvements),
        }
    return {
        "status": "ok" if windows_report else "insufficient_sample",
        "windows": windows_report,
        "window_count": len(windows_report),
        "sample_size": len(ensemble_briers),
        "ensemble_brier": aggregate_ensemble,
        "model_briers": {
            key: bootstrap_confidence_interval(values, seed=seed + index + 2)
            for index, (key, values) in enumerate(model_briers.items())
        },
        "market_baseline_brier": (
            bootstrap_confidence_interval(market_briers, seed=seed + len(model_keys) + 2)
            if market_briers
            else {"status": "unavailable", "reason": "missing_market_odds", "rows_with_odds": market_row_count}
        ),
        "improvement": improvement,
        "_test_probabilities": test_probabilities,
    }
