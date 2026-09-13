"""Tests for probability normalization and handicap settlement."""

from datetime import datetime

import pytest

from app.data import CHINA_TZ, demo_context, demo_fixtures
from app.prediction import predict, settle_asian_handicap


@pytest.mark.parametrize(
    ("difference", "handicap", "expected"),
    [
        (1, -0.75, "half_win"),
        (1, -1.0, "push"),
        (0, -0.25, "half_loss"),
        (2, -0.5, "full_win"),
        (-1, 0.25, "full_loss"),
    ],
)
def test_asian_handicap_settlement(difference: int, handicap: float, expected: str) -> None:
    result = settle_asian_handicap(difference, handicap)
    assert result[expected] == 1.0
    assert sum(result.values()) == 1.0


def test_prediction_is_normalized_and_auditable() -> None:
    fixture = demo_fixtures(datetime.now(CHINA_TZ).date())[0]
    result = predict(fixture, demo_context(fixture["id"]))

    assert sum(result["probabilities"].values()) == pytest.approx(1, abs=0.001)
    assert sum(result["asian_handicap"]["home_settlement"].values()) == pytest.approx(1, abs=0.001)
    assert result["model_version"]
    assert result["evidence"]["odds_at"]


def test_predict_treats_missing_points_per_game_as_zero_without_crashing() -> None:
    fixture = {"id": "fixture-1", "status": "scheduled", "is_demo": False}
    context = demo_context(fixture["id"])
    context["recent_form"]["home_points_per_game"] = None
    context["recent_form"]["away_points_per_game"] = None

    result = predict(fixture, context)

    assert set(result["probabilities"]) == {"home", "draw", "away"}
    assert abs(sum(result["probabilities"].values()) - 1.0) < 0.01


def test_predict_exposes_over_under_totals_forecast() -> None:
    fixture = {"id": "fixture-1", "status": "scheduled", "is_demo": False}
    context = demo_context(fixture["id"])

    result = predict(fixture, context)

    totals = result["totals_forecast"]
    assert totals["line"] == 2.5
    assert totals["over"] + totals["under"] == pytest.approx(1.0, abs=0.001)
    assert 0.05 <= totals["over"] <= 0.95


def test_dixon_coles_negative_rho_shifts_mass_into_draws_and_unders(monkeypatch) -> None:
    import app.prediction as prediction_module

    fixture = {"id": "fixture-1", "status": "scheduled", "is_demo": False}
    context = demo_context(fixture["id"])

    monkeypatch.setattr(prediction_module, "POISSON_DC_RHO", 0.0)
    plain = predict(fixture, context)
    monkeypatch.setattr(prediction_module, "POISSON_DC_RHO", -0.12)
    adjusted = predict(fixture, context)

    assert adjusted["probabilities"]["draw"] > plain["probabilities"]["draw"]
    # The four adjusted cells are all under 2.5 goals, so totals barely move;
    # the correction redistributes inside the low-score region.
    assert abs(adjusted["totals_forecast"]["over"] - plain["totals_forecast"]["over"]) < 0.01
    assert adjusted["probabilities"]["home"] + adjusted["probabilities"]["draw"] + adjusted["probabilities"]["away"] == pytest.approx(1.0, abs=0.001)

def test_markets_detail_dimensions_are_consistent() -> None:
    fixture = {"id": "f1", "league_key": "epl", "is_demo": False}
    context = {
        "recent_form": {"home": [], "away": [], "updated_at": "2026-09-01T00:00:00+00:00"},
        "lineup": {"confirmed": True, "home_strength": None, "away_strength": None, "updated_at": "2026-09-01T00:00:00+00:00"},
        "availability": {"updated_at": "2026-09-01T00:00:00+00:00"},
        "player_impact": {},
        "odds": {"asian_handicap": -0.5, "updated_at": "2026-09-01T00:00:00+00:00"},
    }

    detail = predict(fixture, context)["markets_detail"]

    assert abs(sum(detail["btts"].values()) - 1.0) < 1e-3
    for block in detail["totals_lines"].values():
        assert abs(block["over"] + block["push"] + block["under"] - 1.0) < 1e-3
    for block in detail["handicap_lines"].values():
        assert abs(block["home_cover"] + block["push"] + block["away_cover"] - 1.0) < 1e-3
    assert abs(sum(detail["half_time"][key] for key in ("home", "draw", "away")) - 1.0) < 1e-3
    # 2.5 线与既有 totals_forecast 完全一致（同一矩阵派生）。
    assert abs(detail["totals_lines"]["2.5"]["over"] - predict(fixture, context)["totals_forecast"]["over"]) < 1e-3
