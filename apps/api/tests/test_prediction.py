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
