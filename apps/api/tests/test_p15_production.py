"""P15 production readiness: environment, migrations, backup, smoke tests."""

import pytest

from app.database import PredictionRepository
from app.production import (
    MIGRATIONS,
    EnvironmentContract,
    mysql_backup_verification_status,
    require_mysql_runtime,
    run_migrations,
    run_smoke_checks,
    sqlite_backup_and_verify,
)


def test_environment_contract_validates_four_environments() -> None:
    assert EnvironmentContract("local").is_production is False
    assert EnvironmentContract("test").is_production is False
    assert EnvironmentContract("staging").is_production is False
    assert EnvironmentContract("production").is_production is True
    with pytest.raises(ValueError):
        EnvironmentContract("bogus")


def test_production_rejects_defaults_and_demo_data() -> None:
    contract = EnvironmentContract("production")
    violations = contract.validate(
        {
            "admin_api_key": "dev-admin-key",
            "use_demo_data": True,
            "web_demo_mode": True,
            "database_url": "",
            "cors_origins": "",
        }
    )

    assert any("admin key" in item for item in violations)
    assert any("demo data" in item for item in violations)
    assert any("WEB_DEMO_MODE" in item for item in violations)
    assert any("DATABASE_URL" in item for item in violations)

    production_ok = contract.validate(
        {"admin_api_key": "real-secret", "use_demo_data": False, "web_demo_mode": False, "database_url": "mysql://...", "cors_origins": "https://x"}
    )
    assert production_ok == []

    assert any(
        "MySQL DATABASE_URL" in item
        for item in EnvironmentContract("local").validate(
            {"database_url": "sqlite:///local.db"}
        )
    )
    assert EnvironmentContract("test").validate(
        {"database_url": "sqlite:///test.db"}
    ) == []


def test_non_test_runtime_requires_mysql() -> None:
    class RuntimeSettings:
        environment = "staging"
        database_url = "sqlite:///staging.db"

    with pytest.raises(RuntimeError, match="SQLite is test-only"):
        require_mysql_runtime(RuntimeSettings())

    RuntimeSettings.database_url = "mysql+pymysql://user:secret@db/football_ai"
    require_mysql_runtime(RuntimeSettings())


def test_migrations_dry_run_validates_without_committing(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "p15.db"))
    repository.initialize()

    result = run_migrations(repository, dry_run=True)

    assert result["status"] == "validated"
    assert result["dry_run"] is True
    assert [item["id"] for item in result["applied"]] == [item["id"] for item in MIGRATIONS]
    # Dry-run must not record versions.
    from sqlalchemy import text

    with repository.engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar()
    assert count == 0


def test_migrations_apply_is_idempotent_and_recorded(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "p15.db"))
    repository.initialize()
    from sqlalchemy import text

    first = run_migrations(repository, dry_run=False)
    second = run_migrations(repository, dry_run=False)

    assert first["status"] == "migrated"
    assert len(first["applied"]) == len(MIGRATIONS)
    assert second["applied"] == []
    assert sorted(second["skipped"]) == sorted(item["id"] for item in MIGRATIONS)
    with repository.engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar()
    assert count == len(MIGRATIONS)


def test_migrations_upgrade_pre_round2_database(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "pre-round2.db"))
    from sqlalchemy import inspect, text

    with repository.engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE schema_migrations ("
                "migration_id VARCHAR(64) PRIMARY KEY, "
                "description VARCHAR(255) NOT NULL, "
                "applied_at VARCHAR(64) NOT NULL)"
            )
        )
        for migration in MIGRATIONS:
            if migration["id"] == "0005-round2-data-integrity":
                break
            for statement in migration["statements"]:
                connection.execute(text(statement))
            connection.execute(
                text(
                    "INSERT INTO schema_migrations (migration_id, description, applied_at) "
                    "VALUES (:migration_id, :description, :applied_at)"
                ),
                {
                    "migration_id": migration["id"],
                    "description": migration["description"],
                    "applied_at": "2026-09-14T00:00:00+00:00",
                },
            )

    result = run_migrations(repository, dry_run=False)

    assert [item["id"] for item in result["applied"]] == [
        "0005-round2-data-integrity",
        "0006-round3-feature-engine",
        "0007-round6-5-production-evidence",
    ]
    assert {
        "feature_snapshots",
        "feature_values",
        "prediction_revisions",
        "leakage_audits",
    }.issubset(inspect(repository.engine).get_table_names())
    market_columns = {
        column["name"]: column
        for column in inspect(repository.engine).get_columns("market_snapshots")
    }
    assert market_columns["persisted_at"]["nullable"] is True


