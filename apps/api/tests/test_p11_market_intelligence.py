"""P11 market intelligence: normalization, timeline, consensus, CLV tests."""

from datetime import UTC, datetime, timedelta

from app.market_intelligence import (
    MarketIntelligenceService,
    build_market_snapshots,
    build_odds_timeline,
    compute_clv_with_reason,
    devig_market,
    market_consensus,
    market_snapshot_record,
    model_vs_market,
    normalize_quote,
)


def quote(selection: str, price: float, captured_at: str, **overrides) -> dict:
    values = {
        "snapshot_id": f"snap-{captured_at}",
        "fixture_id": "sportsdb-1",
        "market": "1x2",
        "selection": selection,
        "line": None,
        "price": price,
        "bookmaker": "bet365",
        "source": "dongqiudi",
        "captured_at": captured_at,
    }
    values.update(overrides)
    return normalize_quote(values)


def one_snapshot(captured_at: str, home=2.0, draw=3.5, away=4.0, **overrides) -> list[dict]:
    rows = [quote("home", home, captured_at), quote("draw", draw, captured_at), quote("away", away, captured_at)]
    if overrides:
        for row in rows:
            row.update(overrides)
    return rows


def test_normalize_quote_flags_invalid_odds_without_dropping() -> None:
    valid = quote("home", 2.0, "2026-09-01T08:00:00+00:00")
    assert valid["is_valid"] is True
    assert valid["source"] == "dongqiudi"
    assert valid["captured_at"] == "2026-09-01T08:00:00+00:00"

    bad_price = normalize_quote({**quote("home", 2.0, "2026-09-01T08:00:00+00:00"), "price": 0.5})
    assert bad_price["is_valid"] is False
    assert bad_price["invalid_reason"] == "decimal_odds_must_exceed_one"

    no_time = normalize_quote({**quote("home", 2.0, "2026-09-01T08:00:00+00:00"), "captured_at": ""})
    assert no_time["is_valid"] is False
    assert no_time["invalid_reason"] == "missing_or_invalid_captured_at"


def test_devig_is_reproducible_and_preserves_the_margin() -> None:
    rows = one_snapshot("2026-09-01T08:00:00+00:00")
    first = devig_market(rows, market="1x2")
    second = devig_market(list(reversed(rows)), market="1x2")

    assert first == second
    assert first["overround"] > 0
    assert abs(sum(first["normalized_probabilities"].values()) - 1.0) < 1e-5
    # Raw implied probabilities are kept alongside the normalized ones; the
    # de-vig always lowers them because the bookmaker margin is removed.
    assert first["raw_implied_probability"]["home"] == round(1 / 2.0, 6)
    assert first["normalized_probabilities"]["home"] < first["raw_implied_probability"]["home"]


def test_devig_marks_impossible_margin_invalid() -> None:
    # Odds with a guaranteed arbitrage (overround < 0) cannot be a market.
    rows = one_snapshot("2026-09-01T08:00:00+00:00", home=2.6, draw=3.6, away=4.2)
    snapshot = devig_market(rows, market="1x2")

    assert snapshot["is_valid"] is False
    assert snapshot["invalid_reason"] == "non_positive_overround"
    # Invalid snapshots are excluded from the market snapshot list.
    assert build_market_snapshots(rows) == []


def test_timeline_orders_quotes_and_honors_cutoff() -> None:
    quotes = (
        one_snapshot("2026-08-30T08:00:00+00:00", home=2.2)
        + one_snapshot("2026-08-31T08:00:00+00:00", home=2.0)
        + one_snapshot("2026-09-01T08:00:00+00:00", home=1.8)
        + one_snapshot("2026-09-01T20:00:00+00:00", home=1.6)  # after cutoff
    )
    kickoff = "2026-09-01T19:30:00+00:00"
    cutoff = "2026-09-01T12:00:00+00:00"

    timeline = build_odds_timeline(quotes, market="1x2", selection="home", kickoff=kickoff, cutoff=cutoff)

    assert timeline["selection"] == "home"
    assert timeline["opening"]["captured_at"] == "2026-08-30T08:00:00+00:00"
    assert timeline["current"]["captured_at"] == "2026-09-01T08:00:00+00:00"
    assert timeline["closing"]["captured_at"] == "2026-09-01T08:00:00+00:00"
    assert timeline["movement"]["direction"] == "down"
    assert abs(timeline["movement"]["absolute"] + 0.4) < 1e-6
    assert timeline["post_cutoff_count"] == 1
    assert timeline["post_cutoff_events"][0]["usage"] == "post_cutoff_research_only"


