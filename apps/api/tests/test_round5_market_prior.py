"""Focused Round 5 Market Prior and deterministic fusion contracts."""

from copy import deepcopy

import pytest

from app.database import PredictionRepository
from app.market_prior import (
    MarketPriorConfig,
    MarketPriorError,
    Round5ProbabilityEngine,
    build_market_prior,
    deterministic_fusion,
    implied_probability,
    multiplicative_devig,
    persist_round5_market_snapshot,
)


FIXTURE_ID = "round5-fixture"
CUTOFF = "2026-09-17T12:00:00+00:00"


def odds_snapshot(
    snapshot_id: str,
    captured_at: str,
    prices: dict[str, object],
    *,
    bookmaker: str = "bookmaker-a",
    source: str = "real-provider",
    fixture_id: str = FIXTURE_ID,
    source_updated_at: str | None = None,
) -> dict:
    return {
        "id": snapshot_id,
        "fixture_id": fixture_id,
        "captured_at": captured_at,
        "source_updated_at": source_updated_at or captured_at,
        "bookmaker": bookmaker,
        "source": source,
        "quotes": [
            {
                "market": "1x2",
                "selection": selection,
                "price": price,
                "bookmaker": bookmaker,
                "source": source,
            }
            for selection, price in prices.items()
        ],
    }


def round4_result(probabilities: dict[str, float] | None = None) -> dict:
    return {
        "match_id": FIXTURE_ID,
        "fixture_id": FIXTURE_ID,
        "prediction_cutoff_at": CUTOFF,
        "feature_snapshot_id": "feature:round5-fixture",
        "probability_model_version": "poisson-dc-v2.0.0",
        "calculation_version": "round4-probability-engine-v1",
        "probabilities": probabilities or {"home": 0.50, "draw": 0.30, "away": 0.20},
        # This is the actual Round 4 audit shape: the production-safety flags
        # live under checks rather than being duplicated at the audit root.
        "probability_audit": {
            "status": "PASS",
            "checks": {"market_independent": True, "no_ml": True},
        },
    }


def valid_snapshot(
    snapshot_id: str = "odds-valid",
    captured_at: str = "2026-09-17T11:30:00+00:00",
    **overrides: object,
) -> dict:
    return odds_snapshot(
        snapshot_id,
        captured_at,
        {"home": 2.0, "draw": 3.5, "away": 4.0},
        **overrides,
    )


def test_odds_validation_requires_finite_decimal_price_above_one() -> None:
    assert implied_probability(2.0) == pytest.approx(0.5)

    for invalid in (None, True, 1.0, 0.0, -2.0, float("inf"), float("-inf"), float("nan")):
        with pytest.raises(MarketPriorError, match="finite number greater than one"):
            implied_probability(invalid)


def test_invalid_or_incomplete_1x2_selection_fails_closed() -> None:
    bad_selection = odds_snapshot(
        "odds-bad-selection",
        "2026-09-17T11:30:00+00:00",
        {"home": 2.0, "draw": 3.5, "visitor": 4.0},
    )
    null_price = odds_snapshot(
        "odds-null",
        "2026-09-17T11:35:00+00:00",
        {"home": 2.0, "draw": None, "away": 4.0},
        bookmaker="bookmaker-b",
    )

    prior = build_market_prior(FIXTURE_ID, CUTOFF, [bad_selection, null_price])

    assert prior["status"] == "unavailable"
    assert prior["probabilities"] is None
    assert {item["reason"] for item in prior["excluded_snapshots"]} == {
        "invalid_1x2_selection",
        "invalid_decimal_odds",
    }
    with pytest.raises(MarketPriorError, match="complete 1X2"):
        multiplicative_devig({"home": 2.0, "draw": 3.5, "visitor": 4.0})


def test_implied_probability_devig_and_margin_match_reference_example() -> None:
    result = multiplicative_devig({"home": 2.0, "draw": 3.5, "away": 4.0})

    assert result["raw_implied_probability"] == pytest.approx(
        {"home": 0.5, "draw": 1 / 3.5, "away": 0.25}
    )
    assert result["market_margin"] == pytest.approx(0.0357142857, abs=1e-6)
    assert result["probabilities"] == pytest.approx(
        {"home": 0.4827586, "draw": 0.2758621, "away": 0.2413793},
        abs=1e-6,
    )
    assert sum(result["probabilities"].values()) == pytest.approx(1.0)


def test_cutoff_equality_is_allowed_and_later_snapshot_is_rejected() -> None:
    at_cutoff = valid_snapshot("odds-at-cutoff", CUTOFF)
    after_cutoff = valid_snapshot(
        "odds-after-cutoff",
        "2026-09-17T12:00:01+00:00",
    )

    prior = build_market_prior(FIXTURE_ID, CUTOFF, [at_cutoff, after_cutoff])

    assert prior["status"] == "available"
    assert prior["source_odds_snapshot_ids"] == ["odds-at-cutoff"]
    assert prior["latest_available_at"] == CUTOFF


