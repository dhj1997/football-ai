"""P11 Market Intelligence: odds timelines, de-vig market probabilities, CLV.

Market information stays in its regulated positions: it feeds research
signals and the P0/P2 market-decision layer — never model probabilities
and never bet qualification on its own. Original odds snapshots are only
read here; they are never overwritten.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from statistics import median
from typing import Any, Iterable, Mapping

from .historical_validation import parse_timestamp

MARKET_MARKETS: tuple[str, ...] = ("1x2", "asian_handicap", "over_under")
THREE_WAY_MARKETS: frozenset[str] = frozenset({"1x2"})
MARKET_SNAPSHOT_VERSION = "p11-market-v1"


def normalize_quote(row: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize one stored odds quote; invalid odds are flagged, not dropped."""

    try:
        price = float(row.get("price") if row.get("price") is not None else row.get("decimal_odds"))
    except (TypeError, ValueError):
        price = 0.0
    captured = parse_timestamp(row.get("captured_at"))
    market = str(row.get("market") or "").casefold()
    invalid_reason = None
    if price <= 1.0:
        invalid_reason = "decimal_odds_must_exceed_one"
    if captured is None:
        invalid_reason = invalid_reason or "missing_or_invalid_captured_at"
    if market not in MARKET_MARKETS:
        invalid_reason = invalid_reason or f"unsupported_market_{market or 'unknown'}"
    return {
        "snapshot_id": str(row.get("snapshot_id") or row.get("id") or ""),
        "fixture_id": str(row.get("fixture_id") or ""),
        "market": market,
        "selection": str(row.get("selection") or "").casefold(),
        "line": row.get("line"),
        "decimal_odds": price,
        "bookmaker": str(row.get("bookmaker") or "unknown"),
        "source": str(row.get("source") or "unknown"),
        "captured_at": captured.isoformat() if captured else row.get("captured_at"),
        "captured_at_parsed": captured,
        "source_updated_at": row.get("source_updated_at"),
        "is_valid": invalid_reason is None,
        "invalid_reason": invalid_reason,
    }


