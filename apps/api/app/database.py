"""Database persistence for immutable predictions and fixture cache."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import StaticPool

from .team_names import to_chinese_team_name


class PredictionRepository:
    """Store prediction versions and fixtures on SQLite or MySQL."""

    def __init__(
        self,
        database_url: str,
        competition_id: str = "legacy",
        model_keys: tuple[str, ...] = ("deepseek",),
    ) -> None:
        self.database_url = self._normalize_url(database_url)
        self.is_sqlite = self.database_url.startswith("sqlite:")
        self.competition_id = competition_id
        self.model_keys = tuple(model_keys)
        connect_args = {"check_same_thread": False} if self.is_sqlite else {}
        engine_kwargs: dict[str, Any] = {"future": True, "pool_pre_ping": not self.is_sqlite}
        if self.database_url in {"sqlite:///:memory:", "sqlite://"}:
            engine_kwargs["poolclass"] = StaticPool
        self.engine: Engine = create_engine(self.database_url, connect_args=connect_args, **engine_kwargs)

    @staticmethod
    def _normalize_url(value: str) -> str:
        """Accept the old SQLite path form and both common MySQL URL forms."""

        value = value.strip().strip('"').strip("'")
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
                        model_key VARCHAR(64) NULL,
                        competition_id VARCHAR(128) NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS evidence_snapshots (
                        id VARCHAR(255) PRIMARY KEY,
                        fixture_id VARCHAR(255) NOT NULL,
                        created_at VARCHAR(64) NOT NULL,
                        source_synced_at VARCHAR(64) NULL,
                        content_hash VARCHAR(64) NOT NULL,
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
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS league_snapshots (
                        league_key VARCHAR(32) PRIMARY KEY,
                        season VARCHAR(32) NOT NULL,
                        updated_at VARCHAR(64) NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS team_snapshots (
                        league_key VARCHAR(32) NOT NULL,
                        team_id VARCHAR(64) NOT NULL,
                        season VARCHAR(32) NOT NULL,
                        updated_at VARCHAR(64) NOT NULL,
                        payload TEXT NOT NULL,
                        PRIMARY KEY (league_key, team_id)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS bets (
                        id VARCHAR(255) PRIMARY KEY,
                        prediction_id VARCHAR(255) NOT NULL UNIQUE,
                        fixture_id VARCHAR(255) NOT NULL,
                        fixture_date VARCHAR(10) NOT NULL,
                        placed_at VARCHAR(64) NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        model_key VARCHAR(64) NULL,
                        competition_id VARCHAR(128) NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS bankroll_transactions (
                        id VARCHAR(255) PRIMARY KEY,
                        created_at VARCHAR(64) NOT NULL,
                        kind VARCHAR(32) NOT NULL,
                        reference_id VARCHAR(255) NULL,
                        amount DECIMAL(14, 2) NOT NULL,
                        balance_after DECIMAL(14, 2) NOT NULL,
                        model_key VARCHAR(64) NULL,
                        competition_id VARCHAR(128) NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS fixture_settlements (
                        id VARCHAR(255) PRIMARY KEY,
                        prediction_id VARCHAR(255) NOT NULL UNIQUE,
                        fixture_id VARCHAR(255) NOT NULL,
                        fixture_date VARCHAR(10) NOT NULL,
                        league_key VARCHAR(32) NOT NULL,
                        season VARCHAR(64) NOT NULL,
                        model_version VARCHAR(128) NOT NULL,
                        model_key VARCHAR(64) NULL,
                        competition_id VARCHAR(128) NULL,
                        settled_at VARCHAR(64) NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
            )
            self._ensure_column(connection, "predictions", "model_key", "VARCHAR(64) NULL")
            self._ensure_column(connection, "predictions", "competition_id", "VARCHAR(128) NULL")
            self._ensure_column(connection, "bets", "model_key", "VARCHAR(64) NULL")
            self._ensure_column(connection, "bets", "competition_id", "VARCHAR(128) NULL")
            self._ensure_column(connection, "bankroll_transactions", "model_key", "VARCHAR(64) NULL")
            self._ensure_column(connection, "bankroll_transactions", "competition_id", "VARCHAR(128) NULL")
            self._ensure_column(connection, "fixture_settlements", "model_key", "VARCHAR(64) NULL")
            self._ensure_column(connection, "fixture_settlements", "competition_id", "VARCHAR(128) NULL")
            connection.execute(text("CREATE TABLE IF NOT EXISTS simulation_competitions (id VARCHAR(128) PRIMARY KEY, created_at VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL, payload TEXT NOT NULL)"))
            connection.execute(text("CREATE TABLE IF NOT EXISTS simulation_accounts (id VARCHAR(255) PRIMARY KEY, competition_id VARCHAR(128) NOT NULL, model_key VARCHAR(64) NOT NULL, initial_balance DECIMAL(14, 2) NOT NULL, created_at VARCHAR(64) NOT NULL, payload TEXT NOT NULL, UNIQUE (competition_id, model_key))"))
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS job_runs (
                        id VARCHAR(255) PRIMARY KEY,
                        job_name VARCHAR(64) NOT NULL,
                        started_at VARCHAR(64) NOT NULL,
                        finished_at VARCHAR(64) NULL,
                        status VARCHAR(32) NOT NULL,
                        item_count INTEGER NOT NULL,
                        error_summary VARCHAR(512) NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
            )
            if not self.is_sqlite:
                for table in (
                    "predictions",
                    "evidence_snapshots",
                    "fixtures",
                    "sync_metadata",
                    "league_snapshots",
                    "team_snapshots",
                    "bets",
                    "bankroll_transactions",
                    "fixture_settlements",
                    "job_runs",
                    "simulation_competitions",
                    "simulation_accounts",
                ):
                    connection.execute(
                        text(
                            f"ALTER TABLE {table} CONVERT TO CHARACTER SET utf8mb4 "
                            "COLLATE utf8mb4_unicode_ci"
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
                "idx_evidence_fixture_created",
                "evidence_snapshots",
                "CREATE INDEX idx_evidence_fixture_created ON evidence_snapshots (fixture_id, created_at)",
            )
            self._ensure_index(
                connection,
                "idx_fixtures_date_league",
                "fixtures",
                "CREATE INDEX idx_fixtures_date_league ON fixtures (fixture_date, league_key, kickoff)",
            )
            self._ensure_index(
                connection,
                "idx_bets_fixture_status",
                "bets",
                "CREATE INDEX idx_bets_fixture_status ON bets (fixture_id, status)",
            )
            self._ensure_index(
                connection,
                "idx_bets_date_status",
                "bets",
                "CREATE INDEX idx_bets_date_status ON bets (fixture_date, status)",
            )
            self._ensure_index(
                connection,
                "idx_settlements_metrics",
                "fixture_settlements",
                "CREATE INDEX idx_settlements_metrics ON fixture_settlements (league_key, season, fixture_date, model_version)",
            )
            self._ensure_index(
                connection,
                "idx_job_runs_name_started",
                "job_runs",
                "CREATE INDEX idx_job_runs_name_started ON job_runs (job_name, started_at)",
            )
            self._backfill_model_columns(connection)
            self._ensure_simulation_accounts(connection)
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
    def _ensure_column(connection: Connection, table: str, column: str, definition: str) -> None:
        columns = {item["name"] for item in inspect(connection).get_columns(table)}
        if column not in columns:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))

    def _backfill_model_columns(self, connection: Connection) -> None:
        """Classify pre-dual-model rows as legacy without changing their payloads."""

        for table, payload_column in (
            ("predictions", "payload"),
            ("bets", "payload"),
            ("bankroll_transactions", "payload"),
            ("fixture_settlements", "payload"),
        ):
            rows = connection.execute(
                text(f"SELECT id, {payload_column} FROM {table} WHERE competition_id IS NULL OR model_key IS NULL")
            ).mappings().all()
            for row in rows:
                try:
                    payload = json.loads(row[payload_column])
                except (TypeError, json.JSONDecodeError):
                    payload = {}
                model_version = str(payload.get("model_version") or "deepseek")
                model_key = str((payload.get("ai") or {}).get("provider") or model_version.split(":", 1)[0] or "deepseek")
                competition_id = str(payload.get("competition_id") or "legacy")
                connection.execute(
                    text(f"UPDATE {table} SET model_key = :model_key, competition_id = :competition_id WHERE id = :id"),
                    {"id": row["id"], "model_key": model_key, "competition_id": competition_id},
                )

    def _ensure_simulation_accounts(self, connection: Connection) -> None:
        created_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        competition = connection.execute(
            text("SELECT id FROM simulation_competitions WHERE id = :id"),
            {"id": self.competition_id},
        ).first()
        if competition is None:
            payload = {"id": self.competition_id, "created_at": created_at, "status": "active"}
            connection.execute(
                text("INSERT INTO simulation_competitions (id, created_at, status, payload) VALUES (:id, :created_at, 'active', :payload)"),
                {**payload, "payload": json.dumps(payload, ensure_ascii=False)},
            )
        for model_key in self.model_keys:
            account_id = f"{self.competition_id}:{model_key}"
            existing = connection.execute(
                text("SELECT id FROM simulation_accounts WHERE competition_id = :competition_id AND model_key = :model_key"),
                {"competition_id": self.competition_id, "model_key": model_key},
            ).first()
            if not existing:
                account = {
                    "id": account_id,
                    "competition_id": self.competition_id,
                    "model_key": model_key,
                    "initial_balance": 1000.0,
                    "created_at": created_at,
                }
                connection.execute(
                    text("INSERT INTO simulation_accounts (id, competition_id, model_key, initial_balance, created_at, payload) VALUES (:id, :competition_id, :model_key, :initial_balance, :created_at, :payload)"),
                    {**account, "payload": json.dumps(account, ensure_ascii=False)},
                )
            transaction_exists = connection.execute(
                text("SELECT id FROM bankroll_transactions WHERE model_key = :model_key AND competition_id = :competition_id LIMIT 1"),
                {"model_key": model_key, "competition_id": self.competition_id},
            ).first()
            if transaction_exists is None:
                transaction = {
                    "id": f"bankroll-initial:{self.competition_id}:{model_key}",
                    "created_at": created_at,
                    "kind": "initial_credit",
                    "reference_id": None,
                    "amount": 1000.0,
                    "balance_after": 1000.0,
                    "model_key": model_key,
                    "competition_id": self.competition_id,
                }
                connection.execute(
                    text("INSERT INTO bankroll_transactions (id, created_at, kind, reference_id, amount, balance_after, model_key, competition_id, payload) VALUES (:id, :created_at, :kind, :reference_id, :amount, :balance_after, :model_key, :competition_id, :payload)"),
                    {**transaction, "payload": json.dumps(transaction, ensure_ascii=False)},
                )

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
                    INSERT INTO predictions (id, fixture_id, created_at, phase, model_version, model_key, competition_id, payload)
                    VALUES (:id, :fixture_id, :created_at, :phase, :model_version, :model_key, :competition_id, :payload)
                    """
                ),
                {
                    "id": prediction["id"],
                    "fixture_id": prediction["fixture_id"],
                    "created_at": prediction["created_at"],
                    "phase": prediction["phase"],
                    "model_version": prediction["model_version"],
                    "model_key": prediction.get("model_key") or (prediction.get("ai") or {}).get("provider") or "deepseek",
                    "competition_id": prediction.get("competition_id") or self.competition_id,
                    "payload": json.dumps(prediction, ensure_ascii=False),
                },
            )

    def save_evidence_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Insert one immutable prediction evidence snapshot."""

        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO evidence_snapshots (
                        id, fixture_id, created_at, source_synced_at, content_hash, payload
                    ) VALUES (
                        :id, :fixture_id, :created_at, :source_synced_at, :content_hash, :payload
                    )
                    """
                ),
                {
                    "id": snapshot["id"],
                    "fixture_id": snapshot["fixture_id"],
                    "created_at": snapshot["created_at"],
                    "source_synced_at": snapshot.get("source_synced_at"),
                    "content_hash": snapshot["content_hash"],
                    "payload": json.dumps(snapshot, ensure_ascii=False),
                },
            )

    def evidence_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        """Return an immutable evidence snapshot by ID."""

        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT payload FROM evidence_snapshots WHERE id = :snapshot_id"),
                {"snapshot_id": snapshot_id},
            ).mappings().first()
        return json.loads(row["payload"]) if row else None

    def latest(
        self,
        fixture_id: str,
        model_key: str | None = None,
        competition_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the newest saved prediction for a fixture."""

        with self.engine.connect() as connection:
            clauses = ["fixture_id = :fixture_id"]
            parameters: dict[str, Any] = {"fixture_id": fixture_id}
            if model_key:
                clauses.append("model_key = :model_key")
                parameters["model_key"] = model_key
            if competition_id:
                clauses.append("competition_id = :competition_id")
                parameters["competition_id"] = competition_id
            row = connection.execute(
                text(
                    f"SELECT payload FROM predictions WHERE {' AND '.join(clauses)} "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                parameters,
            ).mappings().first()
        return json.loads(row["payload"]) if row else None

    def predictions_for_fixture(
        self,
        fixture_id: str,
        model_key: str | None = None,
        competition_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return all immutable prediction versions for one fixture."""

        with self.engine.connect() as connection:
            clauses = ["fixture_id = :fixture_id"]
            parameters: dict[str, Any] = {"fixture_id": fixture_id}
            if model_key:
                clauses.append("model_key = :model_key")
                parameters["model_key"] = model_key
            if competition_id:
                clauses.append("competition_id = :competition_id")
                parameters["competition_id"] = competition_id
            rows = connection.execute(
                text(
                    f"SELECT payload FROM predictions WHERE {' AND '.join(clauses)} "
                    "ORDER BY created_at ASC, id ASC"
                ),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows]

    def replace_fixtures(
        self,
        start_date: str,
        end_date: str,
        fixtures: list[dict[str, Any]],
        synced_at: str,
    ) -> None:
        """Atomically replace a synchronized fixture date window."""

        unique_fixtures = list({fixture["id"]: dict(fixture) for fixture in fixtures}.values())
        with self.engine.begin() as connection:
            if unique_fixtures:
                ids = {f"id_{index}": fixture["id"] for index, fixture in enumerate(unique_fixtures)}
                placeholders = ", ".join(f":{key}" for key in ids)
                existing_rows = connection.execute(
                    text(f"SELECT id, payload FROM fixtures WHERE id IN ({placeholders})"),
                    ids,
                ).mappings().all()
                existing_by_id = {
                    row["id"]: json.loads(row["payload"])
                    for row in existing_rows
                }
                for fixture in unique_fixtures:
                    previous = existing_by_id.get(fixture["id"])
                    if not previous:
                        continue
                    for field in ("evidence", "evidence_synced_at", "lineup_confirmed"):
                        if field in previous:
                            fixture[field] = previous[field]
            connection.execute(
                text("DELETE FROM fixtures WHERE fixture_date BETWEEN :start_date AND :end_date"),
                {"start_date": start_date, "end_date": end_date},
            )
            if unique_fixtures:
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

    def restore_fixture_evidence_from_latest_snapshot(
        self,
        fixture_id: str,
    ) -> dict[str, Any] | None:
        """Restore missing mutable evidence from the newest immutable snapshot."""

        with self.engine.begin() as connection:
            row = connection.execute(
                text("SELECT payload FROM fixtures WHERE id = :fixture_id"),
                {"fixture_id": fixture_id},
            ).mappings().first()
            if not row:
                return None
            fixture = json.loads(row["payload"])
            if fixture.get("evidence"):
                return fixture
            snapshot_row = connection.execute(
                text(
                    "SELECT payload FROM evidence_snapshots WHERE fixture_id = :fixture_id "
                    "ORDER BY created_at DESC, id DESC LIMIT 1"
                ),
                {"fixture_id": fixture_id},
            ).mappings().first()
            if not snapshot_row:
                return None
            snapshot = json.loads(snapshot_row["payload"])
            context = dict((snapshot.get("payload") or {}).get("context") or {})
            if not context:
                return None
            synced_at = context.get("synced_at") or snapshot.get("source_synced_at")
            if synced_at and not context.get("synced_at"):
                context["synced_at"] = synced_at
            fixture["evidence"] = context
            fixture["evidence_synced_at"] = synced_at
            fixture["lineup_confirmed"] = bool((context.get("lineup") or {}).get("confirmed"))
            connection.execute(
                text("UPDATE fixtures SET payload = :payload WHERE id = :fixture_id"),
                {"payload": json.dumps(fixture, ensure_ascii=False), "fixture_id": fixture_id},
            )
            return fixture

    def fixture_sync(self) -> dict[str, Any] | None:
        """Return the latest fixture synchronization metadata."""

        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT synced_at, item_count FROM sync_metadata WHERE name = 'fixtures'"),
            ).mappings().first()
        return dict(row) if row else None

    def save_league_snapshots(self, snapshots: list[dict[str, Any]]) -> None:
        """Replace the latest normalized table for each supplied league."""

        with self.engine.begin() as connection:
            for snapshot in snapshots:
                values = {
                    "league_key": snapshot["league_key"],
                    "season": str((snapshot.get("season") or {}).get("year") or "unknown"),
                    "updated_at": snapshot["updated_at"],
                    "payload": json.dumps(snapshot, ensure_ascii=False),
                }
                exists = connection.execute(
                    text("SELECT league_key FROM league_snapshots WHERE league_key = :league_key"),
                    {"league_key": snapshot["league_key"]},
                ).first()
                if exists:
                    connection.execute(
                        text(
                            "UPDATE league_snapshots SET season = :season, updated_at = :updated_at, "
                            "payload = :payload WHERE league_key = :league_key"
                        ),
                        values,
                    )
                else:
                    connection.execute(
                        text(
                            "INSERT INTO league_snapshots (league_key, season, updated_at, payload) "
                            "VALUES (:league_key, :season, :updated_at, :payload)"
                        ),
                        values,
                    )

    def league_snapshots(self, league_key: str | None = None) -> list[dict[str, Any]]:
        """Return cached current-season tables."""

        where = " WHERE league_key = :league_key" if league_key else ""
        parameters = {"league_key": league_key} if league_key else {}
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(f"SELECT payload FROM league_snapshots{where} ORDER BY league_key"),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows]

    def save_team_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Replace one team's latest current-season detail."""

        values = {
            "league_key": snapshot["league_key"],
            "team_id": str(snapshot["team_id"]),
            "season": str((snapshot.get("season") or {}).get("year") or "unknown"),
            "updated_at": snapshot["updated_at"],
            "payload": json.dumps(snapshot, ensure_ascii=False),
        }
        with self.engine.begin() as connection:
            exists = connection.execute(
                text(
                    "SELECT team_id FROM team_snapshots "
                    "WHERE league_key = :league_key AND team_id = :team_id"
                ),
                values,
            ).first()
            if exists:
                connection.execute(
                    text(
                        "UPDATE team_snapshots SET season = :season, updated_at = :updated_at, "
                        "payload = :payload WHERE league_key = :league_key AND team_id = :team_id"
                    ),
                    values,
                )
            else:
                connection.execute(
                    text(
                        "INSERT INTO team_snapshots "
                        "(league_key, team_id, season, updated_at, payload) "
                        "VALUES (:league_key, :team_id, :season, :updated_at, :payload)"
                    ),
                    values,
                )

    def team_snapshot(self, league_key: str, team_id: str) -> dict[str, Any] | None:
        """Return one cached team snapshot."""

        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT payload FROM team_snapshots "
                    "WHERE league_key = :league_key AND team_id = :team_id"
                ),
                {"league_key": league_key, "team_id": str(team_id)},
            ).mappings().first()
        return json.loads(row["payload"]) if row else None

    @staticmethod
    def _current_balance(
        connection: Connection,
        model_key: str | None = None,
        competition_id: str | None = None,
    ) -> float:
        clauses: list[str] = []
        parameters: dict[str, Any] = {}
        if model_key:
            clauses.append("model_key = :model_key")
            parameters["model_key"] = model_key
        if competition_id:
            clauses.append("competition_id = :competition_id")
            parameters["competition_id"] = competition_id
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        row = connection.execute(
            text(f"SELECT COALESCE(SUM(amount), 0) FROM bankroll_transactions{where}"),
            parameters,
        ).first()
        return round(float(row[0]), 2) if row else 0.0

    def current_balance(self, model_key: str | None = None, competition_id: str | None = None) -> float:
        """Return the latest balance from the append-only transaction ledger."""

        with self.engine.connect() as connection:
            return self._current_balance(connection, model_key, competition_id)

    def bankroll_transactions(
        self,
        model_key: str | None = None,
        competition_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return the complete append-only bankroll ledger."""

        with self.engine.connect() as connection:
            clauses: list[str] = []
            parameters: dict[str, Any] = {}
            if model_key:
                clauses.append("model_key = :model_key")
                parameters["model_key"] = model_key
            if competition_id:
                clauses.append("competition_id = :competition_id")
                parameters["competition_id"] = competition_id
            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = connection.execute(
                text(f"SELECT payload FROM bankroll_transactions{where} ORDER BY created_at ASC, id ASC"),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows]

    def place_bet(self, bet: dict[str, Any]) -> dict[str, Any] | None:
        """Atomically insert one simulated bet and its stake debit."""

        stake = round(float(bet["stake"]), 2)
        if stake <= 0:
            return None
        with self.engine.begin() as connection:
            existing = connection.execute(
                text("SELECT payload FROM bets WHERE prediction_id = :prediction_id"),
                {"prediction_id": bet["prediction_id"]},
            ).mappings().first()
            if existing:
                return json.loads(existing["payload"])
            model_key = bet.get("model_key") or "deepseek"
            competition_id = bet.get("competition_id") or self.competition_id
            balance_before = self._current_balance(connection, model_key, competition_id)
            if stake > balance_before:
                return None
            balance_after = round(balance_before - stake, 2)
            payload = {
                **bet,
                "stake": stake,
                "status": "placed",
                "model_key": model_key,
                "competition_id": competition_id,
                "balance_before": balance_before,
                "balance_after_placement": balance_after,
                "settled_at": None,
                "settlement_result": None,
                "return_amount": None,
                "net_profit": None,
                "balance_after_settlement": None,
            }
            connection.execute(
                text(
                    "INSERT INTO bets "
                    "(id, prediction_id, fixture_id, fixture_date, placed_at, status, model_key, competition_id, payload) "
                    "VALUES (:id, :prediction_id, :fixture_id, :fixture_date, :placed_at, 'placed', :model_key, :competition_id, :payload)"
                ),
                {**payload, "payload": json.dumps(payload, ensure_ascii=False)},
            )
            transaction = {
                "id": f"stake:{payload['id']}",
                "created_at": payload["placed_at"],
                "kind": "stake",
                "reference_id": payload["id"],
                "amount": -stake,
                "balance_after": balance_after,
            }
            connection.execute(
                text(
                    "INSERT INTO bankroll_transactions "
                    "(id, created_at, kind, reference_id, amount, balance_after, model_key, competition_id, payload) "
                    "VALUES (:id, :created_at, :kind, :reference_id, :amount, :balance_after, :model_key, :competition_id, :payload)"
                ),
                {**transaction, "model_key": model_key, "competition_id": competition_id, "payload": json.dumps(transaction, ensure_ascii=False)},
            )
        return payload

    def bet_for_prediction(self, prediction_id: str) -> dict[str, Any] | None:
        """Return the simulated bet linked to one prediction version."""

        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT payload FROM bets WHERE prediction_id = :prediction_id"),
                {"prediction_id": prediction_id},
            ).mappings().first()
        return json.loads(row["payload"]) if row else None

    def bets(
        self,
        status: str | None = None,
        fixture_date: str | None = None,
        model_key: str | None = None,
        competition_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List simulated bets with optional placement-state and match-date filters."""

        clauses: list[str] = []
        parameters: dict[str, str] = {}
        if status:
            clauses.append("status = :status")
            parameters["status"] = status
        if fixture_date:
            clauses.append("fixture_date = :fixture_date")
            parameters["fixture_date"] = fixture_date
        if model_key:
            clauses.append("model_key = :model_key")
            parameters["model_key"] = model_key
        if competition_id:
            clauses.append("competition_id = :competition_id")
            parameters["competition_id"] = competition_id
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(f"SELECT payload FROM bets{where} ORDER BY placed_at DESC, id DESC"),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows]

    def settle_bet(
        self,
        bet_id: str,
        settled_at: str,
        settlement_result: str,
        return_amount: float,
    ) -> dict[str, Any] | None:
        """Atomically mark a bet settled and append its return transaction once."""

        with self.engine.begin() as connection:
            row = connection.execute(
                text("SELECT payload FROM bets WHERE id = :bet_id"),
                {"bet_id": bet_id},
            ).mappings().first()
            if not row:
                return None
            payload = json.loads(row["payload"])
            if payload.get("status") == "settled":
                return payload
            amount = round(float(return_amount), 2)
            model_key = payload.get("model_key") or "deepseek"
            competition_id = payload.get("competition_id") or self.competition_id
            balance_before = self._current_balance(connection, model_key, competition_id)
            balance_after = round(balance_before + amount, 2)
            payload.update(
                {
                    "status": "settled",
                    "settled_at": settled_at,
                    "settlement_result": settlement_result,
                    "return_amount": amount,
                    "net_profit": round(amount - float(payload["stake"]), 2),
                    "balance_after_settlement": balance_after,
                }
            )
            connection.execute(
                text("UPDATE bets SET status = 'settled', payload = :payload WHERE id = :bet_id"),
                {"payload": json.dumps(payload, ensure_ascii=False), "bet_id": bet_id},
            )
            transaction = {
                "id": f"return:{bet_id}",
                "created_at": settled_at,
                "kind": "return",
                "reference_id": bet_id,
                "amount": amount,
                "balance_after": balance_after,
                "model_key": model_key,
                "competition_id": competition_id,
            }
            connection.execute(
                text(
                    "INSERT INTO bankroll_transactions "
                    "(id, created_at, kind, reference_id, amount, balance_after, model_key, competition_id, payload) "
                    "VALUES (:id, :created_at, :kind, :reference_id, :amount, :balance_after, :model_key, :competition_id, :payload)"
                ),
                {**transaction, "model_key": model_key, "competition_id": competition_id, "payload": json.dumps(transaction, ensure_ascii=False)},
            )
        return payload

    def save_fixture_settlement(self, settlement: dict[str, Any]) -> dict[str, Any]:
        """Persist prediction evaluation once per immutable prediction version."""

        with self.engine.begin() as connection:
            existing = connection.execute(
                text("SELECT payload FROM fixture_settlements WHERE prediction_id = :prediction_id"),
                {"prediction_id": settlement["prediction_id"]},
            ).mappings().first()
            if existing:
                return json.loads(existing["payload"])
            connection.execute(
                text(
                    "INSERT INTO fixture_settlements "
                    "(id, prediction_id, fixture_id, fixture_date, league_key, season, model_version, model_key, competition_id, settled_at, payload) "
                    "VALUES (:id, :prediction_id, :fixture_id, :fixture_date, :league_key, "
                    ":season, :model_version, :model_key, :competition_id, :settled_at, :payload)"
                ),
                {
                    **settlement,
                    "model_key": settlement.get("model_key") or (settlement.get("model_version") or "deepseek").split(":", 1)[0],
                    "competition_id": settlement.get("competition_id") or self.competition_id,
                    "payload": json.dumps(settlement, ensure_ascii=False),
                },
            )
        return settlement

    def settlement_for_prediction(self, prediction_id: str) -> dict[str, Any] | None:
        """Return one stored prediction evaluation."""

        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT payload FROM fixture_settlements WHERE prediction_id = :prediction_id"),
                {"prediction_id": prediction_id},
            ).mappings().first()
        return json.loads(row["payload"]) if row else None

    def fixture_settlements(
        self,
        league_key: str | None = None,
        season: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        model_version: str | None = None,
        model_key: str | None = None,
        competition_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List evaluated predictions for metrics queries."""

        clauses: list[str] = []
        parameters: dict[str, str] = {}
        for column, value in (
            ("league_key", league_key),
            ("season", season),
            ("model_version", model_version),
            ("model_key", model_key),
            ("competition_id", competition_id),
        ):
            if value:
                clauses.append(f"{column} = :{column}")
                parameters[column] = value
        if start_date:
            clauses.append("fixture_date >= :start_date")
            parameters["start_date"] = start_date
        if end_date:
            clauses.append("fixture_date <= :end_date")
            parameters["end_date"] = end_date
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(f"SELECT payload FROM fixture_settlements{where} ORDER BY fixture_date, settled_at"),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows]

    def start_job_run(self, job_name: str, started_at: str) -> dict[str, Any]:
        """Persist a durable running marker before external work starts."""

        run = {
            "id": str(uuid.uuid4()),
            "job_name": job_name,
            "started_at": started_at,
            "finished_at": None,
            "status": "running",
            "item_count": 0,
            "error_summary": None,
            "result": None,
        }
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO job_runs "
                    "(id, job_name, started_at, finished_at, status, item_count, error_summary, payload) "
                    "VALUES (:id, :job_name, :started_at, NULL, 'running', 0, NULL, :payload)"
                ),
                {**run, "payload": json.dumps(run, ensure_ascii=False)},
            )
        return run

    def finish_job_run(
        self,
        run_id: str,
        finished_at: str,
        status: str,
        item_count: int,
        result: dict[str, Any] | None,
        error_summary: str | None,
    ) -> dict[str, Any] | None:
        """Finalize a durable job record with bounded diagnostic data."""

        with self.engine.begin() as connection:
            row = connection.execute(
                text("SELECT payload FROM job_runs WHERE id = :run_id"),
                {"run_id": run_id},
            ).mappings().first()
            if not row:
                return None
            payload = json.loads(row["payload"])
            payload.update(
                {
                    "finished_at": finished_at,
                    "status": status,
                    "item_count": int(item_count),
                    "error_summary": error_summary[:500] if error_summary else None,
                    "result": result,
                }
            )
            connection.execute(
                text(
                    "UPDATE job_runs SET finished_at = :finished_at, status = :status, "
                    "item_count = :item_count, error_summary = :error_summary, payload = :payload "
                    "WHERE id = :run_id"
                ),
                {
                    "run_id": run_id,
                    "finished_at": finished_at,
                    "status": status,
                    "item_count": int(item_count),
                    "error_summary": payload["error_summary"],
                    "payload": json.dumps(payload, ensure_ascii=False),
                },
            )
        return payload

    def job_runs(self, job_name: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent durable automation runs."""

        where = " WHERE job_name = :job_name" if job_name else ""
        parameters: dict[str, Any] = {"limit": max(1, min(int(limit), 200))}
        if job_name:
            parameters["job_name"] = job_name
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(f"SELECT payload FROM job_runs{where} ORDER BY started_at DESC, id DESC LIMIT :limit"),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows]

    def last_job_run(self, job_name: str) -> dict[str, Any] | None:
        """Return the newest persisted run for one job."""

        rows = self.job_runs(job_name, 1)
        return rows[0] if rows else None