@pytest.mark.parametrize(
    ("source_updated_at", "reason"),
    [
        ("not-a-timestamp", "invalid_source_updated_at"),
        ("2026-09-17T12:00:01+00:00", "future_source_updated_at"),
    ],
)
def test_snapshot_source_updated_at_cannot_be_masked_by_empty_quote_value(
    source_updated_at: str,
    reason: str,
) -> None:
    snapshot = valid_snapshot(source_updated_at=source_updated_at)
    for quote in snapshot["quotes"]:
        quote["source_updated_at"] = None

    prior = build_market_prior(FIXTURE_ID, CUTOFF, [snapshot])

    assert prior["status"] == "unavailable"
    assert prior["excluded_snapshots"] == [{"snapshot_id": "odds-valid", "reason": reason}]


def test_unsupported_market_does_not_create_a_market_prior() -> None:
    snapshot = valid_snapshot()
    for quote in snapshot["quotes"]:
        quote["market"] = "unsupported"

    prior = build_market_prior(FIXTURE_ID, CUTOFF, [snapshot])

    assert prior["status"] == "unavailable"
    assert prior["excluded_snapshots"] == [
        {"snapshot_id": "odds-valid", "reason": "incomplete_1x2_market"}
    ]


def test_latest_complete_snapshot_per_bookmaker_is_equally_aggregated() -> None:
    bookmaker_a_old = odds_snapshot(
        "a-old",
        "2026-09-17T10:00:00+00:00",
        {"home": 2.0, "draw": 3.4, "away": 4.2},
    )
    bookmaker_a_latest = odds_snapshot(
        "a-latest",
        "2026-09-17T11:00:00+00:00",
        {"home": 1.8, "draw": 3.6, "away": 5.0},
    )
    bookmaker_a_incomplete = odds_snapshot(
        "a-incomplete",
        "2026-09-17T11:30:00+00:00",
        {"home": 1.7, "draw": 3.8},
    )
    bookmaker_b_latest = odds_snapshot(
        "b-latest",
        "2026-09-17T11:15:00+00:00",
        {"home": 2.5, "draw": 3.2, "away": 3.0},
        bookmaker="bookmaker-b",
    )
    expected_a = multiplicative_devig({"home": 1.8, "draw": 3.6, "away": 5.0})["probabilities"]
    expected_b = multiplicative_devig({"home": 2.5, "draw": 3.2, "away": 3.0})["probabilities"]

    prior = build_market_prior(
        FIXTURE_ID,
        CUTOFF,
        [bookmaker_a_old, bookmaker_a_latest, bookmaker_a_incomplete, bookmaker_b_latest],
    )

    expected = {
        outcome: (expected_a[outcome] + expected_b[outcome]) / 2
        for outcome in ("home", "draw", "away")
    }
    assert prior["status"] == "available"
    assert prior["bookmaker_count"] == 2
    assert set(prior["source_odds_snapshot_ids"]) == {"a-latest", "b-latest"}
    assert prior["probabilities"] == pytest.approx(expected, abs=1e-11)
    assert sum(prior["probabilities"].values()) == pytest.approx(1.0)
    assert {item["snapshot_id"]: item["reason"] for item in prior["excluded_snapshots"]} == {
        "a-incomplete": "incomplete_1x2_market",
    }
    assert prior["eligible_snapshot_count"] == 3
    assert prior["superseded_snapshot_count"] == 1


def test_missing_market_data_returns_explicit_model_only_result() -> None:
    model = round4_result()

    result = Round5ProbabilityEngine().calculate(model, [])

    assert result["market_status"] == "MODEL_ONLY"
    assert result["market_prior"] is None
    assert result["final_probability"] == result["model_probability"]
    assert result["market_prior_detail"]["missing_reason"] == "no_complete_cutoff_safe_1x2_market"
    assert result["round5_probability_audit"]["market_fusion_count"] == 0
    assert result["market_snapshot"]["overround"] is None
    assert result["market_snapshot"]["payload"]["market_prior"]["missing_reason"] == (
        "no_complete_cutoff_safe_1x2_market"
    )


def test_model_only_preserves_the_exact_round4_probability_values() -> None:
    probabilities = {
        "home": 0.3333333333334,
        "draw": 0.3333333333333,
        "away": 0.3333333333333,
    }

    result = Round5ProbabilityEngine().calculate(round4_result(probabilities), [])

    assert result["model_probability"] == probabilities
    assert result["final_probability"] == probabilities


def test_fixed_60_40_fusion_is_normalized() -> None:
    config = MarketPriorConfig()
    model = {"home": 0.50, "draw": 0.30, "away": 0.20}
    market = {"home": 0.40, "draw": 0.35, "away": 0.25}

    fused = deterministic_fusion(model, market, config=config)

    assert config.model_weight == pytest.approx(0.60)
    assert config.market_weight == pytest.approx(0.40)
    assert fused == pytest.approx({"home": 0.46, "draw": 0.32, "away": 0.22})
    assert sum(fused.values()) == pytest.approx(1.0)


