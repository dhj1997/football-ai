"""Demonstration fixtures used before an external provider key is configured."""

from datetime import UTC, date, datetime, timedelta, timezone


CHINA_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")


LEAGUES = {
    "epl": {"id": 39, "name": "英超", "country": "英格兰", "mark": "PL"},
    "laliga": {"id": 140, "name": "西甲", "country": "西班牙", "mark": "LL"},
    "csl": {"id": 169, "name": "中超", "country": "中国", "mark": "CSL"},
}


def _iso(day: date, hour: int, minute: int = 0) -> str:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=CHINA_TZ).isoformat()


def demo_fixtures(today: date | None = None) -> list[dict]:
    """Build stable sample fixtures around the current date."""

    current = today or datetime.now(CHINA_TZ).date()
    rows = [
        ("demo-epl-today", current, 19, 30, "epl", "曼彻斯特城", "托特纳姆热刺", "MCI", "TOT", False),
        ("demo-laliga-today", current, 21, 0, "laliga", "皇家社会", "塞维利亚", "RSO", "SEV", True),
        ("demo-csl-today", current, 12, 35, "csl", "上海海港", "北京国安", "SHP", "BJG", True),
        ("demo-epl-tomorrow", current + timedelta(days=1), 20, 0, "epl", "阿森纳", "纽卡斯尔联", "ARS", "NEW", False),
        ("demo-laliga-tomorrow", current + timedelta(days=1), 18, 30, "laliga", "比利亚雷亚尔", "皇家贝蒂斯", "VIL", "BET", False),
        ("demo-csl-history", current - timedelta(days=2), 11, 0, "csl", "山东泰山", "成都蓉城", "SDT", "CDR", True),
    ]
    fixtures: list[dict] = []
    for index, row in enumerate(rows):
        fixture_id, day, hour, minute, league_key, home, away, home_code, away_code, lineup = row
        league = LEAGUES[league_key]
        finished = day < current
        fixtures.append(
            {
                "id": fixture_id,
                "provider_id": None,
                "league_key": league_key,
                "league": league,
                "kickoff": _iso(day, hour, minute),
                "status": "finished" if finished else "scheduled",
                "home_team": {"name": home, "code": home_code},
                "away_team": {"name": away, "code": away_code},
                "score": {"home": 2, "away": 1} if finished else None,
                "venue": ["城市体育场", "河岸球场", "中央竞技场"][index % 3],
                "lineup_confirmed": lineup and not finished,
                "is_demo": True,
            }
        )
    return fixtures


def demo_context(fixture_id: str) -> dict:
    """Return sample evidence for one fixture."""

    seed = sum(ord(char) for char in fixture_id)
    home_form = ["W", "W", "D", "L", "W"] if seed % 2 else ["W", "D", "W", "W", "D"]
    away_form = ["D", "L", "W", "D", "W"] if seed % 3 else ["L", "W", "D", "L", "W"]
    now = datetime.now(UTC).replace(microsecond=0)
    fixture = next((item for item in demo_fixtures() if item["id"] == fixture_id), None)
    lineup_confirmed = bool(fixture and fixture["lineup_confirmed"])
    return {
        "recent_form": {
            "home": home_form,
            "away": away_form,
            "home_points_per_game": round(1.3 + (seed % 8) / 10, 2),
            "away_points_per_game": round(1.0 + (seed % 6) / 10, 2),
            "updated_at": now.isoformat(),
        },
        "head_to_head": [
            {"date": "2026-04-18", "home": "主队", "away": "客队", "score": "2-1"},
            {"date": "2025-11-02", "home": "客队", "away": "主队", "score": "1-1"},
            {"date": "2025-05-23", "home": "主队", "away": "客队", "score": "0-1"},
        ],
        "availability": {
            "home_missing": 1 + seed % 2,
            "away_missing": seed % 3,
            "notes": ["主队一名轮换中场缺阵", "客队后防有一名球员出场存疑"],
            "updated_at": now.isoformat(),
        },
        "lineup": {
            "confirmed": lineup_confirmed,
            "home_strength": 0.93 if lineup_confirmed else 0.88,
            "away_strength": 0.89 if lineup_confirmed else 0.86,
            "updated_at": now.isoformat() if lineup_confirmed else None,
        },
        "odds": {
            "bookmaker": "Demo Market",
            "home": round(1.85 + (seed % 4) * 0.08, 2),
            "draw": round(3.35 + (seed % 3) * 0.08, 2),
            "away": round(3.65 + (seed % 5) * 0.12, 2),
            "asian_handicap": -0.75 if seed % 2 else -0.5,
            "updated_at": now.isoformat(),
            "is_demo": True,
        },
    }


def unavailable_context() -> dict:
    """Return an explicit empty evidence document for a real cached fixture."""

    return {
        "recent_form": {
            "home": [],
            "away": [],
            "home_points_per_game": 0.0,
            "away_points_per_game": 0.0,
            "updated_at": None,
        },
        "head_to_head": [],
        "availability": {
            "home_missing": 0,
            "away_missing": 0,
            "notes": [],
            "updated_at": None,
        },
        "lineup": {
            "confirmed": False,
            "home_strength": 0.0,
            "away_strength": 0.0,
            "updated_at": None,
        },
        "odds": None,
    }
