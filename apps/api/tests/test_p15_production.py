"""P15 production readiness: environment, migrations, backup, smoke tests."""

import pytest

from app.database import PredictionRepository
from app.production import (
    MIGRATIONS,
    EnvironmentContract,
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
            "database_url": "",
            "cors_origins": "",
        }
    )

    assert any("admin key" in item for item in violations)
    assert any("demo data" in item for item in violations)
    assert any("DATABASE_URL" in item for item in violations)

    production_ok = contract.validate(
        {"admin_api_key": "real-secret", "use_demo_data": False, "database_url": "mysql://...", "cors_origins": "https://x"}
    )
    assert production_ok == []

    # Non-production environments stay permissive.
    assert EnvironmentContract("local").validate({"admin_api_key": "dev-admin-key", "use_demo_data": True}) == []


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
        environment = "local"
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