def test_fusion_is_exactly_once_and_replay_is_identical() -> None:
    engine = Round5ProbabilityEngine()
    model = round4_result()
    snapshots = [valid_snapshot()]

    first = engine.calculate(model, snapshots)
    replay = engine.calculate(deepcopy(model), deepcopy(snapshots))

    assert first == replay
    assert first["market_status"] == "MODEL_PLUS_MARKET"
    assert first["round5_probability_audit"]["market_fusion_count"] == 1
    assert first["round5_probability_audit"]["no_ml"] is True
    assert first["round5_probability_audit"]["no_llm_numeric_probability"] is True
    with pytest.raises(MarketPriorError, match="already been applied"):
        engine.calculate(first, snapshots)


def test_model_and_market_inputs_remain_independent() -> None:
    engine = Round5ProbabilityEngine()
    original_model = round4_result()
    original_copy = deepcopy(original_model)
    first_market = [valid_snapshot()]
    changed_market = [
        odds_snapshot(
            "odds-changed",
            "2026-09-17T11:30:00+00:00",
            {"home": 1.6, "draw": 4.2, "away": 6.0},
        )
    ]

    first = engine.calculate(original_model, first_market)
    odds_changed = engine.calculate(original_model, changed_market)
    model_changed = engine.calculate(
        round4_result({"home": 0.35, "draw": 0.35, "away": 0.30}),
        first_market,
    )

    assert original_model == original_copy
    assert first["model_probability"] == odds_changed["model_probability"]
    assert first["final_probability"] != odds_changed["final_probability"]
    assert first["market_prior"] == model_changed["market_prior"]
    assert first["model_probability"] != model_changed["model_probability"]


def test_kickoff_freeze_disables_market_fusion() -> None:
    result = Round5ProbabilityEngine().calculate(
        round4_result(),
        [valid_snapshot("odds-at-cutoff", CUTOFF)],
        kickoff=CUTOFF,
    )

    assert result["market_status"] == "MODEL_ONLY"
    assert result["market_fusion_applied"] is False
    assert result["market_prior_detail"]["missing_reason"] == "prediction_cutoff_not_before_kickoff"
    assert result["market_snapshot"]["overround"] is None


def test_round4_market_independence_and_no_ml_audits_are_required() -> None:
    engine = Round5ProbabilityEngine()

    for failed_check, message in (
        ("market_independent", "market-independent"),
        ("no_ml", "no-ML audit"),
    ):
        invalid = round4_result()
        invalid["probability_audit"]["checks"][failed_check] = False
        with pytest.raises(MarketPriorError, match=message):
            engine.calculate(invalid, [valid_snapshot()])

    for field in ("feature_snapshot_id", "probability_model_version", "calculation_version"):
        invalid = round4_result()
        invalid.pop(field)
        with pytest.raises(MarketPriorError, match=field):
            engine.calculate(invalid, [valid_snapshot()])


def test_model_only_audit_can_be_persisted_with_missing_reason(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "round5-model-only.db"))
    repository.initialize()
    result = Round5ProbabilityEngine().calculate(round4_result(), [])

    snapshot_id = persist_round5_market_snapshot(repository, result)
    assert persist_round5_market_snapshot(repository, deepcopy(result)) == snapshot_id

    stored = repository.market_snapshots(FIXTURE_ID)
    assert [item["market_snapshot_id"] for item in stored] == [snapshot_id]
    assert stored[0]["overround"] is None
    assert stored[0]["payload"]["audit"]["market_status"] == "MODEL_ONLY"
    assert stored[0]["payload"]["market_prior"]["missing_reason"] == (
        "no_complete_cutoff_safe_1x2_market"
    )


def test_market_snapshot_persistence_is_append_only_and_immutable(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "round5.db"))
    repository.initialize()
    engine = Round5ProbabilityEngine()
    first = engine.calculate(round4_result(), [valid_snapshot()])

    first_id = persist_round5_market_snapshot(repository, first)
    assert persist_round5_market_snapshot(repository, deepcopy(first)) == first_id
    assert [item["market_snapshot_id"] for item in repository.market_snapshots(FIXTURE_ID)] == [first_id]

    changed_record = deepcopy(first["market_snapshot"])
    changed_record["payload"]["audit"]["final_probability"]["home"] = 0.99
    with pytest.raises(ValueError, match="immutable"):
        repository.save_market_snapshot(changed_record)

    later_model = round4_result()
    later_model["prediction_cutoff_at"] = "2026-09-17T12:30:00+00:00"
    second = engine.calculate(later_model, [valid_snapshot()])
    second_id = persist_round5_market_snapshot(repository, second)

    assert second_id != first_id
    assert len(repository.market_snapshots(FIXTURE_ID)) == 2