def test_closing_uses_last_kickoff_minus_snapshot_not_late_odds() -> None:
    quotes = (
        one_snapshot("2026-09-01T10:00:00+00:00", home=1.9)
        + one_snapshot("2026-09-01T23:00:00+00:00", home=1.5)  # after kickoff
    )

    timeline = build_odds_timeline(quotes, market="1x2", selection="home", kickoff="2026-09-01T19:30:00+00:00")

    # Without a cutoff nothing is "post_cutoff", but closing still only
    # uses the last quote strictly before kickoff.
    assert timeline["closing"]["captured_at"] == "2026-09-01T10:00:00+00:00"
    assert timeline["post_cutoff_count"] == 0


def test_consensus_reports_dispersion_across_bookmakers() -> None:
    snapshots = build_market_snapshots(
        one_snapshot("2026-09-01T08:00:00+00:00")
        + one_snapshot(
            "2026-09-01T08:00:00+00:00",
            bookmaker="crown",
            home=2.1,
            draw=3.4,
            away=3.9,
        )
    )
    consensus = market_consensus(snapshots, market="1x2")

    assert consensus["bookmaker_count"] == 2
    assert consensus["source_count"] == 1
    assert 0 < consensus["consensus_probabilities"]["home"] < 1
    assert consensus["dispersion"]["home"]["spread"] > 0
    assert consensus["latest_captured_at"]


def test_model_vs_market_is_a_research_signal_only() -> None:
    snapshot = devig_market(one_snapshot("2026-09-01T08:00:00+00:00"), market="1x2")
    result = model_vs_market({"home": 0.55, "draw": 0.25, "away": 0.20}, snapshot)

    assert result["role"] == "research_signal"
    assert result["edge"]["home"] > 0
    # No execution semantics leak into the research signal.
    assert not {"recommendation", "stake", "qualified", "bet"} & set(result)

    assert model_vs_market(None, snapshot) is None
    assert model_vs_market({"home": 0.5}, None) is None


def test_clv_requires_both_timestamps_and_prices() -> None:
    decided = "2026-09-01T06:00:00+00:00"
    closing_after = "2026-09-01T10:00:00+00:00"

    ok = compute_clv_with_reason(bet_odds=2.0, closing_odds=1.8, decided_at=decided, closing_captured_at=closing_after)
    assert ok == {"clv": 0.1111, "reason": None}

    missing_close = compute_clv_with_reason(bet_odds=2.0, closing_odds=None, decided_at=decided)
    assert missing_close == {"clv": None, "reason": "missing_closing_line"}

    missing_decision = compute_clv_with_reason(bet_odds=2.0, closing_odds=1.8, closing_captured_at=closing_after)
    assert missing_decision == {"clv": None, "reason": "missing_decision_timestamp"}

    reversed_time = compute_clv_with_reason(bet_odds=2.0, closing_odds=1.8, decided_at=closing_after, closing_captured_at=decided)
    assert reversed_time == {"clv": None, "reason": "closing_line_not_after_decision"}

    unknown_time = compute_clv_with_reason(bet_odds=2.0, closing_odds=1.8, decided_at=decided)
    assert unknown_time == {"clv": None, "reason": "closing_line_timestamp_unknown"}


