"""Open-Meteo / Photon weather forecasts for upcoming fixtures.

Both endpoints are public and keyless. Venue coordinates are resolved via
Photon (stadium-level) with an Open-Meteo city-level fallback; the forecast
picks the hourly entries around kickoff (temperature / wind / precipitation /
WMO code) so the evidence layer receives kickoff-time conditions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

GEOCODE_PHOTON_URL = "https://photon.komoot.io/api/"
GEOCODE_CITY_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
USER_AGENT = "football-ai/0.1 (+weather)"

# WMO 4677 常用码的简短中文标签；未知码不标注。
WMO_LABELS: dict[int, str] = {
    0: "晴",
    1: "基本晴",
    2: "局部多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "大毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    80: "阵雨",
    81: "中阵雨",
    82: "强阵雨",
    95: "雷暴",
    96: "雷暴伴冰雹",
    99: "强雷暴伴冰雹",
}


class WeatherProvider:
    """Keyless public weather access with venue-level geocoding."""

    def __init__(self, timeout_seconds: float = 15, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=True,
            transport=self._transport,
        )

    async def geocode(self, query: str) -> tuple[float, float] | None:
        """Resolve one venue or city query to (lat, lon); None when unknown."""

        text = str(query or "").strip()
        if not text:
            return None
        coords = await self._geocode_photon(text)
        if coords is not None:
            return coords
        return await self._geocode_city(text)

    async def forecast(self, latitude: float, longitude: float, kickoff: str) -> dict[str, Any] | None:
        """Hourly forecast entries within [-1h, +2h] of kickoff."""

        start = _parse_iso(kickoff)
        if start is None:
            return None
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "temperature_2m,wind_speed_10m,precipitation,weather_code",
            "start_hour": (start - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
            "end_hour": (start + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
        }
        async with self._client() as client:
            response = await client.get(FORECAST_URL, params=params, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            payload = response.json()
        hourly = payload.get("hourly") or {}
        times = hourly.get("time") or []
        if not times:
            return None
        index = _nearest_hour_index(times, start)
        if index is None:
            return None
        code = _optional_int((hourly.get("weather_code") or [None])[index])
        return {
            "kickoff": start.isoformat(),
            "temperature_c": _optional_float((hourly.get("temperature_2m") or [None])[index]),
            "wind_kmh": _optional_float((hourly.get("wind_speed_10m") or [None])[index]),
            "precipitation_mm": _optional_float((hourly.get("precipitation") or [None])[index]),
            "weather_code": code,
            "condition": WMO_LABELS.get(code) if code is not None else None,
        }

    async def _geocode_photon(self, query: str) -> tuple[float, float] | None:
        try:
            async with self._client() as client:
                response = await client.get(
                    GEOCODE_PHOTON_URL,
                    params={"q": query, "limit": 1},
                    headers={"User-Agent": USER_AGENT},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        features = payload.get("features") or []
        for feature in features:
            geometry = feature.get("geometry") or {}
            coordinates = geometry.get("coordinates") or []
            if len(coordinates) >= 2:
                lon, lat = _optional_float(coordinates[0]), _optional_float(coordinates[1])
                if lat is not None and lon is not None:
                    return lat, lon
        return None

    async def _geocode_city(self, query: str) -> tuple[float, float] | None:
        try:
            async with self._client() as client:
                response = await client.get(
                    GEOCODE_CITY_URL,
                    params={"name": query, "count": 1},
                    headers={"User-Agent": USER_AGENT},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        results = payload.get("results") or []
        for result in results:
            lat, lon = _optional_float(result.get("latitude")), _optional_float(result.get("longitude"))
            if lat is not None and lon is not None:
                return lat, lon
        return None


def _nearest_hour_index(times: list[str], kickoff: datetime) -> int | None:
    best: tuple[float, int] | None = None
    for index, value in enumerate(times):
        parsed = _parse_iso(value)
        if parsed is None:
            continue
        delta = abs((parsed - kickoff).total_seconds())
        if best is None or delta < best[0]:
            best = (delta, index)
    return best[1] if best is not None else None


def _parse_iso(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
