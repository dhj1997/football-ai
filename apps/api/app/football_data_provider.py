"""Football-Data.co.uk historical ingestion: results, HT scores and closing odds.

Free CSV archives (1993/94–) for European leagues. One season sync writes
finished fixtures plus one immutable odds snapshot per match; closing odds
are stamped ``captured_at = kickoff`` (that is the definition of a closing
line) with the semantics noted in the payload.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

import httpx

DIVISION_MAP: dict[str, str] = {"epl": "E0", "laliga": "SP1"}
BASE_URL = "https://www.football-data.co.uk/mmz4281"


def season_code(year: int) -> str:
    """2025 (2025-26 season) -> 2526."""

    return f"{year % 100:02d}{(year + 1) % 100:02d}"


def season_csv_url(division_key: str, season_year: int) -> str:
    division = DIVISION_MAP[division_key]
    return f"{BASE_URL}/{season_code(season_year)}/{division}.csv"


async def fetch_season_csv(division_key: str, season_year: int) -> str | None:
    url = season_csv_url(division_key, season_year)
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.content.decode("windows-1252", errors="replace")


def _parse_date(value: str, season_year: int) -> str | None:
    raw = str(value or "").strip()
    match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", raw)
    if match:
        day, month, year = (int(part) for part in match.groups())
        if year < 100:
            year += 2000 if year < 50 else 1900
        try:
            return datetime(year, month, day, 12, 0, tzinfo=UTC).isoformat()
        except ValueError:
            return None
    match = re.match(r"^(\d{1,2})/(\d{1,2})$", raw)
    if match:
        day, month = (int(part) for part in match.groups())
        try:
            return datetime(season_year, month, day, 12, 0, tzinfo=UTC).isoformat()
        except ValueError:
            return None
    return None


def _number(value: Any) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 1.0 else None


def parse_season_csv(csv_text: str, season_year: int) -> list[dict[str, Any]]:
    """Parse one season CSV into normalized match rows (provenance kept)."""

    import csv
    import io

    matches: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        date = _parse_date(row.get("Date"), season_year)
        home = str(row.get("HomeTeam") or "").strip()
        away = str(row.get("AwayTeam") or "").strip()
        try:
            home_goals = int(row.get("FTHG"))
            away_goals = int(row.get("FTAG"))
        except (TypeError, ValueError):
            continue
        if not date or not home or not away:
            continue
        odds: dict[str, Any] = {}
        for group, prefix in (("b365", "B365"), ("avg", "Avg"), ("closing", "PSC")):
            prices = {
                "home": _number(row.get(f"{prefix}H")),
                "draw": _number(row.get(f"{prefix}D")),
                "away": _number(row.get(f"{prefix}A")),
            }
            if any(prices.values()):
                odds[group] = prices
        ah_line = row.get("AHh")
        ah = {
            "line": float(ah_line) if ah_line not in (None, "") else None,
            "b365_home": _number(row.get("B365AHH")),
            "b365_away": _number(row.get("B365AHA")),
            "avg_home": _number(row.get("AvgAHH")),
            "avg_away": _number(row.get("AvgAHA")),
        }
        if any(ah.get(key) is not None for key in ("line", "b365_home", "avg_home")):
            odds["asian_handicap"] = ah
        matches.append(
            {
                "date": date,
                "home": home,
                "away": away,
                "home_goals": home_goals,
                "away_goals": away_goals,
                "result": str(row.get("FTR") or "").strip().upper() or None,
                "half_time": (
                    f"{row.get('HTHG')} - {row.get('HTAG')}"
                    if str(row.get("HTHG") or "").strip() and str(row.get("HTAG") or "").strip()
                    else None
                ),
                "odds": odds,
            }
        )
    return matches


def sync_season(
    repository: Any,
    csv_text: str,
    division_key: str,
    season_year: int,
    *,
    chinese_name: Any = None,
) -> dict[str, Any]:
    """Ingest one parsed season: fixtures + closing-odds snapshots (idempotent)."""

    if division_key not in DIVISION_MAP:
        raise ValueError(f"Unknown division: {division_key}")
    matches = parse_season_csv(csv_text, season_year)
    localize = chinese_name or (lambda value: value)
    inserted = 0
    odds_saved = 0
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    for row in matches:
        key = hashlib.sha1(
            f"{division_key}|{season_year}|{row['date']}|{row['home']}|{row['away']}".encode()
        ).hexdigest()[:10]
        fixture_id = f"fd-{DIVISION_MAP[division_key]}{season_code(season_year)}-{key}"
        kickoff = row["date"]
        repository.upsert_fixture(
            {
                "id": fixture_id,
                "provider_id": None,
                "source": "football-data",
                "league_key": division_key,
                "fixture_date": kickoff[:10],
                "kickoff": kickoff,
                "status": "finished",
                "home_team": {"name": localize(row["home"]), "original_name": row["home"]},
                "away_team": {"name": localize(row["away"]), "original_name": row["away"]},
                "score": {"home": row["home_goals"], "away": row["away_goals"]},
                "provider_status": row["result"],
                "half_time_score": row["half_time"],
                "season": str(season_year),
                "kickoff_date_only": True,
                "is_demo": False,
            },
            synced_at=now,
        )
        inserted += 1

        quotes: list[dict[str, Any]] = []
        for group, bookmaker in (("b365", "Bet365"), ("avg", "Market Avg"), ("closing", "Pinnacle Closing")):
            prices = row["odds"].get(group)
            if not prices:
                continue
            for selection in ("home", "draw", "away"):
                if prices.get(selection):
                    quotes.append(
                        {
                            "market": "1x2",
                            "selection": selection,
                            "line": None,
                            "price": prices[selection],
                            "bookmaker": bookmaker,
                            "source": "football-data",
                            "captured_at": kickoff,
                        }
                    )
        ah = row["odds"].get("asian_handicap")
        if ah and ah.get("line") is not None:
            for selection, price_key in (("home", "b365_home"), ("away", "b365_away")):
                if ah.get(price_key):
                    quotes.append(
                        {
                            "market": "asian_handicap",
                            "selection": selection,
                            "line": str(ah["line"]),
                            "price": ah[price_key],
                            "bookmaker": "Bet365",
                            "source": "football-data",
                            "captured_at": kickoff,
                        }
                    )
        if quotes:
            saver = getattr(repository, "save_odds_snapshot", None)
            if callable(saver):
                # 每个庄家组独立快照：主键按 (快照, 市场, 选择, 盘口) 唯一，
                # 同一比赛多家庄家的同选择不能共占一个主键。
                for group in ("b365", "avg", "closing"):
                    group_quotes = [quote for quote in quotes if quote["bookmaker"].startswith({"b365": "Bet365", "avg": "Market", "closing": "Pinnacle"}[group])]
                    if not group_quotes:
                        continue
                    saver(
                        {
                            "snapshot_id": f"odds:football-data:{fixture_id}:{group}",
                            "fixture_id": fixture_id,
                            "captured_at": kickoff,
                            "source": "football-data",
                            "quotes": group_quotes,
                            "payload_note": "closing odds at kickoff (football-data.co.uk archive)",
                        }
                    )
                    odds_saved += 1
    return {
        "status": "completed",
        "division": division_key,
        "season": season_year,
        "matches": inserted,
        "odds_snapshots": odds_saved,
    }
