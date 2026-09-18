"""ClubElo integration: free club Elo ratings (api.clubelo.com, no key).

Ratings are stored as one snapshot row (``clubeelo/ratings``) keyed by the
Chinese team name so prediction-time Elo lookups use professional,
cross-season ratings as-of the sync date. Point-in-time: the snapshot
records the validity window returned by ClubElo.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Any, Mapping

import httpx

from .prediction_intelligence import parse_timestamp

BASE_URL = "https://api.clubelo.com"


class ClubEloProvider:
    source_name = "clubeelo"

    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    async def fetch_on(self, date_iso: str | None = None) -> str:
        """CSV ratings for one date (defaults to today)."""

        day = (date_iso or datetime.now(UTC).date().isoformat())[:10]
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(f"{self.base_url}/{day}")
            response.raise_for_status()
            return response.text


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