class FakeMarketRepository:
    def __init__(self, quotes: list[dict] | None = None, bets: list[dict] | None = None) -> None:
        self._quotes = quotes or []
        self._bets = bets or []
        self.saved: list[dict] = []

    def odds_snapshots(self, fixture_id: str | None = None) -> list[dict]:
        return self._quotes

    def bets(self, fixture_id: str = "") -> list[dict]:
        return [bet for bet in self._bets if not fixture_id or bet.get("fixture_id") == fixture_id]

    def save_market_snapshot(self, item: dict) -> None:
        if item["market_snapshot_id"] not in {row["market_snapshot_id"] for row in self.saved}:
            self.saved.append(item)


def _snapshot_with_quotes(fixture_id: str = "sportsdb-1") -> dict:
    captured = "2026-09-01T08:00:00+00:00"
    return {
        "id": f"odds:{captured}",
        "snapshot_id": f"snap-{captured}",
        "fixture_id": fixture_id,
        "quotes": [
            {"market": "1x2", "selection": "home", "line": None, "price": 2.0, "bookmaker": "bet365", "source": "dongqiudi", "captured_at": captured},
            {"market": "1x2", "selection": "draw", "line": None, "price": 3.5, "bookmaker": "bet365", "source": "dongqiudi", "captured_at": captured},
            {"market": "1x2", "selection": "away", "line": None, "price": 4.0, "bookmaker": "bet365", "source": "dongqiudi", "captured_at": captured},
        ],
    }


def test_service_report_shows_timeline_consensus_and_clv_with_reasons() -> None:
    repository = FakeMarketRepository(
        quotes=[_snapshot_with_quotes()],
        bets=[
            {
                "id": "bet-1",
                "fixture_id": "sportsdb-1",
                "bet_odds": 1.9,
                "closing_odds": None,
                "created_at": "2026-09-01T06:00:00+00:00",
            }
        ],
    )
    service = MarketIntelligenceService(repository)

    report = service.report("sportsdb-1", model_probabilities={"home": 0.55, "draw": 0.25, "away": 0.2}, cutoff="2026-09-01T12:00:00+00:00")

    section = report["markets"]["1x2"]
    home_timeline = section["timelines"]["home"]
    assert home_timeline["current"]["source"] == "dongqiudi"
    assert home_timeline["current"]["captured_at"]
    assert section["consensus"]["consensus_probabilities"]
    assert section["model_vs_market"]["role"] == "research_signal"
    assert report["bet_clv"] == [{"bet_id": "bet-1", "clv": None, "reason": "missing_closing_line"}]


def test_persist_market_snapshots_is_idempotent_by_content() -> None:
    repository = FakeMarketRepository(quotes=[_snapshot_with_quotes()])
    service = MarketIntelligenceService(repository)

    first = service.persist_market_snapshots("sportsdb-1")
    second = service.persist_market_snapshots("sportsdb-1")

    assert first["persisted_market_snapshot_ids"]
    assert first["persisted_market_snapshot_ids"] == second["persisted_market_snapshot_ids"]
    assert len(repository.saved) == len(first["persisted_market_snapshot_ids"])
    # One snapshot per supported market that has data (1x2 here).
    assert {item["market"] for item in repository.saved} == {"1x2"}


def test_timeline_never_uses_future_events_for_historical_research() -> None:
    kickoff = datetime.now(UTC) + timedelta(hours=24)
    before = (kickoff - timedelta(hours=6)).isoformat()
    after = (kickoff + timedelta(hours=3)).isoformat()
    quotes = one_snapshot(before, home=1.9) + one_snapshot(after, home=1.4)

    timeline = build_odds_timeline(quotes, market="1x2", selection="home", kickoff=kickoff.isoformat(), cutoff=kickoff.isoformat())

    assert timeline["closing"]["captured_at"] == before
    assert timeline["post_cutoff_count"] == 1
    assert timeline["post_cutoff_events"][0]["captured_at"] == after
    assert timeline["post_cutoff_events"][0]["usage"] == "post_cutoff_research_only"
