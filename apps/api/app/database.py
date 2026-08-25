"""Database persistence for immutable predictions and fixture cache."""

import json
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import StaticPool

from .team_names import to_chinese_team_name


class PredictionRepository:
    """Store prediction versions and fixtures on SQLite or MySQL."""

    def __init__(self, database_url: str) -> None:
        self.database_url = self._normalize_url(database_url)
        self.is_sqlite = self.database_url.startswith("sqlite:")
        connect_args = {"check_same_thread": False} if self.is_sqlite else {}
        engine_kwargs: dict[str, Any] = {"future": True, "pool_pre_ping": not self.is_sqlite}
        if self.database_url in {"sqlite:///:memory:", "sqlite://"}:
            engine_kwargs["poolclass"] = StaticPool
        self.engine: Engine = create_engine(self.database_url, connect_args=connect_args, **engine_kwargs)

    @staticmethod
    def _normalize_url(value: str) -> str:
        """Accept the old SQLite path form and both common MySQL URL forms."""

        if value.startswith("mysql://"):
            return "mysql+pymysql://" + value.removeprefix("mysql://")
        if value.startswith(("sqlite:", "mysql+")):
            return value
        if value == ":memory:":
            return "sqlite:///:memory:"
        return f"sqlite:///{Path(value).resolve().as_posix()}"

    def connect(self) -> Connection:
        """Open a SQLAlchemy connection for callers that need one transaction."""

        return self.engine.connect()

    def initialize(self) -> None:
        """Create the shared schema and apply the SQLite legacy migration."""

        if self.is_sqlite and not self.database_url.endswith(":memory:"):
            Path(self.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS predictions (
                        id VARCHAR(255) PRIMARY KEY,
                        fixture_id VARCHAR(255) NOT NULL,
                        created_at VARCHAR(64) NOT NULL,
                        phase VARCHAR(32) NOT NULL,
                        model_version VARCHAR(128) NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS fixtures (
                        id VARCHAR(255) PRIMARY KEY,
                        provider_id INTEGER NULL,
                        league_key VARCHAR(32) NOT NULL,
                        fixture_date VARCHAR(10) NOT NULL,
                        kickoff VARCHAR(64) NOT NULL,
                        payload TEXT NOT NULL,
                        synced_at VARCHAR(64) NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS sync_metadata (
                        name VARCHAR(64) PRIMARY KEY,
                        synced_at VARCHAR(64) NOT NULL,
                        item_count INTEGER NOT NULL
                    )
                    """
                )
            )
            self._ensure_index(
                connection,
                "idx_predictions_fixture_created",
                "predictions",
                "CREATE INDEX idx_predictions_fixture_created ON predictions (fixture_id, created_at)",
            )
            self._ensure_index(
                connection,
                "idx_fixtures_date_league",
                "fixtures",
                "CREATE INDEX idx_fixtures_date_league ON fixtures (fixture_date, league_key, kickoff)",
            )
            if self.is_sqlite:
                self._migrate_provider_id_constraint(connection)
            self._localize_cached_fixtures(connection)

    @staticmethod
    def _ensure_index(connection: Connection, name: str, table: str, ddl: str) -> None:
        """Create an index once on either supported dialect."""

        existing = {item["name"] for item in inspect(connection).get_indexes(table)}
        if name not in existing:
            connection.execute(text(ddl))

    @staticmethod
    def _migrate_provider_id_constraint(connection: Connection) -> None:
        """Remove the old SQLite-only global provider ID uniqueness constraint."""

        schema = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'fixtures'")
        ).mappings().first()
        sql = (schema or {}).get("sql") or ""
        if "provider_id INTEGER UNIQUE" not in sql:
            return
        connection.execute(text("ALTER TABLE fixtures RENAME TO fixtures_legacy"))
        connection.execute(
            text(
                """
                CREATE TABLE fixtures (
                    id VARCHAR(255) PRIMARY KEY,
                    provider_id INTEGER NULL,
                    league_key VARCHAR(32) NOT NULL,
                    fixture_date VARCHAR(10) NOT NULL,
                    kickoff VARCHAR(64) NOT NULL,
                    payload TEXT NOT NULL,
                    synced_at VARCHAR(64) NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO fixtures (id, provider_id, league_key, fixture_date, kickoff, payload, synced_at)
                SELECT id, provider_id, league_key, fixture_date, kickoff, payload, synced_at
                FROM fixtures_legacy
                """
            )
        )
        connection.execute(text("DROP TABLE fixtures_legacy"))

    @staticmethod
    def _localize_cached_fixtures(connection: Connection) -> None:
        """Upgrade known cached provider names without another network request."""

        rows = connection.execute(text("SELECT id, payload FROM fixtures")).mappings().all()
        for row in rows:
            payload = json.loads(row["payload"])
            changed = False
            for side in ("home_team", "away_team"):
                team = payload.get(side) or {}
                original = team.get("name")
                localized = to_chinese_team_name(original) if original else original
                if localized != original:
                    team["name"] = localized
                    changed = True
            if changed:
                connection.execute(
                    text("UPDATE fixtures SET payload = :payload WHERE id = :id"),
                    {"payload": json.dumps(payload, ensure_ascii=False), "id": row["id"]},
                )

    def save(self, prediction: dict[str, Any]) -> None:
        """Insert one immutable prediction version."""

        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO predictions (id, fixture_id, created_at, phase, model_version, payload)
                    VALUES (:id, :fixture_id, :created_at, :phase, :model_version, :payload)
                    """
                ),
                {
                    "id": prediction["id"],
                    "fixture_id": prediction["fixture_id"],
                    "created_at": prediction["created_at"],
                    "phase": prediction["phase"],
                    "model_version": prediction["model_version"],
                    "payload": json.dumps(prediction, ensure_ascii=False),
                },
            )

    def latest(self, fixture_id: str) -> dict[str, Any] | None:
        """Return the newest saved prediction for a fixture."""

        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT payload FROM predictions WHERE fixture_id = :fixture_id "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"fixture_id": fixture_id},
            ).mappings().first()
        return json.loads(row["payload"]) if row else None

    def replace_fixtures(
        self,
        start_date: str,
        end_date: str,
        fixtures: list[dict[str, Any]],
        synced_at: str,
    ) -> None:
        """Atomically replace a synchronized fixture date window."""

        unique_fixtures = list({fixture["id"]: fixture for fixture in fixtures}.values())
        with self.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM fixtures WHERE fixture_date BETWEEN :start_date AND :end_date"),
                {"start_date": start_date, "end_date": end_date},
            )
            if unique_fixtures:
                ids = {f"id_{index}": fixture["id"] for index, fixture in enumerate(unique_fixtures)}
                placeholders = ", ".join(f":{key}" for key in ids)
                connection.execute(text(f"DELETE FROM fixtures WHERE id IN ({placeholders})"), ids)
                connection.execute(
                    text(
                        """
                        INSERT INTO fixtures (
                            id, provider_id, league_key, fixture_date, kickoff, payload, synced_at
                        ) VALUES (:id, :provider_id, :league_key, :fixture_date, :kickoff, :payload, :synced_at)
                        """
                    ),
                    [
                        {
                            "id": fixture["id"],
                            "provider_id": fixture["provider_id"],
                            "league_key": fixture["league_key"],
                            "fixture_date": fixture["fixture_date"],
                            "kickoff": fixture["kickoff"],
                            "payload": json.dumps(fixture, ensure_ascii=False),
                            "synced_at": synced_at,
                        }
                        for fixture in unique_fixtures
                    ],
                )
            existing = connection.execute(
                text("SELECT name FROM sync_metadata WHERE name = 'fixtures'"),
            ).first()
            if existing:
                connection.execute(
                    text("UPDATE sync_metadata SET synced_at = :synced_at, item_count = :item_count WHERE name = 'fixtures'"),
                    {"synced_at": synced_at, "item_count": len(unique_fixtures)},
                )
            else:
                connection.execute(
                    text("INSERT INTO sync_metadata (name, synced_at, item_count) VALUES ('fixtures', :synced_at, :item_count)"),
                    {"synced_at": synced_at, "item_count": len(unique_fixtures)},
                )

    def list_fixtures(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        league_key: str | None = None,
    ) -> list[dict[str, Any]]:
        """List cached fixtures ordered by kickoff."""

        clauses: list[str] = []
        parameters: dict[str, str] = {}
        if start_date is not None:
            clauses.append("fixture_date >= :start_date")
            parameters["start_date"] = start_date
        if end_date is not None:
            clauses.append("fixture_date <= :end_date")
            parameters["end_date"] = end_date
        if league_key is not None:
            clauses.append("league_key = :league_key")
            parameters["league_key"] = league_key
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(f"SELECT payload FROM fixtures{where} ORDER BY kickoff ASC"),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows]

    def fixture(self, fixture_id: str) -> dict[str, Any] | None:
        """Return one cached fixture by application ID."""

        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT payload FROM fixtures WHERE id = :fixture_id"),
                {"fixture_id": fixture_id},
            ).mappings().first()
        return json.loads(row["payload"]) if row else None

    def save_fixture_evidence(self, fixture_id: str, context: dict[str, Any]) -> dict[str, Any] | None:
        """Persist the latest evidence snapshot on a cached fixture."""

        with self.engine.begin() as connection:
            row = connection.execute(
                text("SELECT payload FROM fixtures WHERE id = :fixture_id"),
                {"fixture_id": fixture_id},
            ).mappings().first()
            if not row:
                return None
            payload = json.loads(row["payload"])
            payload["evidence"] = context
            payload["evidence_synced_at"] = context.get("synced_at")
            payload["lineup_confirmed"] = bool((context.get("lineup") or {}).get("confirmed"))
            connection.execute(
                text("UPDATE fixtures SET payload = :payload WHERE id = :fixture_id"),
                {"payload": json.dumps(payload, ensure_ascii=False), "fixture_id": fixture_id},
            )
            return payload

    def fixture_sync(self) -> dict[str, Any] | None:
        """Return the latest fixture synchronization metadata."""

        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT synced_at, item_count FROM sync_metadata WHERE name = 'fixtures'"),
            ).mappings().first()
        return dict(row) if row else None