def _flat_quotes(odds_snapshots: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    quotes: list[dict[str, Any]] = []
    for snapshot in odds_snapshots:
        inner = snapshot.get("quotes")
        if isinstance(inner, list) and inner:
            for quote in inner:
                merged = {**snapshot, **quote}
                merged.pop("quotes", None)
                quotes.append(normalize_quote(merged))
            continue
        quotes.append(normalize_quote(snapshot))
    return quotes


def devig_market(group: Iterable[Mapping[str, Any]], *, market: str) -> dict[str, Any] | None:
    """De-vig one bookmaker snapshot into raw/normalized probabilities.

    Uses only selections from the same snapshot so the overround reflects
    one bookmaker's margin. Snapshots with an impossible margin are marked
    invalid instead of silently normalized.
    """

    rows = [row for row in group if row.get("is_valid") and row.get("market") == market]
    if not rows:
        return None
    if market in THREE_WAY_MARKETS:
        required = {"home", "draw", "away"}
        selections = {row.get("selection") for row in rows}
        if not required <= selections:
            return None
        wanted = tuple(sorted(required))
    else:
        pairs = sorted({row.get("selection") for row in rows})
        if len(pairs) < 2:
            return None
        wanted = tuple(pairs[:2])
    implied: dict[str, float] = {}
    for selection in wanted:
        row = next(item for item in rows if item.get("selection") == selection)
        implied[selection] = round(1.0 / float(row["decimal_odds"]), 6)
    overround = round(sum(implied.values()) - 1.0, 6)
    total = sum(implied.values())
    anchor = rows[0]
    return {
        "market_snapshot_version": MARKET_SNAPSHOT_VERSION,
        "market": market,
        "snapshot_id": anchor.get("snapshot_id"),
        "fixture_id": anchor.get("fixture_id"),
        "bookmaker": anchor.get("bookmaker"),
        "source": anchor.get("source"),
        "captured_at": anchor.get("captured_at"),
        "captured_at_parsed": anchor.get("captured_at_parsed"),
        "raw_implied_probability": implied,
        "overround": overround,
        "normalized_probabilities": {key: round(value / total, 6) for key, value in implied.items()},
        "is_valid": overround > 0,
        "invalid_reason": None if overround > 0 else "non_positive_overround",
    }


def build_market_snapshots(quotes: Iterable[Mapping[str, Any]], *, cutoff: Any = None) -> list[dict[str, Any]]:
    """Group normalized quotes into per-bookmaker-capture de-vig snapshots."""

    cutoff_at = parse_timestamp(cutoff)
    groups: dict[str, list[dict[str, Any]]] = {}
    for quote in quotes:
        if not quote.get("is_valid"):
            continue
        if cutoff_at and quote.get("captured_at_parsed") and quote["captured_at_parsed"] > cutoff_at:
            continue
        key = "|".join(
            (
                str(quote.get("snapshot_id")),
                str(quote.get("market")),
                str(quote.get("bookmaker")),
                str(quote.get("captured_at")),
            )
        )
        groups.setdefault(key, []).append(quote)
    snapshots = []
    for key in sorted(groups):
        snapshot = devig_market(groups[key], market=groups[key][0].get("market"))
        if snapshot and snapshot.get("is_valid"):
            snapshots.append(snapshot)
    snapshots.sort(key=lambda item: item.get("captured_at_parsed") or datetime.min.replace(tzinfo=UTC))
    return snapshots


def market_consensus(market_snapshots: Iterable[Mapping[str, Any]], *, market: str) -> dict[str, Any] | None:
    """Consensus and dispersion across bookmakers at one market level."""

    rows = [item for item in market_snapshots if item.get("market") == market and item.get("is_valid")]
    if not rows:
        return None
    selections = sorted({key for row in rows for key in row["normalized_probabilities"]})
    consensus: dict[str, float] = {}
    dispersion: dict[str, dict[str, float]] = {}
    for selection in selections:
        values = [float(row["normalized_probabilities"][selection]) for row in rows if selection in row["normalized_probabilities"]]
        if not values:
            continue
        consensus[selection] = round(median(values), 6)
        dispersion[selection] = {
            "min": round(min(values), 6),
            "max": round(max(values), 6),
            "spread": round(max(values) - min(values), 6),
        }
    latest = rows[-1]
    return {
        "market": market,
        "bookmaker_count": len({row.get("bookmaker") for row in rows}),
        "source_count": len({row.get("source") for row in rows}),
        "snapshot_count": len(rows),
        "consensus_probabilities": consensus,
        "dispersion": dispersion,
        "latest_captured_at": latest.get("captured_at"),
        "latest_snapshot_id": latest.get("snapshot_id"),
    }


def build_odds_timeline(
    quotes: Iterable[Mapping[str, Any]],
    *,
    market: str,
    selection: str | None = None,
    kickoff: Any = None,
    cutoff: Any = None,
) -> dict[str, Any]:
    """Ordered timeline for one market selection with movement and cutoffs.

    A timeline tracks one selection so movement stays coherent. ``cutoff``
    marks the latest timestamp usable as a decision input; later quotes
    stay in the timeline flagged ``post_cutoff`` for post-game research
    only. Closing is always the last quote strictly before kickoff.
    """

    cutoff_at = parse_timestamp(cutoff)
    kickoff_at = parse_timestamp(kickoff)
    events = sorted(
        (
            row
            for row in quotes
            if row.get("market") == market
            and row.get("is_valid")
            and (selection is None or row.get("selection") == selection)
        ),
        key=lambda row: (row.get("captured_at_parsed") or datetime.min.replace(tzinfo=UTC), str(row.get("snapshot_id")), str(row.get("selection"))),
    )
    pre_cutoff = [row for row in events if cutoff_at is None or (row.get("captured_at_parsed") and row["captured_at_parsed"] <= cutoff_at)]
    pre_kickoff = [row for row in events if kickoff_at is None or (row.get("captured_at_parsed") and row["captured_at_parsed"] < kickoff_at)]
    opening = pre_cutoff[0] if pre_cutoff else None
    current = pre_cutoff[-1] if pre_cutoff else None
    closing = pre_kickoff[-1] if pre_kickoff else None
    movement: dict[str, Any] | None = None
    if opening and current and opening is not current:
        absolute = round(float(current["decimal_odds"]) - float(opening["decimal_odds"]), 6)
        relative = round(absolute / float(opening["decimal_odds"]), 6) if float(opening["decimal_odds"]) else None
        movement = {
            "absolute": absolute,
            "relative": relative,
            "direction": "up" if absolute > 0 else "down" if absolute < 0 else "flat",
        }
    selection_value = selection or (current.get("selection") if current else None)
    return {
        "market": market,
        "selection": selection_value,
        "opening": _public_event(opening),
        "current": _public_event(current),
        "closing": _public_event(closing),
        "movement": movement,
        "event_count": len(pre_cutoff),
        "post_cutoff_count": len(events) - len(pre_cutoff),
        "post_cutoff_events": [
            _public_event(row, extra={"usage": "post_cutoff_research_only"})
            for row in events
            if row not in pre_cutoff
        ],
        "cutoff": cutoff_at.isoformat() if cutoff_at else None,
    }


def _public_event(row: Mapping[str, Any] | None, *, extra: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    if row is None:
        return None
    event = {
        "snapshot_id": row.get("snapshot_id"),
        "selection": row.get("selection"),
        "line": row.get("line"),
        "decimal_odds": row.get("decimal_odds"),
        "bookmaker": row.get("bookmaker"),
        "source": row.get("source"),
        "captured_at": row.get("captured_at"),
    }
    if extra:
        event.update(extra)
    return event


def model_vs_market(
    model_probabilities: Mapping[str, Any] | None,
    market_snapshot: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Research signal only: model minus de-vigged market probability.

    The result never carries execution semantics; bet qualification stays
    with the P0/P2 market-decision layer.
    """

    if not isinstance(model_probabilities, Mapping) or not isinstance(market_snapshot, Mapping):
        return None
    edges: dict[str, float] = {}
    for selection, market_probability in market_snapshot.get("normalized_probabilities", {}).items():
        try:
            model_probability = float(model_probabilities.get(selection))
        except (TypeError, ValueError):
            continue
        edges[selection] = round(model_probability - float(market_probability), 6)
    if not edges:
        return None
    return {
        "market": market_snapshot.get("market"),
        "market_captured_at": market_snapshot.get("captured_at"),
        "market_snapshot_id": market_snapshot.get("snapshot_id"),
        "edge": edges,
        "role": "research_signal",
        "note": "edge 只是研究信号，不构成下注资格；执行决定仍由 P0/P2 市场决策层产生",
    }


def compute_clv_with_reason(
    *,
    bet_odds: Any,
    closing_odds: Any,
    decided_at: Any = None,
    closing_captured_at: Any = None,
) -> dict[str, Any]:
    """CLV with explicit null reasons; nothing is fabricated.

    CLV is only computed when both prices exist and the closing capture is
    verifiably at or after the decision time.
    """

    decided = parse_timestamp(decided_at)
    closing_captured = parse_timestamp(closing_captured_at)
    try:
        bet_price = float(bet_odds)
    except (TypeError, ValueError):
        bet_price = 0.0
    try:
        close_price = float(closing_odds)
    except (TypeError, ValueError):
        close_price = 0.0
    if bet_price <= 0:
        return {"clv": None, "reason": "missing_bet_price"}
    if close_price <= 0:
        return {"clv": None, "reason": "missing_closing_line"}
    if decided is None:
        return {"clv": None, "reason": "missing_decision_timestamp"}
    if closing_captured is None:
        return {"clv": None, "reason": "closing_line_timestamp_unknown"}
    if closing_captured < decided:
        return {"clv": None, "reason": "closing_line_not_after_decision"}
    return {"clv": round(bet_price / close_price - 1.0, 4), "reason": None}


def market_snapshot_record(fixture_id: str, snapshots: Iterable[Mapping[str, Any]], *, consensus: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    """Build one persistable market-snapshot record for a fixture."""

    rows = [dict(item) for item in snapshots]
    if not rows:
        return None
    latest = rows[-1]
    captured = latest.get("captured_at_parsed") or parse_timestamp(latest.get("captured_at"))
    if captured is None:
        return None
    payload = {
        "market_snapshot_version": MARKET_SNAPSHOT_VERSION,
        "fixture_id": fixture_id,
        "market": latest.get("market"),
        "captured_at": captured.isoformat(),
        "snapshot_count": len(rows),
        "bookmaker_count": len({row.get("bookmaker") for row in rows}),
        "source_count": len({row.get("source") for row in rows}),
        "snapshots": [{key: value for key, value in row.items() if key != "captured_at_parsed"} for row in rows],
        "consensus": dict(consensus) if consensus else None,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    market_snapshot_id = f"market:{hashlib.sha256(canonical.encode()).hexdigest()[:32]}"
    return {
        **payload,
        "market_snapshot_id": market_snapshot_id,
        "overround": latest.get("overround"),
        "payload": payload,
    }


class MarketIntelligenceService:
    """Read-only market research layer over the immutable odds snapshots."""

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def report(
        self,
        fixture_id: str,
        *,
        model_probabilities: Mapping[str, Any] | None = None,
        cutoff: Any = None,
        kickoff: Any = None,
        markets: Iterable[str] = ("1x2",),
    ) -> dict[str, Any]:
        quotes = _flat_quotes(
            self.repository.odds_snapshots(fixture_id) if callable(getattr(self.repository, "odds_snapshots", None)) else []
        )
        market_snapshots = build_market_snapshots(quotes, cutoff=cutoff)
        sections: dict[str, Any] = {}
        consensus_by_market: dict[str, Any] = {}
        for market in markets:
            market_rows = [item for item in market_snapshots if item.get("market") == market]
            consensus = market_consensus(market_rows, market=market)
            consensus_by_market[market] = consensus
            selections = sorted(
                {
                    str(row.get("selection"))
                    for row in quotes
                    if row.get("market") == market and row.get("is_valid")
                }
            )
            section: dict[str, Any] = {
                "consensus": consensus,
                "snapshot_count": len(market_rows),
                "invalid_quote_count": sum(1 for row in quotes if row.get("market") == market and not row.get("is_valid")),
                "timelines": {
                    selection_name: build_odds_timeline(
                        quotes,
                        market=market,
                        selection=selection_name,
                        kickoff=kickoff,
                        cutoff=cutoff,
                    )
                    for selection_name in selections
                },
            }
            sections[market] = section
            if consensus:
                divergence = model_vs_market(
                    model_probabilities,
                    {
                        "market": market,
                        "normalized_probabilities": consensus["consensus_probabilities"],
                        "captured_at": consensus["latest_captured_at"],
                        "snapshot_id": consensus["latest_snapshot_id"],
                    },
                )
                if divergence:
                    sections[market]["model_vs_market"] = divergence
        return {
            "fixture_id": fixture_id,
            "quote_count": len(quotes),
            "invalid_quote_count": sum(1 for row in quotes if not row.get("is_valid")),
            "cutoff": parse_timestamp(cutoff).isoformat() if parse_timestamp(cutoff) else None,
            "markets": sections,
            "bet_clv": self._bet_clv(fixture_id),
        }

    def _bet_clv(self, fixture_id: str) -> list[dict[str, Any]]:
        reader = getattr(self.repository, "bets", None)
        if not callable(reader):
            return []
        try:
            bet_rows = reader(fixture_id=fixture_id)
        except TypeError:
            return []
        results: list[dict[str, Any]] = []
        for bet in bet_rows or []:
            results.append(
                {
                    "bet_id": bet.get("id") or bet.get("prediction_id"),
                    **compute_clv_with_reason(
                        bet_odds=bet.get("bet_odds") or bet.get("odds"),
                        closing_odds=bet.get("closing_odds"),
                        decided_at=bet.get("created_at") or bet.get("placed_at"),
                        closing_captured_at=bet.get("closing_odds_captured_at"),
                    ),
                }
            )
        return results

    def persist_market_snapshots(self, fixture_id: str, *, kickoff: Any = None) -> dict[str, Any]:
        """Compute and persist market snapshots for research records (idempotent)."""

        quotes = _flat_quotes(
            self.repository.odds_snapshots(fixture_id) if callable(getattr(self.repository, "odds_snapshots", None)) else []
        )
        market_snapshots = build_market_snapshots(quotes)
        report = self.report(fixture_id, kickoff=kickoff, markets=("1x2", "asian_handicap", "over_under"))
        saver = getattr(self.repository, "save_market_snapshot", None)
        persisted: list[str] = []
        for market in ("1x2", "asian_handicap", "over_under"):
            market_rows = [item for item in market_snapshots if item.get("market") == market]
            record = market_snapshot_record(fixture_id, market_rows, consensus=report["markets"].get(market, {}).get("consensus"))
            if record and callable(saver):
                saver(record)
                persisted.append(record["market_snapshot_id"])
        report["persisted_market_snapshot_ids"] = persisted
        return report
