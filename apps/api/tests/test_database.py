"""Fixture cache persistence tests."""

from app.database import PredictionRepository


def fixture(fixture_id: str, fixture_date: str, league_key: str = "epl") -> dict:
    """Build a minimal cached fixture document."""

    return {
        "id": fixture_id,
        "provider_id": int(fixture_id.removeprefix("api-")),
        "league_key": league_key,
        "fixture_date": fixture_date,
        "kickoff": f"{fixture_date}T19:30:00+08:00",
    }


def test_fixture_window_is_replaced_atomically(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "cache.db"))
    repository.initialize()
    repository.replace_fixtures(
        "2026-08-23",
        "2026-08-24",
        [fixture("api-1", "2026-08-23"), fixture("api-2", "2026-08-24", "csl")],
        "2026-08-24T08:00:00+00:00",
    )
    repository.replace_fixtures(
        "2026-08-23",
        "2026-08-24",
        [fixture("api-3", "2026-08-24", "laliga")],
        "2026-08-24T09:00:00+00:00",
    )

    assert [item["id"] for item in repository.list_fixtures()] == ["api-3"]
    assert repository.fixture("api-1") is None
    assert repository.fixture_sync() == {
        "synced_at": "2026-08-24T09:00:00+00:00",
        "item_count": 1,
    }

