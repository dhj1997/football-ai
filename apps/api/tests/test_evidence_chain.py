import pytest

from app.evidence_chain import EvidenceProviderChain, evidence_needs_enrichment, localize_evidence_players, merge_evidence


@pytest.mark.asyncio
async def test_provider_chain_switches_to_espn_after_api_football_quota_error() -> None:
    class Primary:
        configured = True

        async def fetch(self, _fixture):
            raise RuntimeError("API-Football request limit reached")

    class ESPN:
        configured = True

        async def fetch(self, _fixture):
            return {"source": "espn-evidence", "synced_at": "2026-08-26T00:00:00+00:00"}

    class Partial:
        public_configured = True

        async def fetch_public(self, _fixture):
            raise AssertionError("TheSportsDB should not run after ESPN succeeds")

    result = await EvidenceProviderChain(Primary(), ESPN(), Partial()).fetch({})

    assert result["source"] == "espn-evidence"
    assert result["fallback_from"] == "api-football"
    assert result["provider_failures"] == [
        {"provider": "api-football", "error": "API-Football request limit reached"}
    ]


@pytest.mark.asyncio
async def test_provider_chain_falls_through_to_partial_when_espn_fails() -> None:
    class Primary:
        configured = True

        async def fetch(self, _fixture):
            raise RuntimeError("quota")

    class ESPN:
        configured = True

        async def fetch(self, _fixture):
            raise RuntimeError("ESPN unavailable")

    class Partial:
        public_configured = True

        async def fetch_public(self, _fixture):
            return {"source": "thesportsdb-partial", "synced_at": "2026-08-26T00:00:00+00:00"}

    result = await EvidenceProviderChain(Primary(), ESPN(), Partial()).fetch({})

    assert result["source"] == "thesportsdb-partial"
    assert [item["provider"] for item in result["provider_failures"]] == ["api-football", "espn"]


def test_incomplete_form_is_enriched_without_discarding_existing_fields() -> None:
    previous = {
        "source": "api-football-single-fixture",
        "recent_form": {"home": [{"result": "D"}], "away": [{"result": "D"}]},
        "availability": {"players": [{"name": "旧伤停"}]},
        "odds": {"home": 1.8},
    }
    incoming = {
        "source": "espn-evidence",
        "synced_at": "2026-08-26T02:00:00+00:00",
        "recent_form": {"home": [{"result": "W"}] * 5, "away": [{"result": "L"}] * 5},
        "availability": {"players": []},
        "odds": {"home": 1.9},
    }

    merged = merge_evidence(previous, incoming)

    assert evidence_needs_enrichment(previous) is True
    assert len(merged["recent_form"]["home"]) == 5
    assert merged["availability"]["players"] == [{"name": "旧伤停"}]
    assert merged["odds"] == {"home": 1.9}
    assert merged["source"] == "api-football-single-fixture+espn-evidence"

    localized = localize_evidence_players(
        {"source": "api-football+espn-evidence+espn-evidence", "squads": {"home": [], "away": []}, "lineup": {}, "availability": {}}
    )
    assert localized["source"] == "api-football+espn-evidence"


def test_performance_rich_squad_replaces_basic_identity_only_squad() -> None:
    previous = {
        "source": "api-football-single-fixture+espn-evidence",
        "squads": {
            "home": [{"id": "1", "name": "测试球员", "original_name": "Test Player"}],
            "away": [],
        },
    }
    incoming = {
        "source": "espn-evidence",
        "squads": {
            "home": [
                {
                    "id": "espn-1",
                    "provider_player_id": "espn-1",
                    "name": "测试球员",
                    "original_name": "Test Player",
                    "statistics": {"appearances": 8, "goals": 3},
                }
            ],
            "away": [],
        },
    }

    merged = merge_evidence(previous, incoming)

    assert merged["squads"]["home"][0]["statistics"]["appearances"] == 8
    assert merged["source"] == "api-football-single-fixture+espn-evidence"
