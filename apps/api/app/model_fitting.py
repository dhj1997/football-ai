"""Fit Dixon-Coles rho and league xG baselines from historical finished matches.

The home/away goal means are closed-form MLEs (empirical averages); rho is
fitted by grid search maximising the exact-score log-likelihood under the
DC-corrected independent Poisson model. Fitted parameters are registered as
versioned model artifacts with dataset provenance; predictions fall back to
the built-in constants when no fitted artifact exists.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping

from .historical_validation import parse_timestamp

FITTING_VERSION = "model-fitting-v1"
MAX_GOALS = 10
RHO_GRID_STEP = 0.005


def _poisson(lam: float, goals: int) -> float:
    return math.exp(-lam) * lam**goals / math.factorial(goals)


def _tau(home_goals: int, away_goals: int, home_xg: float, away_xg: float, rho: float) -> float:
    if home_goals == 0 and away_goals == 0:
        return 1.0 - home_xg * away_xg * rho
    if home_goals == 0 and away_goals == 1:
        return 1.0 + home_xg * rho
    if home_goals == 1 and away_goals == 0:
        return 1.0 + away_xg * rho
    if home_goals == 1 and away_goals == 1:
        return 1.0 - rho
    return 1.0


def _dc_log_likelihood(
    scores: list[tuple[int, int]], home_xg: float, away_xg: float, rho: float
) -> float:
    total = 0.0
    mass = [
        _poisson(home_xg, h) * _poisson(away_xg, a) * max(0.0, _tau(h, a, home_xg, away_xg, rho))
        for h in range(MAX_GOALS)
        for a in range(MAX_GOALS)
    ]
    norm = sum(mass)
    if norm <= 0:
        return float("-inf")
    index = {(h, a): mass[h * MAX_GOALS + a] / norm for h in range(MAX_GOALS) for a in range(MAX_GOALS)}
    for h, a in scores:
        total += math.log(max(1e-12, index.get((h, a), 0.0)))
    return total


def fit_league(rows: Iterable[tuple[int, int]]) -> dict[str, Any]:
    """Fit one league's xG means (closed form) and rho (grid search MLE)."""

    scores = [(int(h), int(a)) for h, a in rows if h >= 0 and a >= 0]
    n = len(scores)
    if n < 30:
        return {"n": n, "status": "insufficient_sample", "minimum": 30}
    home_xg = sum(h for h, _ in scores) / n
    away_xg = sum(a for _, a in scores) / n
    best_rho = 0.0
    best_ll = float("-inf")
    steps = int(abs(-0.20) / RHO_GRID_STEP)
    for step in range(steps + 1):
        rho = round(-0.20 + step * RHO_GRID_STEP, 3)
        ll = _dc_log_likelihood(scores, home_xg, away_xg, rho)
        if ll > best_ll:
            best_ll, best_rho = ll, rho
    return {
        "n": n,
        "status": "ok",
        "home_xg": round(home_xg, 4),
        "away_xg": round(away_xg, 4),
        "rho": best_rho,
        "log_likelihood": round(best_ll, 4),
    }


def _finished_rows(fixture_rows: Iterable[Mapping[str, Any]]) -> Iterable[tuple[str, int, int, str]]:
    for row in fixture_rows:
        if row.get("status") != "finished":
            continue
        score = row.get("score") if isinstance(row.get("score"), Mapping) else None
        if not score or score.get("home") is None or score.get("away") is None:
            continue
        league = str(row.get("canonical_league") or row.get("league_key") or "").casefold()
        kickoff = parse_timestamp(row.get("kickoff"))
        yield league, int(score["home"]), int(score["away"]), kickoff.isoformat() if kickoff else ""


def fit_from_repository(repository: Any, *, min_matches: int = 30) -> dict[str, Any]:
    """Fit per-league parameters from every finished fixture in the store."""

    reader = getattr(repository, "list_fixtures", None)
    fixture_rows = reader() if callable(reader) else []
    by_league: dict[str, list[tuple[int, int]]] = {}
    kickoffs: list[str] = []
    for league, home, away, kickoff in _finished_rows(fixture_rows or []):
        by_league.setdefault(league or "unknown", []).append((home, away))
        if kickoff:
            kickoffs.append(kickoff)
    leagues: dict[str, Any] = {}
    for league, scores in sorted(by_league.items()):
        result = fit_league(scores)
        if result.get("status") != "ok" and result["n"] < min_matches:
            leagues[league] = {**result, "status": "insufficient_sample"}
        else:
            leagues[league] = result
    fitted = {
        "fitting_version": FITTING_VERSION,
        "fitted_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "dataset": {
            "finished_matches": sum(len(scores) for scores in by_league.values()),
            "training_cutoff": max(kickoffs) if kickoffs else None,
            "leagues": {league: len(scores) for league, scores in sorted(by_league.items())},
        },
        "leagues": leagues,
    }
    digest = hashlib.sha256(
        json.dumps(fitted["leagues"], ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:12]
    fitted["fitted_version"] = f"dc-fit-{digest}"
    return fitted


def fitted_record(fitted: Mapping[str, Any]) -> dict[str, Any]:
    """Build a ModelRecord-ready payload for the fitted parameters."""

    return {
        "model_key": "dixon_coles",
        "model_version": fitted["fitted_version"],
        "artifact_hash": hashlib.sha256(
            json.dumps(fitted["leagues"], ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()[:32],
        "status": "draft",
        "competition_scope": "all",
        "feature_version": None,
        "dataset_fingerprint": f"fit:{fitted['dataset']['finished_matches']}",
        "training_cutoff": fitted["dataset"].get("training_cutoff"),
        "calibration_version": None,
        "created_at": fitted.get("fitted_at"),
        "payload": {"parameters": dict(fitted["leagues"]), "dataset": dict(fitted["dataset"])},
    }


def load_fitted_params(repository: Any) -> dict[str, Any] | None:
    """Latest fitted parameter artifact (any lifecycle status)."""

    reader = getattr(repository, "model_registry", None)
    if not callable(reader):
        return None
    for row in reader(model_key="dixon_coles"):
        parameters = (row.get("payload") or {}).get("parameters")
        if parameters:
            return {
                "fitted_version": row.get("model_version"),
                "leagues": parameters,
                "fitted_at": row.get("created_at"),
            }
    return None
