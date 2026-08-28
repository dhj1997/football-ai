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


def test_duplicate_fixture_ids_are_collapsed_before_insert(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "cache.db"))
    repository.initialize()
    repository.replace_fixtures(
        "2026-08-24",
        "2026-08-24",
        [
            fixture("api-1", "2026-08-24"),
            {**fixture("api-1", "2026-08-24"), "league_key": "laliga"},
        ],
        "2026-08-24T10:00:00+00:00",
    )

    rows = repository.list_fixtures()
    assert len(rows) == 1
    assert rows[0]["league_key"] == "laliga"
    assert repository.fixture_sync()["item_count"] == 1


def test_fixture_replacement_preserves_saved_evidence(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "preserve-evidence.db"))
    repository.initialize()
    original = {**fixture("api-1", "2026-08-24"), "status": "scheduled", "score": None}
    context = {
        "source": "test",
        "synced_at": "2026-08-24T10:00:00+00:00",
        "recent_form": {"home": [{"result": "W"}], "away": [{"result": "L"}]},
        "lineup": {"confirmed": True},
    }
    repository.replace_fixtures(
        "2026-08-24",
        "2026-08-24",
        [original],
        "2026-08-24T09:00:00+00:00",
    )
    repository.save_fixture_evidence("api-1", context)

    repository.replace_fixtures(
        "2026-08-24",
        "2026-08-24",
        [{**original, "status": "finished", "score": {"home": 2, "away": 1}}],
        "2026-08-24T11:00:00+00:00",
    )

    refreshed = repository.fixture("api-1")
    assert refreshed["status"] == "finished"
    assert refreshed["score"] == {"home": 2, "away": 1}
    assert refreshed["evidence"] == context
    assert refreshed["evidence_synced_at"] == context["synced_at"]
    assert refreshed["lineup_confirmed"] is True


def test_missing_fixture_evidence_is_restored_from_latest_snapshot(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "restore-evidence.db"))
    repository.initialize()
    repository.replace_fixtures(
        "2026-08-24",
        "2026-08-24",
        [fixture("api-1", "2026-08-24")],
        "2026-08-24T09:00:00+00:00",
    )
    for index, synced_at in enumerate(
        ("2026-08-24T08:00:00+00:00", "2026-08-24T10:00:00+00:00"),
        start=1,
    ):
        context = {
            "source": f"test-{index}",
            "synced_at": synced_at,
            "recent_form": {"home": [{"version": index}], "away": []},
            "lineup": {"confirmed": index == 2},
        }
        repository.save_evidence_snapshot(
            {
                "id": f"snapshot-{index}",
                "fixture_id": "api-1",
                "created_at": synced_at,
                "source_synced_at": synced_at,
                "content_hash": str(index) * 64,
                "payload": {"fixture": {"id": "api-1"}, "context": context},
            }
        )

    restored = repository.restore_fixture_evidence_from_latest_snapshot("api-1")
    restored_again = repository.restore_fixture_evidence_from_latest_snapshot("api-1")

    assert restored["evidence"]["source"] == "test-2"
    assert restored["evidence_synced_at"] == "2026-08-24T10:00:00+00:00"
    assert restored["lineup_confirmed"] is True
    assert restored_again == restored


def test_mysql_url_uses_pymysql_dialect_without_connecting() -> None:
    repository = PredictionRepository("mysql://football_ai:password@127.0.0.1:3306/football_ai")

    assert repository.database_url.startswith("mysql+pymysql://")
    assert repository.engine.dialect.name == "mysql"


def test_league_snapshots_are_replaced_per_league(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "standings.db"))
    repository.initialize()
    first = {
        "league_key": "epl",
        "season": {"year": 2026},
        "updated_at": "2026-08-26T00:00:00+00:00",
        "standings": [{"rank": 1}],
    }
    latest = {
        **first,
        "updated_at": "2026-08-26T06:00:00+00:00",
        "standings": [{"rank": 2}],
    }

    repository.save_league_snapshots([first])
    repository.save_league_snapshots([latest])

    assert repository.league_snapshots("epl") == [latest]


def test_team_snapshot_is_replaced_per_team(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "teams.db"))
    repository.initialize()
    first = {
        "league_key": "epl",
        "team_id": "359",
        "season": {"year": 2026},
        "updated_at": "2026-08-26T00:00:00+00:00",
        "roster": [{"id": "1"}],
    }
    latest = {**first, "updated_at": "2026-08-26T06:00:00+00:00", "roster": [{"id": "2"}]}

    repository.save_team_snapshot(first)
    repository.save_team_snapshot(latest)

    assert repository.team_snapshot("epl", "359") == latest


def test_player_value_snapshot_is_upserted_with_provenance(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "player-values.db"))
    repository.initialize()
    first = {
        "canonical_player_id": "player-1",
        "market_value_eur": 10_000_000.0,
        "market_value_source": "licensed-test",
        "market_value_as_of": "2026-08-20T00:00:00+00:00",
        "cached_at": "2026-08-20T01:00:00+00:00",
    }
    latest = {**first, "market_value_eur": 12_000_000.0, "cached_at": "2026-08-27T01:00:00+00:00"}

    repository.save_player_values([first])
    repository.save_player_values([latest])

    assert repository.player_values(["player-1"]) == [latest]
    assert repository.player_values([]) == []


def test_player_name_snapshot_is_upserted_with_provenance(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "player-names.db"))
    repository.initialize()
    first = {
        "canonical_player_id": "player-1",
        "provider_player_id": "provider-1",
        "source_name_hash": "a" * 64,
        "chinese_name": "测试甲",
        "name_source": "deepseek_transliteration",
        "name_status": "machine_translated",
        "model": "deepseek-test",
        "created_at": "2026-08-27T01:00:00+00:00",
    }
    latest = {**first, "chinese_name": "测试乙", "created_at": "2026-08-27T02:00:00+00:00"}

    repository.save_player_names([first])
    repository.save_player_names([latest])

    assert repository.player_names(["player-1"]) == [latest]
    assert repository.player_names([]) == []


def test_evidence_snapshot_is_persisted_immutably(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "evidence.db"))
    repository.initialize()
    snapshot = {
        "id": "snapshot-1",
        "fixture_id": "fixture-1",
        "created_at": "2026-08-26T00:00:00+00:00",
        "source_synced_at": "2026-08-25T23:00:00+00:00",
        "content_hash": "a" * 64,
        "payload": {"context": {"source": "test"}},
    }

    repository.save_evidence_snapshot(snapshot)

    assert repository.evidence_snapshot("snapshot-1") == snapshot


def test_repository_initializes_one_simulated_bankroll_credit(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "initial.db"))
    repository.initialize()
    repository.initialize()

    assert repository.current_balance() == 1000.0
    transactions = repository.bankroll_transactions()
    assert len(transactions) == 1
    assert transactions[0]["kind"] == "initial_credit"
