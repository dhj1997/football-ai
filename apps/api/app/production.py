"""P15 Production readiness: environment contract, migrations, backup, smoke.

Environment configuration is validated (never silently defaulted in
production), database migrations are versioned with a dry-run mode, and
SQLite backups must prove restorability before a backup counts as
successful. Production history stays immutable: no function here edits
historical predictions, odds or evaluation runs.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from sqlalchemy import text

ENVIRONMENTS: tuple[str, ...] = ("local", "test", "staging", "production")
MIGRATION_VERSION = "p15-migrations-v1"


class EnvironmentContract:
    """Validate that runtime settings match the declared environment."""

    def __init__(self, environment: str) -> None:
        if environment not in ENVIRONMENTS:
            raise ValueError(f"Unknown environment: {environment}")
        self.environment = environment

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def validate(self, settings: Mapping[str, Any]) -> list[str]:
        """Return configuration violations; empty means deployable."""

        violations: list[str] = []
        if self.is_production:
            admin_key = str(settings.get("admin_api_key") or "")
            if not admin_key or admin_key == "dev-admin-key":
                violations.append("production must override the default admin key")
            if bool(settings.get("use_demo_data")):
                violations.append("production must not serve demo data")
            if not str(settings.get("database_url") or "").strip():
                violations.append("production requires an explicit DATABASE_URL")
            if not str(settings.get("cors_origins") or "").strip():
                violations.append("production requires an explicit CORS origin list")
        return violations


def _settings_view(settings: Any) -> dict[str, Any]:
    if isinstance(settings, Mapping):
        return dict(settings)
    return {
        "admin_api_key": getattr(settings, "admin_api_key", None),
        "use_demo_data": getattr(settings, "use_demo_data", None),
        "database_url": getattr(settings, "database_url", None),
        "cors_origins": getattr(settings, "cors_origins", None),
    }


# Additive migrations only. Each entry states its id, a human description
# and the DDL statements; destructive changes need their own phase and
# migration note (P15 spec).
MIGRATIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "0001-p9-competition-registry",
        "description": "Add competition_registry and fixture_conflicts tables",
        "statements": (
            "CREATE TABLE IF NOT EXISTS competition_registry (competition_key VARCHAR(32) PRIMARY KEY, competition_type VARCHAR(16) NOT NULL, capabilities TEXT NOT NULL, updated_at VARCHAR(64) NOT NULL, payload TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS fixture_conflicts (conflict_id VARCHAR(255) PRIMARY KEY, canonical_fixture_id VARCHAR(255) NOT NULL, competition_key VARCHAR(32) NOT NULL, conflict_type VARCHAR(32) NOT NULL, source_a VARCHAR(255) NOT NULL, source_b VARCHAR(255) NOT NULL, value_a TEXT NULL, value_b TEXT NULL, resolution VARCHAR(64) NOT NULL, resolved BOOLEAN NOT NULL, detected_at VARCHAR(64) NOT NULL, payload TEXT NOT NULL)",
        ),
    },
    {
        "id": "0002-p10-model-registry",
        "description": "Add model_registry table",
        "statements": (
            "CREATE TABLE IF NOT EXISTS model_registry (model_key VARCHAR(64) NOT NULL, model_version VARCHAR(128) NOT NULL, status VARCHAR(32) NOT NULL, competition_scope VARCHAR(64) NULL, feature_version VARCHAR(128) NULL, dataset_fingerprint VARCHAR(255) NULL, training_cutoff VARCHAR(64) NULL, calibration_version VARCHAR(128) NULL, artifact_hash VARCHAR(64) NOT NULL, created_at VARCHAR(64) NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (model_key, model_version))",
        ),
    },
    {
        "id": "0003-p11-market-snapshots",
        "description": "Add market_snapshots table",
        "statements": (
            "CREATE TABLE IF NOT EXISTS market_snapshots (market_snapshot_id VARCHAR(255) PRIMARY KEY, fixture_id VARCHAR(255) NOT NULL, market VARCHAR(64) NOT NULL, captured_at VARCHAR(64) NOT NULL, overround DECIMAL(10, 6) NULL, payload TEXT NOT NULL)",
        ),
    },
    {
        "id": "0004-p14-research-runs",
        "description": "Add research_runs table",
        "statements": (
            "CREATE TABLE IF NOT EXISTS research_runs (run_id VARCHAR(255) PRIMARY KEY, status VARCHAR(32) NOT NULL, job_id VARCHAR(255) NULL, created_at VARCHAR(64) NOT NULL, payload TEXT NOT NULL)",
        ),
    },
)


def _ensure_migrations_table(connection: Any) -> None:
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "migration_id VARCHAR(64) PRIMARY KEY, "
            "description VARCHAR(255) NOT NULL, "
            "applied_at VARCHAR(64) NOT NULL)"
        )
    )


def _applied_migrations(connection: Any) -> set[str]:
    _ensure_migrations_table(connection)
    rows = connection.execute(text("SELECT migration_id FROM schema_migrations")).fetchall()
    return {row[0] for row in rows}


def run_migrations(repository: Any, *, dry_run: bool = True) -> dict[str, Any]:
    """Apply (or dry-run) the versioned additive migrations.

    A dry-run validates the statements against the real database inside a
    transaction that is always rolled back — the standard production
    pre-flight. Applied migrations are recorded in schema_migrations and
    are never re-executed.
    """

    engine = getattr(repository, "engine", None)
    if engine is None:
        raise RuntimeError("repository does not expose a database engine")
    if dry_run and not getattr(repository, "is_sqlite", False):
        # MySQL DDL auto-commits, so a "dry run" would actually create
        # tables. Validation there must target a staging database copy.
        return {
            "migration_version": MIGRATION_VERSION,
            "dry_run": True,
            "status": "not_supported",
            "reason": "transactional DDL dry-run requires SQLite; run against a staging copy for other engines",
            "applied": [],
            "skipped": [],
        }
    applied: list[dict[str, Any]] = []
    skipped: list[str] = []
    with engine.begin() as connection:
        already = _applied_migrations(connection)
        for migration in MIGRATIONS:
            if migration["id"] in already:
                skipped.append(migration["id"])
                continue
            for statement in migration["statements"]:
                if dry_run:
                    # SQLite/MySQL both roll back DDL inside a clean
                    # transaction; connection.begin() nested savepoint keeps
                    # the outer transaction untouched for validation.
                    connection.execute(text("SAVEPOINT migration_dry_run"))
                    try:
                        connection.execute(text(statement))
                    finally:
                        connection.execute(text("ROLLBACK TO SAVEPOINT migration_dry_run"))
                else:
                    connection.execute(text(statement))
            applied.append({"id": migration["id"], "description": migration["description"]})
        if not dry_run:
            now = datetime.now(UTC).replace(microsecond=0).isoformat()
            for item in applied:
                connection.execute(
                    text("INSERT INTO schema_migrations (migration_id, description, applied_at) VALUES (:id, :description, :applied_at)"),
                    {"id": item["id"], "description": item["description"], "applied_at": now},
                )
    return {
        "migration_version": MIGRATION_VERSION,
        "dry_run": dry_run,
        "applied": applied,
        "skipped": skipped,
        "status": "validated" if dry_run else "migrated",
    }


def _table_fingerprint(connection: Any, tables: Iterable[str]) -> dict[str, Any]:
    fingerprint: dict[str, Any] = {}
    for table in tables:
        try:
            count = connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()  # noqa: S608
        except Exception:
            count = None
        fingerprint[table] = int(count) if count is not None else None
    return fingerprint


def sqlite_backup_and_verify(
    database_path: str,
    *,
    backup_dir: str | None = None,
) -> dict[str, Any]:
    """Back up a SQLite database and prove the backup restores.

    Success requires opening the restored copy and matching a row-count
    fingerprint of the core tables — "the backup file exists" is never
    treated as success.
    """

    source = Path(database_path)
    if not source.exists():
        return {"status": "unavailable", "reason": f"database file not found: {database_path}"}
    with sqlite3.connect(str(source)) as source_connection:
        tables = [
            row[0]
            for row in source_connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        source_fingerprint = _sqlite_fingerprint(source_connection, tables)
    target_dir = Path(backup_dir) if backup_dir else Path(tempfile.mkdtemp(prefix="football-ai-backup-"))
    target_dir.mkdir(parents=True, exist_ok=True)
    backup_path = target_dir / f"backup-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.db"
    source_sqlite = sqlite3.connect(str(source))
    try:
        destination = sqlite3.connect(str(backup_path))
        try:
            with destination:
                source_sqlite.backup(destination)
        finally:
            destination.close()
    finally:
        source_sqlite.close()

    started = datetime.now(UTC)
    restore_path = target_dir / f"restore-check-{backup_path.stem}.db"
    shutil.copyfile(backup_path, restore_path)
    with sqlite3.connect(str(restore_path)) as restored:
        restore_fingerprint = _sqlite_fingerprint(restored, tables)
    duration_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
    matches = restore_fingerprint == source_fingerprint
    try:
        restore_path.unlink()
    except OSError:
        pass
    return {
        "status": "verified" if matches else "failed",
        "backup_path": str(backup_path),
        "restored": matches,
        "duration_ms": duration_ms,
        "tables": {table: count for table, count in source_fingerprint.items() if count is not None},
        "source_fingerprint": source_fingerprint,
        "restore_fingerprint": restore_fingerprint,
        "verified_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }


def _sqlite_fingerprint(connection: Any, tables: Iterable[str]) -> dict[str, Any]:
    fingerprint: dict[str, Any] = {}
    for table in tables:
        try:
            fingerprint[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608
        except Exception:
            fingerprint[table] = None
    return fingerprint


def run_smoke_checks(repository: Any, settings: Any) -> dict[str, Any]:
    """Automated production smoke test over live dependencies (no HTTP self-calls)."""

    checks: list[dict[str, Any]] = []

    def check(name: str, fn: Callable[[], bool], detail: Any = None) -> None:
        try:
            passed = bool(fn())
        except Exception as error:  # smoke checks must never crash the caller
            passed = False
            detail = str(error)[:200]
        checks.append({"check": name, "status": "pass" if passed else "fail", "detail": detail})

    def database_query() -> bool:
        with repository.engine.connect() as connection:
            return connection.execute(text("SELECT 1")).scalar() == 1

    check("database_connectivity", lambda: repository.engine.connect() is not None)
    check("database_query", database_query)
    check("competition_registry_loaded", lambda: len(repository.competition_registry()) == 6)
    check("fixture_reader_available", lambda: callable(getattr(repository, "list_fixtures", None)))
    contract = EnvironmentContract(getattr(settings, "environment", "local") or "local")
    violations = contract.validate(_settings_view(settings))
    check("environment_contract", lambda: not violations, violations)
    overall = "pass" if all(item["status"] == "pass" for item in checks) else "fail"
    return {
        "status": overall,
        "checks": checks,
        "environment": contract.environment,
        "ran_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
