"""SQLite persistence for immutable prediction versions."""

import json
import sqlite3
from pathlib import Path
from typing import Any

from .team_names import to_chinese_team_name


class PredictionRepository:
    """Store and retrieve prediction documents without mutating older versions."""

    def __init__(self, path: str) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        """Open a row-aware SQLite connection."""

        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        """Create local storage when it does not exist."""

        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS predictions (
                    id TEXT PRIMARY KEY,
                    fixture_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_predictions_fixture_created "
                "ON predictions (fixture_id, created_at DESC)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS fixtures (
                    id TEXT PRIMARY KEY,
                    provider_id INTEGER,
                    league_key TEXT NOT NULL,
                    fixture_date TEXT NOT NULL,
                    kickoff TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    synced_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_fixtures_date_league "
                "ON fixtures (fixture_date, league_key, kickoff)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_metadata (
                    name TEXT PRIMARY KEY,
                    synced_at TEXT NOT NULL,
                    item_count INTEGER NOT NULL
                )
                """
            )
            self._migrate_provider_id_constraint(connection)
            self._localize_cached_fixtures(connection)

    @staticmethod
    def _migrate_provider_id_constraint(connection: sqlite3.Connection) -> None:
        """Remove the old global provider ID uniqueness constraint."""

        schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'fixtures'"
        ).fetchone()
        if not schema or "provider_id INTEGER UNIQUE" not in (schema[0] or ""):
            return
        connection.execute(
            """
            CREATE TABLE fixtures_migrated (
                id TEXT PRIMARY KEY,
                provider_id INTEGER,
                league_key TEXT NOT NULL,
                fixture_date TEXT NOT NULL,
                kickoff TEXT NOT NULL,
                payload TEXT NOT NULL,
                synced_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO fixtures_migrated
            SELECT id, provider_id, league_key, fixture_date, kickoff, payload, synced_at
            FROM fixtures
            """
        )
        connection.execute("DROP TABLE fixtures")
        connection.execute("ALTER TABLE fixtures_migrated RENAME TO fixtures")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_fixtures_date_league "
            "ON fixtures (fixture_date, league_key, kickoff)"
        )

    @staticmethod
    def _localize_cached_fixtures(connection: sqlite3.Connection) -> None:
        """Upgrade known cached provider names without another network request."""

        rows = connection.execute("SELECT id, payload FROM fixtures").fetchall()
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
                    "UPDATE fixtures SET payload = ? WHERE id = ?",
                    (json.dumps(payload, ensure_ascii=False), row["id"]),
                )

    def save(self, prediction: dict[str, Any]) -> None:
        """Insert one immutable prediction version."""

        with self.connect() as connection:
            connection.execute(
                "INSERT INTO predictions VALUES (?, ?, ?, ?, ?, ?)",
                (
                    prediction["id"],
                    prediction["fixture_id"],
                    prediction["created_at"],
                    prediction["phase"],
                    prediction["model_version"],
                    json.dumps(prediction, ensure_ascii=False),
                ),
            )

    def latest(self, fixture_id: str) -> dict[str, Any] | None:
        """Return the newest saved prediction for a fixture."""

        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM predictions WHERE fixture_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (fixture_id,),
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def replace_fixtures(
        self,
        start_date: str,
        end_date: str,
        fixtures: list[dict[str, Any]],
        synced_at: str,
    ) -> None:
        """Atomically replace a synchronized fixture date window."""

        with self.connect() as connection:
            connection.execute(
                "DELETE FROM fixtures WHERE fixture_date BETWEEN ? AND ?",
                (start_date, end_date),
            )
            connection.executemany(
                """
                INSERT INTO fixtures (
                    id, provider_id, league_key, fixture_date, kickoff, payload, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        fixture["id"],
                        fixture["provider_id"],
                        fixture["league_key"],
                        fixture["fixture_date"],
                        fixture["kickoff"],
                        json.dumps(fixture, ensure_ascii=False),
                        synced_at,
                    )
                    for fixture in fixtures
                ],
            )
            connection.execute(
                """
                INSERT INTO sync_metadata (name, synced_at, item_count)
                VALUES ('fixtures', ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    synced_at = excluded.synced_at,
                    item_count = excluded.item_count
                """,
                (synced_at, len(fixtures)),
            )

    def list_fixtures(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        league_key: str | None = None,
    ) -> list[dict[str, Any]]:
        """List cached fixtures ordered by kickoff."""

        clauses: list[str] = []
        parameters: list[str] = []
        if start_date is not None:
            clauses.append("fixture_date >= ?")
            parameters.append(start_date)
        if end_date is not None:
            clauses.append("fixture_date <= ?")
            parameters.append(end_date)
        if league_key is not None:
            clauses.append("league_key = ?")
            parameters.append(league_key)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT payload FROM fixtures{where} ORDER BY kickoff ASC",
                parameters,
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def fixture(self, fixture_id: str) -> dict[str, Any] | None:
        """Return one cached fixture by application id."""

        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM fixtures WHERE id = ?",
                (fixture_id,),
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def fixture_sync(self) -> dict[str, Any] | None:
        """Return the latest fixture synchronization metadata."""

        with self.connect() as connection:
            row = connection.execute(
                "SELECT synced_at, item_count FROM sync_metadata WHERE name = 'fixtures'"
            ).fetchone()
        return dict(row) if row else None
