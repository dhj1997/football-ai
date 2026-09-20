"""ClubElo integration: free club Elo ratings (api.clubelo.com, no key).

Ratings are stored as one snapshot row (``clubeelo/ratings``) keyed by the
Chinese team name so prediction-time Elo lookups use professional,
cross-season ratings as-of the sync date. Point-in-time: the snapshot
records the validity window returned by ClubElo.
"""

from __future__ import annotations

import asyncio
import csv
import io
import uuid
from datetime import UTC, datetime
from typing import Any, Mapping

import httpx

from .prediction_intelligence import parse_timestamp

BASE_URL = "https://api.clubelo.com"


class ClubEloProvider:
    source_name = "clubeelo"

    def __init__(
        self,
        base_url: str = BASE_URL,
        *,
        timeout_seconds: float = 15.0,
        max_retries: int = 1,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.max_retries = max(0, int(max_retries))

    async def fetch_on(self, date_iso: str | None = None) -> str:
        """CSV ratings for one date (defaults to today)."""

        day = (date_iso or datetime.now(UTC).date().isoformat())[:10]
        timeout = httpx.Timeout(self.timeout_seconds, connect=min(5.0, self.timeout_seconds))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            for attempt in range(self.max_retries + 1):
                try:
                    response = await client.get(f"{self.base_url}/{day}")
                    response.raise_for_status()
                    return response.text
                except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as error:
                    retryable = not isinstance(error, httpx.HTTPStatusError) or error.response.status_code >= 500
                    if not retryable or attempt >= self.max_retries:
                        raise
                    await asyncio.sleep(0.5 * (attempt + 1))
        raise RuntimeError("ClubElo request exhausted without a response")


async def refresh_ratings(repository: Any, provider: ClubEloProvider, *, localize: Any = None) -> dict[str, Any]:
    """Fetch, validate, store, and record one observable ClubElo sync."""

    run = _start_sync_run(repository)
    had_snapshot = bool(getattr(repository, "team_snapshot", lambda *_: None)("clubeelo", "ratings"))
    try:
        csv_text = await provider.fetch_on()
        result = sync_ratings(repository, csv_text, localize=localize)
        empty = result.get("status") != "ok"
        _finish_sync_run(
            repository,
            run,
            status="partial" if empty else "completed",
            records_seen=int(result.get("ratings") or 0),
            records_updated=int(result.get("ratings") or 0),
            error_category="empty_response" if empty else None,
            errors=["ClubElo response contained no valid ratings"] if empty else [],
        )
        return {
            **result,
            "last_good_snapshot_preserved": had_snapshot and empty,
            "errors": ["ClubElo response contained no valid ratings"] if empty else [],
        }
    except Exception as error:
        _finish_sync_run(
            repository,
            run,
            status="failed",
            error_category=type(error).__name__,
            errors=[str(error)[:300]],
        )
        raise


def parse_elo_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse the ClubElo CSV (header-based, tolerant to column order)."""

    reader = csv.DictReader(io.StringIO(csv_text))
    rows: list[dict[str, Any]] = []
    for row in reader:
        normalized = {(key or "").strip().casefold(): (value or "").strip() for key, value in row.items() if key}
        club = normalized.get("club")
        rating_text = normalized.get("elo") or normalized.get("rating") or normalized.get("ratingpoints")
        if not club:
            continue
        try:
            rating = float(rating_text)
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "club": club,
                "rating": rating,
                "rank": normalized.get("rank") or None,
                "league": normalized.get("league") or None,
                "country": normalized.get("country") or None,
                "from": normalized.get("from") or None,
                "to": normalized.get("to") or None,
            }
        )
    return rows


def sync_ratings(repository: Any, csv_text: str, *, localize: Any = None) -> dict[str, Any]:
    """Store all ratings as one snapshot keyed by Chinese team name."""

    rows = parse_elo_csv(csv_text)
    if not rows:
        return {"status": "empty", "ratings": 0}
    localize = localize or (lambda value: value)
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    ratings: dict[str, Any] = {}
    for row in rows:
        key = localize(row["club"])
        ratings[key] = {
            "rating": row["rating"],
            "club": row["club"],
            "league": row.get("league"),
            "from": row.get("from"),
            "to": row.get("to"),
        }
    saver = getattr(repository, "save_team_snapshot", None)
    if not callable(saver):
        raise RuntimeError("repository does not support team snapshots")
    saver(
        {
            "league_key": "clubeelo",
            "team_id": "ratings",
            "season": None,
            "updated_at": now,
            "ratings": ratings,
            "source": "clubeelo",
            "rating_count": len(ratings),
        }
    )
    return {"status": "ok", "ratings": len(ratings), "updated_at": now}


def stored_ratings(repository: Any, *, as_of: Any | None = None) -> dict[str, float]:
    """Read the stored rating map (Chinese name -> rating) for predictions."""

    reader = getattr(repository, "team_snapshot", None)
    if not callable(reader):
        return {}
    snapshot = reader("clubeelo", "ratings") or {}
    cutoff = parse_timestamp(as_of)
    updated_at = parse_timestamp(snapshot.get("updated_at"))
    if cutoff is not None and (updated_at is None or updated_at > cutoff):
        return {}
    ratings = (snapshot.get("payload") or snapshot).get("ratings") or {}
    result: dict[str, float] = {}
    for key, item in ratings.items():
        try:
            result[str(key)] = float(item["rating"]) if isinstance(item, Mapping) else float(item)
        except (TypeError, ValueError, KeyError):
            continue
    return result


def _start_sync_run(repository: Any) -> dict[str, Any]:
    run = {
        "run_id": f"sync:{uuid.uuid4()}",
        "provider": "clubeelo",
        "league": None,
        "entity_type": "team_rating",
        "started_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "finished_at": None,
        "status": "running",
        "records_seen": 0,
        "records_inserted": 0,
        "records_updated": 0,
        "records_rejected": 0,
        "error_category": None,
        "errors": [],
        "config": {"source": "api.clubelo.com"},
    }
    saver = getattr(repository, "save_data_sync_run", None)
    if callable(saver):
        saver(run)
    return run


def _finish_sync_run(repository: Any, run: dict[str, Any], **updates: Any) -> None:
    updates["finished_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    updater = getattr(repository, "update_data_sync_run", None)
    if callable(updater):
        updater(run["run_id"], updates)
