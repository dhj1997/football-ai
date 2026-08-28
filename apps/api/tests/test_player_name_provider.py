import json

import httpx
import pytest

from app.database import PredictionRepository
from app.player_identity import public_payload
from app.player_name_provider import ChatGptPlayerNameProvider, FallbackPlayerNameProvider, PlayerNameService


class FakeNameProvider:
    source_name = "test_transliteration"
    model = "test-name-model"

    def __init__(self, names: dict[str, str] | None = None, configured: bool = True, error: str | None = None) -> None:
        self.names = names or {}
        self.configured = configured
        self.error = error
        self.calls: list[list[dict[str, str]]] = []

    async def translate(self, players: list[dict[str, str]]) -> dict:
        self.calls.append(players)
        if self.error:
            raise RuntimeError(self.error)
        return {
            "translations": [
                {
                    "canonical_player_id": item["canonical_player_id"],
                    "chinese_name": self.names[item["source_name"]],
                }
                for item in players
            ],
            "model": self.model,
        }


def context() -> dict:
    return {
        "source": "api-football-single-fixture",
        "squads": {
            "home": [
                {"id": 10, "name": "Unknown Alpha", "original_name": "Unknown Alpha", "number": 9},
                {"id": 11, "name": "Unknown Beta", "original_name": "Unknown Beta", "number": 18},
                {"id": 42, "name": "Hugo Duro", "original_name": "Hugo Duro", "number": 10},
            ],
            "away": [],
        },
        "lineup": {"home_players": [], "away_players": []},
        "availability": {
            "players": [
                {
                    "team": "home",
                    "provider_player_id": "10",
                    "name": "Unknown Alpha",
                    "original_name": "Unknown Alpha",
                    "reason": "伤病",
                }
            ]
        },
    }


@pytest.mark.asyncio
async def test_machine_names_are_cached_reused_and_linked_to_availability(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "names.db"))
    repository.initialize()
    provider = FakeNameProvider({"Unknown Alpha": "阿尔法", "Unknown Beta": "贝塔"})
    first_context = context()

    await PlayerNameService(provider, repository).enrich(first_context, resolve_missing=True)

    assert len(provider.calls) == 1
    assert [item["name"] for item in first_context["squads"]["home"]] == ["阿尔法", "贝塔", "乌戈·杜罗"]
    assert first_context["availability"]["players"][0]["name"] == "阿尔法"
    assert first_context["squads"]["home"][0]["name_status"] == "machine_translated"
    assert first_context["squads"]["home"][2]["name_status"] == "resolved"
    assert first_context["player_name"]["generated_count"] == 2

    cached_context = context()
    offline_provider = FakeNameProvider(configured=False)
    await PlayerNameService(offline_provider, repository).enrich(cached_context, resolve_missing=True)

    assert offline_provider.calls == []
    assert [item["name"] for item in cached_context["squads"]["home"]] == ["阿尔法", "贝塔", "乌戈·杜罗"]
    assert cached_context["player_name"]["machine_translated_count"] == 2
    public = public_payload(cached_context)
    assert "Unknown Alpha" not in str(public)
    assert "Unknown Beta" not in str(public)


@pytest.mark.asyncio
async def test_translation_failure_keeps_unique_safe_fallbacks(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "failed-names.db"))
    repository.initialize()
    provider = FakeNameProvider(error="temporary provider failure")
    value = context()

    await PlayerNameService(provider, repository).enrich(value, resolve_missing=True)

    public = public_payload(value)
    names = [item["name"] for item in public["squads"]["home"][:2]]
    assert len(set(names)) == 2
    assert all(name.startswith("待核验球员 #") for name in names)
    assert all(item["name_status"] == "unresolved" for item in public["squads"]["home"][:2])
    assert public["player_name"]["error"] == "temporary provider failure"
    assert "Unknown Alpha" not in str(public)
    assert "Unknown Beta" not in str(public)


@pytest.mark.asyncio
async def test_fallback_provider_uses_second_model_after_primary_failure() -> None:
    primary = FakeNameProvider(error="empty content")
    secondary = FakeNameProvider({"Unknown Alpha": "阿尔法"})
    secondary.source_name = "secondary_transliteration"
    provider = FallbackPlayerNameProvider([primary, secondary])

    result = await provider.translate([{"canonical_player_id": "player-1", "source_name": "Unknown Alpha"}])

    assert len(primary.calls) == 1
    assert len(secondary.calls) == 1
    assert result["translations"][0]["chinese_name"] == "阿尔法"


@pytest.mark.asyncio
async def test_chatgpt_name_provider_uses_strict_responses_schema() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        content = json.dumps(
            {"translations": [{"canonical_player_id": "player-1", "chinese_name": "阿尔法"}]},
            ensure_ascii=False,
        )
        return httpx.Response(200, json={"model": "gpt-test", "output_text": content})

    provider = ChatGptPlayerNameProvider(
        "key",
        "gpt-test",
        "https://gpt.test",
        transport=httpx.MockTransport(handler),
    )
    result = await provider.translate([{"canonical_player_id": "player-1", "source_name": "Unknown Alpha"}])

    assert captured["text"]["format"]["strict"] is True
    assert result["source"] == "chatgpt_transliteration"
    assert result["translations"][0]["chinese_name"] == "阿尔法"