def test_round3_migration_upgrades_pre_round3_database(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "pre-round3.db"))
    from sqlalchemy import inspect, text

    with repository.engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE schema_migrations ("
                "migration_id VARCHAR(64) PRIMARY KEY, "
                "description VARCHAR(255) NOT NULL, "
                "applied_at VARCHAR(64) NOT NULL)"
            )
        )
        for migration in MIGRATIONS:
            if migration["id"] == "0006-round3-feature-engine":
                break
            for statement in migration["statements"]:
                connection.execute(text(statement))
            connection.execute(
                text(
                    "INSERT INTO schema_migrations (migration_id, description, applied_at) "
                    "VALUES (:migration_id, :description, :applied_at)"
                ),
                {
                    "migration_id": migration["id"],
                    "description": migration["description"],
                    "applied_at": "2026-09-15T00:00:00+00:00",
                },
            )

    result = run_migrations(repository, dry_run=False)

    assert [item["id"] for item in result["applied"]] == [
        "0006-round3-feature-engine",
        "0007-round6-5-production-evidence",
    ]
    schema = inspect(repository.engine)
    assert {"feature_registry", "player_impact_rules"}.issubset(schema.get_table_names())
    feature_columns = {column["name"] for column in schema.get_columns("feature_values")}
    assert {
        "registry_id",
        "entity_type",
        "entity_id",
        "value_type",
        "calculation_version",
        "source_record_ids",
        "quality_score",
        "missing_reason",
    }.issubset(feature_columns)
    market_columns = {
        column["name"]: column
        for column in schema.get_columns("market_snapshots")
    }
    assert market_columns["persisted_at"]["nullable"] is True


def test_sqlite_backup_is_verified_by_restoring(tmp_path) -> None:
    database_path = tmp_path / "prod.db"
    repository = PredictionRepository(str(database_path))
    repository.initialize()
    repository.save_competition_registry(
        [
            {"key": "csl", "competition_type": "league", "capabilities": {}, "updated_at": "2026-09-13T00:00:00+00:00", "payload": None},
            {"key": "epl", "competition_type": "league", "capabilities": {}, "updated_at": "2026-09-13T00:00:00+00:00", "payload": None},
        ]
    )

    result = sqlite_backup_and_verify(str(database_path), backup_dir=str(tmp_path / "backups"))

    assert result["status"] == "verified"
    assert result["restored"] is True
    assert result["source_fingerprint"] == result["restore_fingerprint"]
    assert result["source_fingerprint"]["competition_registry"] == 2
    assert result["duration_ms"] >= 0

    missing = sqlite_backup_and_verify(str(tmp_path / "nope.db"), backup_dir=str(tmp_path / "backups"))
    assert missing["status"] == "unavailable"


def test_mysql_backup_verification_status_reads_only_verified_marker(tmp_path) -> None:
    marker = tmp_path / "last-verified.json"
    assert mysql_backup_verification_status(str(marker))["status"] == "unavailable"

    marker.write_text('{"status":"failed"}', encoding="utf-8")
    assert mysql_backup_verification_status(str(marker))["status"] == "invalid"

    marker.write_text(
        '{"status":"verified","database":"football_ai","verified_at":"2026-09-20T00:00:00Z"}',
        encoding="utf-8",
    )
    result = mysql_backup_verification_status(str(marker))
    assert result["status"] == "verified"
    assert result["database"] == "football_ai"


def test_smoke_checks_report_failures_without_crashing(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "p15.db"))
    repository.initialize()
    repository.save_competition_registry(
        [
            {"key": key, "competition_type": "league", "capabilities": {}, "updated_at": "2026-09-13T00:00:00+00:00", "payload": None}
            for key in ("csl", "epl", "laliga", "cfa_cup", "ucl", "acl")
        ]
    )

    class Settings:
        environment = "test"
        admin_api_key = "dev-admin-key"
        use_demo_data = False
        database_url = "sqlite://"
        cors_origins = "http://localhost:3000"

    result = run_smoke_checks(repository, Settings())
    assert result["status"] == "pass"
    assert {item["check"] for item in result["checks"]} >= {"database_query", "competition_registry_loaded", "environment_contract"}

    class BadProductionSettings(Settings):
        environment = "production"
        admin_api_key = "dev-admin-key"
        use_demo_data = True

    production = run_smoke_checks(repository, BadProductionSettings())
    assert production["status"] == "fail"
    environment_check = next(item for item in production["checks"] if item["check"] == "environment_contract")
    assert environment_check["status"] == "fail"
