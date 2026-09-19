"""Weather evidence: forecast mapping, sync flow, and evidence attach."""

from datetime import UTC, datetime

import httpx
import pytest

from app.weather_provider import WeatherProvider, _nearest_hour_index
from app.weather_sync import attach_weather, sync_weather


def _forecast_transport(handler) -> WeatherProvider:
    return WeatherProvider(timeout_seconds=5, transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_forecast_picks_hour_nearest_kickoff() -> None:
    calls = {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "hourly": {
                    "time": ["2026-09-20T14:00", "2026-09-20T15:00", "2026-09-20T16:00", "2026-09-20T17:00"],
                    "temperature_2m": [21.0, 19.2, 18.7, 18.1],
                    "wind_speed_10m": [9.0, 12.2, 10.8, 8.3],
                    "precipitation": [0.0, 0.3, 1.1, 0.0],
                    "weather_code": [1, 2, 61, 3],
                }
            },
        )

    provider = _forecast_transport(handler)
    forecast = await provider.forecast(51.51, -0.22, "2026-09-20T16:00:00+00:00")

    assert forecast["temperature_c"] == pytest.approx(18.7)
    assert forecast["wind_kmh"] == pytest.approx(10.8)
    assert forecast["precipitation_mm"] == pytest.approx(1.1)
    assert forecast["weather_code"] == 61
    assert forecast["condition"] == "小雨"
    assert "start_hour=2026-09-20T15%3A00" in calls["url"]


@pytest.mark.asyncio
async def test_geocode_falls_back_to_city_lookup() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "photon" in str(request.url):
            return httpx.Response(200, json={"features": []})
        return httpx.Response(
            200,
            json={"results": [{"latitude": 50.72, "longitude": -1.88}]},
        )

    provider = _forecast_transport(handler)
    coords = await provider.geocode("Bournemouth England")
    assert coords == pytest.approx((50.72, -1.88))


def test_nearest_hour_index_handles_gaps() -> None:
    times = ["2026-09-20T14:00", "2026-09-20T18:00"]
    assert _nearest_hour_index(times, datetime(2026, 9, 20, 15, 30, tzinfo=UTC)) == 0
    assert _nearest_hour_index(times, datetime(2026, 9, 20, 17, 30, tzinfo=UTC)) == 1
    assert _nearest_hour_index([], datetime.now(UTC)) is None


class StubProvider:
    def __init__(self, coords=None, forecast=None) -> None:
        self.coords = coords
        self.forecast_result = forecast
        self.geocode_queries: list[str] = []

    async def geocode(self, query: str):
        self.geocode_queries.append(query)
        return self.coords

    async def forecast(self, lat, lon, kickoff):
        if self.coords is None or self.forecast_result is None:
            return None
        return {**self.forecast_result, "kickoff": kickoff}


class StubRepository:
    def __init__(self, rows, venue_location=None) -> None:
        self.rows = {row["id"]: dict(row) for row in rows}
        self.venue_location_result = venue_location
        self.saved_venues: list[str] = []

    def list_fixtures(self, league_key=None):
        return [dict(row) for row in self.rows.values()]

    def venue_location(self, query):
        return self.venue_location_result

    def save_venue_location(self, query, lat, lon):
        self.saved_venues.append(query)

    def upsert_fixture(self, fixture, synced_at=None):
        self.rows[fixture["id"]] = fixture


def _scheduled(row_id, venue="Craven Cottage", evidence_venue=None, kickoff="2026-09-20T15:00:00+00:00", **extra):
    row = {
        "id": row_id,
        "league_key": "epl",
        "status": "scheduled",
        "kickoff": kickoff,
        "venue": venue,
    }
    if evidence_venue is not None:
        row["evidence"] = {"venue": evidence_venue}
    row.update(extra)
    return row


@pytest.mark.asyncio
async def test_sync_writes_forecast_and_caches_location() -> None:
    repository = StubRepository(
        [_scheduled("a"), _scheduled("b", status="finished"), _scheduled("c", venue="待定")],
        venue_location=(51.51, -0.22),
    )
    provider = StubProvider(coords=(51.51, -0.22), forecast={"temperature_c": 18.7, "condition": "小雨"})

    result = await sync_weather(repository, provider, limit=10)

    assert result["enriched"] == 1
    weather = repository.rows["a"]["weather"]
    assert weather["temperature_c"] == 18.7
    assert weather["source"] == "open-meteo"
    # 已完赛与场地未定的都不写
    assert "weather" not in repository.rows["b"]
    assert "weather" not in repository.rows["c"]


@pytest.mark.asyncio
async def test_sync_skips_fresh_and_unresolvable() -> None:
    repository = StubRepository(
        [
            _scheduled("a", weather={"captured_at": "2026-09-19T18:00:00+00:00"}),
            _scheduled("d", venue="Some Stadium"),
        ]
    )
    provider = StubProvider(coords=None, forecast=None)

    result = await sync_weather(
        repository,
        provider,
        limit=10,
        now=datetime(2026, 9, 19, 20, 0, tzinfo=UTC),
    )

    assert result["skipped_fresh"] == 1
    assert result["unresolved_location"] == 1
    assert result["enriched"] == 0
    assert provider.geocode_queries == ["Some Stadium"]  # 已有证据地址的先查城市，再查场地名


@pytest.mark.asyncio
async def test_location_queries_fall_back_to_learned_home_venue() -> None:
    from app.weather_sync import _location_queries, _team_home_venues

    row = _scheduled(
        "a",
        venue="待定",
        evidence_venue={"name": "Vitality Stadium", "city": "Bournemouth", "country": "England"},
    )
    queries = _location_queries(row, {})
    assert queries == ["Bournemouth England"]

    # venue 未知时回退：主队历史球场 → 主队名
    rows = [
        _scheduled("hist", venue="Old Trafford", kickoff="2026-09-01T00:00:00+00:00"),
        _scheduled("old", venue="Old Ground", kickoff="2026-08-01T00:00:00+00:00"),
    ]
    rows[0]["status"] = "finished"
    rows[1]["status"] = "finished"
    rows[0]["home_team"] = {"name": "曼联", "original_name": "Manchester United"}
    rows[1]["home_team"] = {"name": "曼联", "original_name": "Manchester United"}
    learned = _team_home_venues(rows)
    assert learned == {"曼彻斯特联": "Old Trafford"}

    upcoming = _scheduled("u", venue="待定")
    upcoming["home_team"] = {"name": "曼联", "original_name": "Manchester United"}
    queries = _location_queries(upcoming, learned)
    assert queries == ["Old Trafford", "Manchester United", "曼联"]


def test_attach_weather_exposes_slot() -> None:
    fixture = {
        "weather": {
            "source": "open-meteo",
            "captured_at": "2026-09-19T18:00:00+00:00",
            "available_at": "2026-09-19T18:00:00+00:00",
            "venue": "Craven Cottage",
            "temperature_c": 18.7,
            "wind_kmh": 10.8,
            "precipitation_mm": 1.1,
            "condition": "小雨",
        }
    }
    context: dict = {}
    attach_weather(fixture, context)
    assert context["weather"]["condition"] == "小雨"
    assert context["weather"]["source"] == "open-meteo"

    empty: dict = {}
    attach_weather({}, empty)
    assert "weather" not in empty
