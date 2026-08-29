"""Database persistence for immutable predictions and fixture cache."""

import json
import uuid
import hashlib
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
                        prompt_version VARCHAR(128) NULL,
                        evidence_snapshot_id VARCHAR(255) NULL,
                        evidence_hash VARCHAR(64) NULL,
                        evidence_version VARCHAR(128) NULL,
                        odds_snapshot_id VARCHAR(255) NULL,
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
                        captured_at VARCHAR(64) NULL,
                        evidence_version VARCHAR(128) NULL,
                        hash_algorithm VARCHAR(32) NULL,
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
                    CREATE TABLE IF NOT EXISTS odds_snapshots (
                        id VARCHAR(255) PRIMARY KEY,
                        snapshot_id VARCHAR(255) NOT NULL,
                        fixture_id VARCHAR(255) NOT NULL,
                        market VARCHAR(64) NOT NULL,
                        selection VARCHAR(64) NOT NULL,
                        line VARCHAR(64) NULL,
                        price DECIMAL(14, 6) NULL,
                        bookmaker VARCHAR(255) NULL,
                        source VARCHAR(255) NULL,
                        captured_at VARCHAR(64) NOT NULL,
                        source_updated_at VARCHAR(64) NULL,
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
                    CREATE TABLE IF NOT EXISTS player_value_snapshots (
                        canonical_player_id VARCHAR(255) PRIMARY KEY,
                        updated_at VARCHAR(64) NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS player_name_snapshots (
                        canonical_player_id VARCHAR(255) PRIMARY KEY,
                        provider_player_id VARCHAR(255) NULL,
                        updated_at VARCHAR(64) NOT NULL,
                        payload TEXT NOT NULL
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
                        bet_odds DECIMAL(14, 6) NULL,
                        closing_odds DECIMAL(14, 6) NULL,
                        clv DECIMAL(14, 8) NULL,
                        closing_odds_captured_at VARCHAR(64) NULL,
                        line_at_bet VARCHAR(64) NULL,
                        line_at_close VARCHAR(64) NULL,
                        line_changed BOOLEAN NULL,
                        odds_snapshot_id VARCHAR(255) NULL,
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
                    CREATE TABLE IF NOT EXISTS bet_executions (
                        execution_id VARCHAR(255) PRIMARY KEY,
                        prediction_id VARCHAR(255) NOT NULL,
                        fixture_id VARCHAR(255) NOT NULL,
                        fixture_date VARCHAR(10) NULL,
                        model_key VARCHAR(64) NULL,
                        competition_id VARCHAR(128) NULL,
                        market VARCHAR(64) NOT NULL,
                        selection VARCHAR(128) NOT NULL,
                        line VARCHAR(64) NULL,
                        odds DECIMAL(14, 6) NOT NULL,
                        stake DECIMAL(14, 2) NOT NULL,
                        requested_at VARCHAR(64) NOT NULL,
                        executed_at VARCHAR(64) NULL,
                        status VARCHAR(32) NOT NULL,
                        source VARCHAR(32) NOT NULL,
                        result VARCHAR(64) NULL,
                        profit_loss DECIMAL(14, 2) NULL,
                        settled_at VARCHAR(64) NULL,
                        payload TEXT NOT NULL,
                        UNIQUE (prediction_id, market, selection, line)
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
            self._ensure_column(connection, "predictions", "prompt_version", "VARCHAR(128) NULL")
            self._ensure_column(connection, "predictions", "evidence_snapshot_id", "VARCHAR(255) NULL")
            self._ensure_column(connection, "predictions", "evidence_hash", "VARCHAR(64) NULL")
            self._ensure_column(connection, "predictions", "evidence_version", "VARCHAR(128) NULL")
            self._ensure_column(connection, "predictions", "odds_snapshot_id", "VARCHAR(255) NULL")
            self._ensure_column(connection, "evidence_snapshots", "captured_at", "VARCHAR(64) NULL")
            self._ensure_column(connection, "evidence_snapshots", "evidence_version", "VARCHAR(128) NULL")
            self._ensure_column(connection, "evidence_snapshots", "hash_algorithm", "VARCHAR(32) NULL")
            self._ensure_column(connection, "odds_snapshots", "source_updated_at", "VARCHAR(64) NULL")
            self._ensure_column(connection, "bets", "model_key", "VARCHAR(64) NULL")
            self._ensure_column(connection, "bets", "competition_id", "VARCHAR(128) NULL")
            self._ensure_column(connection, "bets", "bet_odds", "DECIMAL(14, 6) NULL")
            self._ensure_column(connection, "bets", "closing_odds", "DECIMAL(14, 6) NULL")
            self._ensure_column(connection, "bets", "clv", "DECIMAL(14, 8) NULL")
            self._ensure_column(connection, "bets", "closing_odds_captured_at", "VARCHAR(64) NULL")
            self._ensure_column(connection, "bets", "line_at_bet", "VARCHAR(64) NULL")
            self._ensure_column(connection, "bets", "line_at_close", "VARCHAR(64) NULL")
            self._ensure_column(connection, "bets", "line_changed", "BOOLEAN NULL")
            self._ensure_column(connection, "bets", "odds_snapshot_id", "VARCHAR(255) NULL")
            self._ensure_column(connection, "bet_executions", "fixture_date", "VARCHAR(10) NULL")
            self._ensure_column(connection, "bet_executions", "model_key", "VARCHAR(64) NULL")
            self._ensure_column(connection, "bet_executions", "competition_id", "VARCHAR(128) NULL")
            self._ensure_column(connection, "bet_executions", "line", "VARCHAR(64) NULL")
            self._ensure_column(connection, "bet_executions", "executed_at", "VARCHAR(64) NULL")
            self._ensure_column(connection, "bet_executions", "result", "VARCHAR(64) NULL")
            self._ensure_column(connection, "bet_executions", "profit_loss", "DECIMAL(14, 2) NULL")
            self._ensure_column(connection, "bet_executions", "settled_at", "VARCHAR(64) NULL")
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
                    "odds_snapshots",
                    "fixtures",
                    "sync_metadata",
                    "league_snapshots",
                    "team_snapshots",
                    "player_value_snapshots",
                    "player_name_snapshots",
                    "bets",
                    "bet_executions",
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
                "idx_odds_snapshot_fixture_captured",
                "odds_snapshots",
                "CREATE INDEX idx_odds_snapshot_fixture_captured ON odds_snapshots (fixture_id, snapshot_id, captured_at)",
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
                "idx_bet_executions_fixture_status",
                "bet_executions",
                "CREATE INDEX idx_bet_executions_fixture_status ON bet_executions (fixture_id, status)",
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
            self._backfill_prediction_integrity_columns(connection)
            self._backfill_bet_evaluation_columns(connection)
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

    @staticmethod
    def _backfill_prediction_integrity_columns(connection: Connection) -> None:
        """Populate newly explicit frozen columns from legacy JSON payloads."""

        rows = connection.execute(
            text(
                "SELECT id, payload FROM predictions WHERE prompt_version IS NULL "
                "OR evidence_snapshot_id IS NULL OR odds_snapshot_id IS NULL"
            )
        ).mappings().all()
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                payload = {}
            ai = payload.get("ai") or {}
            connection.execute(
                text(
                    "UPDATE predictions SET prompt_version = COALESCE(prompt_version, :prompt_version), "
                    "evidence_snapshot_id = COALESCE(evidence_snapshot_id, :evidence_snapshot_id), "
                    "evidence_hash = COALESCE(evidence_hash, :evidence_hash), "
                    "evidence_version = COALESCE(evidence_version, :evidence_version), "
                    "odds_snapshot_id = COALESCE(odds_snapshot_id, :odds_snapshot_id) WHERE id = :id"
                ),
                {
                    "id": row["id"],
                    "prompt_version": payload.get("prompt_version") or ai.get("prompt_version"),
                    "evidence_snapshot_id": payload.get("evidence_snapshot_id"),
                    "evidence_hash": payload.get("evidence_hash"),
                    "evidence_version": payload.get("evidence_version") or ai.get("evidence_version"),
                    "odds_snapshot_id": payload.get("odds_snapshot_id"),
                },
            )

        snapshots = connection.execute(
            text(
                "SELECT id, payload FROM evidence_snapshots WHERE captured_at IS NULL "
                "OR evidence_version IS NULL OR hash_algorithm IS NULL"
            )
        ).mappings().all()
        for row in snapshots:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                payload = {}
            connection.execute(
                text(
                    "UPDATE evidence_snapshots SET captured_at = COALESCE(captured_at, :captured_at), "
                    "evidence_version = COALESCE(evidence_version, :evidence_version), "
                    "hash_algorithm = COALESCE(hash_algorithm, :hash_algorithm) WHERE id = :id"
                ),
                {
                    "id": row["id"],
                    "captured_at": payload.get("captured_at") or payload.get("created_at"),
                    "evidence_version": payload.get("evidence_version"),
                    "hash_algorithm": payload.get("hash_algorithm"),
                },
            )

    @staticmethod
    def _backfill_bet_evaluation_columns(connection: Connection) -> None:
        """Populate additive CLV columns from existing bet JSON payloads."""

        rows = connection.execute(
            text(
                "SELECT id, payload FROM bets WHERE bet_odds IS NULL AND closing_odds IS NULL "
                "AND clv IS NULL AND odds_snapshot_id IS NULL"
            )
        ).mappings().all()
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                payload = {}
            connection.execute(
                text(
                    "UPDATE bets SET bet_odds = :bet_odds, closing_odds = :closing_odds, clv = :clv, "
                    "closing_odds_captured_at = :closing_odds_captured_at, line_at_bet = :line_at_bet, "
                    "line_at_close = :line_at_close, line_changed = :line_changed, odds_snapshot_id = :odds_snapshot_id "
                    "WHERE id = :id"
                ),
                {
                    "id": row["id"],
                    "bet_odds": payload.get("bet_odds") or payload.get("odds"),
                    "closing_odds": payload.get("closing_odds"),
                    "clv": payload.get("clv"),
                    "closing_odds_captured_at": payload.get("closing_odds_captured_at"),
                    "line_at_bet": str(payload["line_at_bet"]) if payload.get("line_at_bet") is not None else None,
                    "line_at_close": str(payload["line_at_close"]) if payload.get("line_at_close") is not None else None,
                    "line_changed": payload.get("line_changed"),
                    "odds_snapshot_id": payload.get("odds_snapshot_id"),
                },
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
                    INSERT INTO predictions (
                        id, fixture_id, created_at, phase, model_version, model_key, competition_id,
                        prompt_version, evidence_snapshot_id, evidence_hash, evidence_version,
                        odds_snapshot_id, payload
                    ) VALUES (
                        :id, :fixture_id, :created_at, :phase, :model_version, :model_key, :competition_id,
                        :prompt_version, :evidence_snapshot_id, :evidence_hash, :evidence_version,
                        :odds_snapshot_id, :payload
                    )
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
                    "prompt_version": prediction.get("prompt_version") or (prediction.get("ai") or {}).get("prompt_version"),
                    "evidence_snapshot_id": prediction.get("evidence_snapshot_id"),
                    "evidence_hash": prediction.get("evidence_hash"),
                    "evidence_version": prediction.get("evidence_version") or (prediction.get("ai") or {}).get("evidence_version"),
                    "odds_snapshot_id": prediction.get("odds_snapshot_id"),
                    "payload": json.dumps(prediction, ensure_ascii=False),
                },
            )

    def save_evidence_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Insert one immutable prediction evidence snapshot."""

        if snapshot.get("hash_algorithm") == "sha256":
            encoded = json.dumps(
                snapshot.get("payload") or {},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            if hashlib.sha256(encoded).hexdigest() != snapshot.get("content_hash"):
                raise ValueError("Evidence snapshot hash does not match payload")
        with self.engine.begin() as connection:
            existing = connection.execute(
                text("SELECT content_hash, payload FROM evidence_snapshots WHERE id = :id"),
                {"id": snapshot["id"]},
            ).mappings().first()
            if existing:
                if existing["content_hash"] != snapshot["content_hash"] or json.loads(existing["payload"]) != snapshot:
                    raise ValueError("Evidence snapshot is immutable")
                return
            connection.execute(
                text(
                    """
                    INSERT INTO evidence_snapshots (
                        id, fixture_id, created_at, captured_at, evidence_version, hash_algorithm,
                        source_synced_at, content_hash, payload
                    ) VALUES (
                        :id, :fixture_id, :created_at, :captured_at, :evidence_version, :hash_algorithm,
                        :source_synced_at, :content_hash, :payload
                    )
                    """
                ),
                {
                    "id": snapshot["id"],
                    "fixture_id": snapshot["fixture_id"],
                    "created_at": snapshot["created_at"],
                    "captured_at": snapshot.get("captured_at") or snapshot.get("created_at"),
                    "evidence_version": snapshot.get("evidence_version"),
                    "hash_algorithm": snapshot.get("hash_algorithm"),
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

    def save_odds_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Persist one append-only odds capture, represented by quote rows."""

        group_id = snapshot.get("snapshot_id") or snapshot.get("id")
        quotes = snapshot.get("quotes") or []
        if not quotes and snapshot.get("market") and snapshot.get("selection"):
            quotes = [
                {
                    "market": snapshot["market"],
                    "selection": snapshot["selection"],
                    "line": snapshot.get("line"),
                    "price": snapshot.get("price"),
                    "bookmaker": snapshot.get("bookmaker"),
                    "source": snapshot.get("source"),
                    "captured_at": snapshot.get("captured_at"),
                }
            ]
        if not quotes:
            return
        if not group_id:
            raise ValueError("Odds snapshot id is required")
        snapshot = {**snapshot, "id": group_id, "quotes": quotes}
        with self.engine.begin() as connection:
            existing = connection.execute(
                text(
                    "SELECT fixture_id, captured_at, source_updated_at, bookmaker, source, payload "
                    "FROM odds_snapshots WHERE snapshot_id = :snapshot_id ORDER BY id"
                ),
                {"snapshot_id": snapshot["id"]},
            ).mappings().all()
            if existing:
                existing_quotes = [json.loads(row["payload"]) for row in existing]
                if (
                    existing_quotes != quotes
                    or existing[0]["fixture_id"] != snapshot["fixture_id"]
                    or existing[0]["captured_at"] != snapshot["captured_at"]
                    or existing[0]["source_updated_at"] != snapshot.get("source_updated_at")
                    or existing[0]["bookmaker"] != snapshot.get("bookmaker")
                    or existing[0]["source"] != snapshot.get("source")
                ):
                    raise ValueError("Odds snapshot is immutable")
                return
            for quote in quotes:
                quote_id = f"{snapshot['id']}:{quote['market']}:{quote['selection']}:{quote.get('line')}"
                connection.execute(
                    text(
                        """
                        INSERT INTO odds_snapshots (
                            id, snapshot_id, fixture_id, market, selection, line, price,
                            bookmaker, source, captured_at, source_updated_at, payload
                        ) VALUES (
                            :id, :snapshot_id, :fixture_id, :market, :selection, :line, :price,
                            :bookmaker, :source, :captured_at, :source_updated_at, :payload
                        )
                        """
                    ),
                    {
                        "id": quote_id,
                        "snapshot_id": snapshot["id"],
                        "fixture_id": snapshot["fixture_id"],
                        "market": quote["market"],
                        "selection": quote["selection"],
                        "line": str(quote["line"]) if quote.get("line") is not None else None,
                        "price": quote.get("price"),
                        "bookmaker": quote.get("bookmaker"),
                        "source": quote.get("source"),
                        "captured_at": quote.get("captured_at") or snapshot["captured_at"],
                        "source_updated_at": quote.get("source_updated_at") or snapshot.get("source_updated_at"),
                        "payload": json.dumps(quote, ensure_ascii=False),
                    },
                )

    def save_odds_snapshots(self, snapshots: list[dict[str, Any]]) -> None:
        """Persist a batch of independent odds captures."""

        for snapshot in snapshots:
            self.save_odds_snapshot(snapshot)

    def odds_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        """Return one immutable odds capture and its quote rows."""

        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT snapshot_id, fixture_id, captured_at, source_updated_at, bookmaker, source, payload "
                    "FROM odds_snapshots WHERE snapshot_id = :snapshot_id ORDER BY id"
                ),
                {"snapshot_id": snapshot_id},
            ).mappings().all()
        if not rows:
            return None
        quotes = [json.loads(row["payload"]) for row in rows]
        return {
            "id": snapshot_id,
            "fixture_id": rows[0]["fixture_id"],
            "captured_at": rows[0]["captured_at"],
            "source_updated_at": rows[0]["source_updated_at"],
            "bookmaker": rows[0]["bookmaker"],
            "source": rows[0]["source"],
            "quotes": quotes,
            "payload": _odds_payload_from_quotes(quotes),
        }

    def odds_snapshots(self, fixture_id: str | None = None) -> list[dict[str, Any]]:
        """List immutable odds captures, newest capture last."""

        clauses = ["1 = 1"]
        parameters: dict[str, Any] = {}
        if fixture_id:
            clauses.append("fixture_id = :fixture_id")
            parameters["fixture_id"] = fixture_id
        with self.engine.connect() as connection:
            ids = connection.execute(
                text(
                    "SELECT snapshot_id, MAX(captured_at) AS captured_at "
                    f"FROM odds_snapshots WHERE {' AND '.join(clauses)} "
                    "GROUP BY snapshot_id ORDER BY captured_at, snapshot_id"
                ),
                parameters,
            ).mappings().all()
        return [item for row in ids if (item := self.odds_snapshot(row["snapshot_id"] or ""))]

    def closing_odds_for_bet(
        self,
        fixture_id: str,
        kickoff: str,
        bet: dict[str, Any],
        allow_line_change: bool = False,
    ) -> dict[str, Any] | None:
        """Return the latest matching odds capture strictly before kickoff."""

        kickoff_at = _parse_datetime(kickoff)
        if kickoff_at is None:
            return None
        market = str(bet.get("market") or "")
        selection = str(bet.get("selection") or "")
        target_line = bet.get("line_at_bet")
        if target_line is None:
            target_line = bet.get("handicap_line")
        target_bookmaker = bet.get("bookmaker")
        best: tuple[datetime, dict[str, Any]] | None = None
        fallback_line_best: tuple[datetime, dict[str, Any]] | None = None
        for snapshot in self.odds_snapshots(fixture_id):
            for quote in snapshot.get("quotes") or []:
                if quote.get("market") != market or quote.get("selection") != selection:
                    continue
                if target_bookmaker and quote.get("bookmaker") != target_bookmaker:
                    continue
                captured_at = _parse_datetime(quote.get("captured_at"))
                if captured_at is None or captured_at >= kickoff_at:
                    continue
                candidate = (captured_at, {**quote, "snapshot_id": snapshot.get("id")})
                if _same_line(quote.get("line"), target_line):
                    if best is None or captured_at > best[0]:
                        best = candidate
                elif allow_line_change and market == "asian_handicap":
                    if fallback_line_best is None or captured_at > fallback_line_best[0]:
                        fallback_line_best = candidate
        return (best or fallback_line_best)[1] if (best or fallback_line_best) else None

    def update_prediction(
        self,
        prediction_id: str,
        updates: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """Update lifecycle metadata only; frozen forecast fields are rejected."""

        updates = {**(updates or {}), **kwargs}
        allowed = {"status", "metadata"}
        forbidden = set(updates) - allowed
        if forbidden:
            raise ValueError(f"Prediction fields are immutable: {', '.join(sorted(forbidden))}")
        with self.engine.begin() as connection:
            row = connection.execute(
                text("SELECT payload FROM predictions WHERE id = :id"),
                {"id": prediction_id},
            ).mappings().first()
            if not row:
                return None
            payload = json.loads(row["payload"])
            payload.update({key: value for key, value in updates.items() if key in allowed})
            connection.execute(
                text("UPDATE predictions SET payload = :payload WHERE id = :id"),
                {"id": prediction_id, "payload": json.dumps(payload, ensure_ascii=False)},
            )
        return payload

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

    def latest_current(
        self,
        fixture_id: str,
        prompt_version: str,
        model_key: str | None = None,
        competition_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the newest prediction compatible with the active prompt contract."""

        compatible = [
            item
            for item in self.predictions_for_fixture(fixture_id, model_key, competition_id)
            if (item.get("ai") or {}).get("prompt_version") == prompt_version
        ]
        return max(compatible, key=lambda item: (str(item.get("created_at") or ""), str(item["id"]))) if compatible else None

    def current_predictions_for_fixture(
        self,
        fixture_id: str,
        prompt_version: str,
        competition_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return at most one active-contract prediction per model."""

        items = self.predictions_for_fixture(fixture_id, competition_id=competition_id)
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            if (item.get("ai") or {}).get("prompt_version") != prompt_version:
                continue
            key = str(item.get("model_key") or (item.get("ai") or {}).get("provider") or "deepseek")
            groups.setdefault(key, []).append(item)
        return [
            max(group, key=lambda item: (str(item.get("created_at") or ""), str(item["id"])))
            for _, group in sorted(groups.items())
        ]

    def current_prediction_decisions(
        self,
        prompt_version: str | None = None,
        fixture_date: str | None = None,
        league_key: str | None = None,
        model_version: str | None = None,
        model_key: str | None = None,
        competition_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return the newest prediction per fixture/model with its cached fixture."""

        clauses: list[str] = []
        parameters: dict[str, Any] = {}
        for column, value in (
            ("p.competition_id", competition_id),
            ("p.model_key", model_key),
            ("p.model_version", model_version),
            ("f.fixture_date", fixture_date),
            ("f.league_key", league_key),
        ):
            if value:
                parameter = column.split(".")[-1]
                clauses.append(f"{column} = :{parameter}")
                parameters[parameter] = value
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT p.payload AS prediction_payload, f.payload AS fixture_payload "
                    "FROM predictions p LEFT JOIN fixtures f ON f.id = p.fixture_id"
                    f"{where} ORDER BY p.created_at DESC, p.id DESC"
                ),
                parameters,
            ).mappings().all()
        groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for row in rows:
            prediction = json.loads(row["prediction_payload"])
            if prompt_version and (prediction.get("ai") or {}).get("prompt_version") != prompt_version:
                continue
            key = (
                str(prediction.get("fixture_id") or ""),
                str(prediction.get("model_key") or (prediction.get("ai") or {}).get("provider") or "deepseek"),
                str((prediction.get("experiment") or {}).get("strategy_id") or "baseline"),
                str((prediction.get("experiment") or {}).get("strategy_version") or "v1"),
            )
            if key not in groups:
                groups[key] = {
                    "prediction": prediction,
                    "fixture": json.loads(row["fixture_payload"]) if row.get("fixture_payload") else None,
                }
        return sorted(
            groups.values(),
            key=lambda item: (
                str((item.get("fixture") or {}).get("fixture_date") or ""),
                str((item.get("fixture") or {}).get("kickoff") or ""),
                str((item.get("prediction") or {}).get("id") or ""),
            ),
        )

    def prediction_retention_preview(
        self,
        prompt_version: str,
        competition_id: str | None = None,
        fixture_id: str | None = None,
        model_key: str | None = None,
    ) -> dict[str, Any]:
        """Count superseded prediction data without changing it."""

        with self.engine.connect() as connection:
            plan = self._prediction_retention_plan(
                connection,
                prompt_version,
                competition_id,
                fixture_id,
                model_key,
            )
        return self._prediction_retention_summary(plan, prompt_version)

    def prune_prediction_history(
        self,
        prompt_version: str,
        competition_id: str | None = None,
        fixture_id: str | None = None,
        model_key: str | None = None,
    ) -> dict[str, Any]:
        """Delete superseded prediction data and rebuild affected simulated ledgers."""

        with self.engine.begin() as connection:
            plan = self._prediction_retention_plan(
                connection,
                prompt_version,
                competition_id,
                fixture_id,
                model_key,
            )
            self._delete_values(connection, "bankroll_transactions", "reference_id", plan["bet_ids"])
            self._delete_values(connection, "fixture_settlements", "prediction_id", plan["prediction_ids"])
            self._delete_values(connection, "bets", "id", plan["bet_ids"])
            self._delete_values(connection, "predictions", "id", plan["prediction_ids"])
            self._delete_values(connection, "evidence_snapshots", "id", plan["snapshot_ids"])
            balances = [
                self._rebuild_simulation_ledger(connection, account_competition, account_model)
                for account_competition, account_model in plan["affected_accounts"]
            ]
        return {
            **self._prediction_retention_summary(plan, prompt_version),
            "balances": balances,
        }

    def _prediction_retention_plan(
        self,
        connection: Connection,
        prompt_version: str,
        competition_id: str | None,
        fixture_id: str | None,
        model_key: str | None,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        parameters: dict[str, str] = {}
        for column, value in (
            ("competition_id", competition_id),
            ("fixture_id", fixture_id),
            ("model_key", model_key),
        ):
            if value:
                clauses.append(f"{column} = :{column}")
                parameters[column] = value
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = connection.execute(
            text(
                "SELECT id, fixture_id, created_at, model_key, competition_id, payload "
                f"FROM predictions{where}"
            ),
            parameters,
        ).mappings().all()
        parsed_rows: list[dict[str, Any]] = []
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for row in rows:
            payload = json.loads(row["payload"])
            normalized = {
                "id": str(row["id"]),
                "fixture_id": str(row["fixture_id"]),
                "created_at": str(row["created_at"]),
                "model_key": str(row["model_key"] or payload.get("model_key") or (payload.get("ai") or {}).get("provider") or "deepseek"),
                "competition_id": str(row["competition_id"] or payload.get("competition_id") or "legacy"),
                "prompt_version": (payload.get("ai") or {}).get("prompt_version"),
                "evidence_snapshot_id": payload.get("evidence_snapshot_id"),
            }
            parsed_rows.append(normalized)
            group_key = (normalized["competition_id"], normalized["fixture_id"], normalized["model_key"])
            groups.setdefault(group_key, []).append(normalized)

        retained_ids: set[str] = set()
        for group in groups.values():
            compatible = [item for item in group if item["prompt_version"] == prompt_version]
            if compatible:
                current = max(compatible, key=lambda item: (item["created_at"], item["id"]))
                retained_ids.add(current["id"])
        deleted_rows = [item for item in parsed_rows if item["id"] not in retained_ids]
        prediction_ids = {item["id"] for item in deleted_rows}

        bet_rows = connection.execute(
            text("SELECT id, prediction_id, model_key, competition_id, payload FROM bets")
        ).mappings().all()
        existing_prediction_ids = {
            str(row["id"])
            for row in connection.execute(text("SELECT id FROM predictions")).mappings().all()
        }
        deleted_bets = [
            row
            for row in bet_rows
            if str(row["prediction_id"]) in prediction_ids
            or str(row["prediction_id"]) not in existing_prediction_ids
        ]
        bet_ids = {str(row["id"]) for row in deleted_bets}
        affected_accounts = sorted(
            {
                (
                    str(row["competition_id"] or json.loads(row["payload"]).get("competition_id") or "legacy"),
                    str(row["model_key"] or json.loads(row["payload"]).get("model_key") or "deepseek"),
                )
                for row in deleted_bets
            }
        )
        transaction_count = sum(
            1
            for row in connection.execute(
                text("SELECT reference_id FROM bankroll_transactions")
            ).mappings().all()
            if row["reference_id"] is not None and str(row["reference_id"]) in bet_ids
        )
        settlement_count = sum(
            1
            for row in connection.execute(
                text("SELECT prediction_id FROM fixture_settlements")
            ).mappings().all()
            if str(row["prediction_id"]) in prediction_ids
        )
        retained_snapshot_ids = set()
        for row in connection.execute(text("SELECT id, payload FROM predictions")).mappings().all():
            if str(row["id"]) in prediction_ids:
                continue
            payload = json.loads(row["payload"])
            if payload.get("evidence_snapshot_id"):
                retained_snapshot_ids.add(str(payload["evidence_snapshot_id"]))
        candidate_snapshot_ids = {
            str(item["evidence_snapshot_id"])
            for item in deleted_rows
            if item.get("evidence_snapshot_id") and str(item["evidence_snapshot_id"]) not in retained_snapshot_ids
        }
        existing_snapshot_ids = {
            str(row["id"])
            for row in connection.execute(text("SELECT id FROM evidence_snapshots")).mappings().all()
        }
        snapshot_ids = candidate_snapshot_ids & existing_snapshot_ids
        return {
            "prediction_ids": prediction_ids,
            "bet_ids": bet_ids,
            "snapshot_ids": snapshot_ids,
            "affected_accounts": affected_accounts,
            "counts": {
                "predictions": len(prediction_ids),
                "bets": len(bet_ids),
                "fixture_settlements": settlement_count,
                "bankroll_transactions": transaction_count,
                "evidence_snapshots": len(snapshot_ids),
            },
        }

    @staticmethod
    def _prediction_retention_summary(plan: dict[str, Any], prompt_version: str) -> dict[str, Any]:
        counts = dict(plan["counts"])
        return {
            "prompt_version": prompt_version,
            "delete_counts": counts,
            "history_count": counts["predictions"],
            "affected_accounts": [
                {"competition_id": competition_id, "model_key": model_key}
                for competition_id, model_key in plan["affected_accounts"]
            ],
        }

    @staticmethod
    def _delete_values(
        connection: Connection,
        table: str,
        column: str,
        values: set[str],
    ) -> None:
        if not values:
            return
        parameters = {f"value_{index}": value for index, value in enumerate(sorted(values))}
        placeholders = ", ".join(f":{key}" for key in parameters)
        connection.execute(text(f"DELETE FROM {table} WHERE {column} IN ({placeholders})"), parameters)

    def _rebuild_simulation_ledger(
        self,
        connection: Connection,
        competition_id: str,
        model_key: str,
    ) -> dict[str, Any]:
        account = connection.execute(
            text(
                "SELECT initial_balance, created_at FROM simulation_accounts "
                "WHERE competition_id = :competition_id AND model_key = :model_key"
            ),
            {"competition_id": competition_id, "model_key": model_key},
        ).mappings().first()
        if account is None:
            raise ValueError(f"Simulation account is missing: {competition_id}/{model_key}")
        transactions = connection.execute(
            text(
                "SELECT id, kind, reference_id, amount, payload FROM bankroll_transactions "
                "WHERE competition_id = :competition_id AND model_key = :model_key "
                "ORDER BY CASE WHEN kind = 'initial_credit' THEN 0 ELSE 1 END, created_at ASC, id ASC"
            ),
            {"competition_id": competition_id, "model_key": model_key},
        ).mappings().all()
        if not any(row["kind"] == "initial_credit" for row in transactions):
            initial = {
                "id": f"bankroll-initial:{competition_id}:{model_key}",
                "created_at": account["created_at"],
                "kind": "initial_credit",
                "reference_id": None,
                "amount": float(account["initial_balance"]),
                "balance_after": float(account["initial_balance"]),
                "model_key": model_key,
                "competition_id": competition_id,
            }
            connection.execute(
                text(
                    "INSERT INTO bankroll_transactions "
                    "(id, created_at, kind, reference_id, amount, balance_after, model_key, competition_id, payload) "
                    "VALUES (:id, :created_at, :kind, :reference_id, :amount, :balance_after, :model_key, :competition_id, :payload)"
                ),
                {**initial, "payload": json.dumps(initial, ensure_ascii=False)},
            )
            transactions = connection.execute(
                text(
                    "SELECT id, kind, reference_id, amount, payload FROM bankroll_transactions "
                    "WHERE competition_id = :competition_id AND model_key = :model_key "
                    "ORDER BY CASE WHEN kind = 'initial_credit' THEN 0 ELSE 1 END, created_at ASC, id ASC"
                ),
                {"competition_id": competition_id, "model_key": model_key},
            ).mappings().all()

        balance = 0.0
        transaction_balances: dict[tuple[str, str], float] = {}
        transaction_amounts: dict[tuple[str, str], float] = {}
        for row in transactions:
            amount = round(float(row["amount"]), 2)
            balance = round(balance + amount, 2)
            payload = json.loads(row["payload"])
            payload.update(
                {
                    "balance_after": balance,
                    "model_key": model_key,
                    "competition_id": competition_id,
                }
            )
            connection.execute(
                text("UPDATE bankroll_transactions SET balance_after = :balance, payload = :payload WHERE id = :id"),
                {"balance": balance, "payload": json.dumps(payload, ensure_ascii=False), "id": row["id"]},
            )
            if row["reference_id"]:
                key = (str(row["reference_id"]), str(row["kind"]))
                transaction_balances[key] = balance
                transaction_amounts[key] = amount

        bets = connection.execute(
            text(
                "SELECT id, payload FROM bets WHERE competition_id = :competition_id AND model_key = :model_key"
            ),
            {"competition_id": competition_id, "model_key": model_key},
        ).mappings().all()
        for row in bets:
            payload = json.loads(row["payload"])
            stake_key = (str(row["id"]), "stake")
            return_key = (str(row["id"]), "return")
            if stake_key in transaction_balances:
                payload["balance_after_placement"] = transaction_balances[stake_key]
                payload["balance_before"] = round(
                    transaction_balances[stake_key] - transaction_amounts[stake_key],
                    2,
                )
            payload["balance_after_settlement"] = transaction_balances.get(return_key)
            connection.execute(
                text("UPDATE bets SET payload = :payload WHERE id = :id"),
                {"payload": json.dumps(payload, ensure_ascii=False), "id": row["id"]},
            )
        return {
            "competition_id": competition_id,
            "model_key": model_key,
            "balance": balance,
        }

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
        odds_snapshot = _odds_snapshot_document(fixture_id, context)
        if odds_snapshot:
            self.save_odds_snapshot(odds_snapshot)
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

    def save_player_values(self, values: list[dict[str, Any]]) -> None:
        """Upsert licensed market-value snapshots with their provenance."""

        with self.engine.begin() as connection:
            for value in values:
                parameters = {
                    "canonical_player_id": value["canonical_player_id"],
                    "updated_at": value.get("cached_at") or datetime.now(UTC).replace(microsecond=0).isoformat(),
                    "payload": json.dumps(value, ensure_ascii=False),
                }
                exists = connection.execute(
                    text(
                        "SELECT canonical_player_id FROM player_value_snapshots "
                        "WHERE canonical_player_id = :canonical_player_id"
                    ),
                    parameters,
                ).first()
                if exists:
                    connection.execute(
                        text(
                            "UPDATE player_value_snapshots SET updated_at = :updated_at, payload = :payload "
                            "WHERE canonical_player_id = :canonical_player_id"
                        ),
                        parameters,
                    )
                else:
                    connection.execute(
                        text(
                            "INSERT INTO player_value_snapshots (canonical_player_id, updated_at, payload) "
                            "VALUES (:canonical_player_id, :updated_at, :payload)"
                        ),
                        parameters,
                    )

    def player_values(self, canonical_player_ids: list[str]) -> list[dict[str, Any]]:
        """Return cached value snapshots for the requested canonical players."""

        if not canonical_player_ids:
            return []
        parameters = {f"player_{index}": player_id for index, player_id in enumerate(canonical_player_ids)}
        placeholders = ", ".join(f":{key}" for key in parameters)
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT payload FROM player_value_snapshots "
                    f"WHERE canonical_player_id IN ({placeholders})"
                ),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows]

    def save_player_names(self, values: list[dict[str, Any]]) -> None:
        """Upsert cached Chinese player-name translations with provenance."""

        with self.engine.begin() as connection:
            for value in values:
                parameters = {
                    "canonical_player_id": value["canonical_player_id"],
                    "provider_player_id": value.get("provider_player_id"),
                    "updated_at": value.get("created_at") or datetime.now(UTC).replace(microsecond=0).isoformat(),
                    "payload": json.dumps(value, ensure_ascii=False),
                }
                exists = connection.execute(
                    text(
                        "SELECT canonical_player_id FROM player_name_snapshots "
                        "WHERE canonical_player_id = :canonical_player_id"
                    ),
                    parameters,
                ).first()
                if exists:
                    connection.execute(
                        text(
                            "UPDATE player_name_snapshots SET provider_player_id = :provider_player_id, "
                            "updated_at = :updated_at, payload = :payload "
                            "WHERE canonical_player_id = :canonical_player_id"
                        ),
                        parameters,
                    )
                else:
                    connection.execute(
                        text(
                            "INSERT INTO player_name_snapshots "
                            "(canonical_player_id, provider_player_id, updated_at, payload) "
                            "VALUES (:canonical_player_id, :provider_player_id, :updated_at, :payload)"
                        ),
                        parameters,
                    )

    def player_names(self, canonical_player_ids: list[str]) -> list[dict[str, Any]]:
        """Return cached Chinese names for the requested canonical players."""

        if not canonical_player_ids:
            return []
        parameters = {f"player_{index}": player_id for index, player_id in enumerate(canonical_player_ids)}
        placeholders = ", ".join(f":{key}" for key in parameters)
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT payload FROM player_name_snapshots "
                    f"WHERE canonical_player_id IN ({placeholders})"
                ),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows]

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
            if payload.get("line_at_bet") is None and payload.get("handicap_line") is not None:
                payload["line_at_bet"] = payload["handicap_line"]
            connection.execute(
                text(
                    "INSERT INTO bets "
                    "(id, prediction_id, fixture_id, fixture_date, placed_at, status, model_key, competition_id, "
                    "bet_odds, closing_odds, clv, closing_odds_captured_at, line_at_bet, line_at_close, "
                    "line_changed, odds_snapshot_id, payload) "
                    "VALUES (:id, :prediction_id, :fixture_id, :fixture_date, :placed_at, 'placed', :model_key, :competition_id, "
                    ":bet_odds, NULL, NULL, NULL, :line_at_bet, NULL, NULL, :odds_snapshot_id, :payload)"
                ),
                {
                    **payload,
                    "bet_odds": payload.get("bet_odds") or payload.get("odds"),
                    "line_at_bet": str(payload["line_at_bet"]) if payload.get("line_at_bet") is not None else None,
                    "odds_snapshot_id": payload.get("odds_snapshot_id"),
                    "payload": json.dumps(payload, ensure_ascii=False),
                },
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

    def create_bet_execution(self, execution: dict[str, Any]) -> dict[str, Any]:
        """Create an idempotent paper execution with frozen price and stake."""

        execution_id = str(execution.get("execution_id") or execution.get("id") or "")
        if not execution_id:
            raise ValueError("Execution id is required")
        required = ("prediction_id", "fixture_id", "market", "selection", "odds", "stake", "requested_at")
        missing = [key for key in required if execution.get(key) is None]
        if missing:
            raise ValueError(f"Execution fields are required: {', '.join(missing)}")
        status = str(execution.get("status") or "PENDING").upper()
        source = str(execution.get("source") or "paper")
        payload = {
            **execution,
            "execution_id": execution_id,
            "status": status,
            "source": source,
            "line": execution.get("line"),
            "odds": round(float(execution["odds"]), 6),
            "stake": round(float(execution["stake"]), 2),
        }
        immutable = ("prediction_id", "fixture_id", "model_key", "competition_id", "market", "selection", "line", "odds", "stake", "source")
        with self.engine.begin() as connection:
            existing = connection.execute(
                text("SELECT payload FROM bet_executions WHERE execution_id = :execution_id"),
                {"execution_id": execution_id},
            ).mappings().first()
            if existing:
                current = json.loads(existing["payload"])
                if any(current.get(key) != payload.get(key) for key in immutable):
                    raise ValueError("Bet execution immutable fields cannot change")
                return current
            duplicate = connection.execute(
                text(
                    "SELECT payload FROM bet_executions WHERE prediction_id = :prediction_id "
                    "AND market = :market AND selection = :selection "
                    "AND (line = :line OR (line IS NULL AND :line IS NULL))"
                ),
                {
                    "prediction_id": payload["prediction_id"],
                    "market": payload["market"],
                    "selection": payload["selection"],
                    "line": str(payload["line"]) if payload["line"] is not None else None,
                },
            ).mappings().first()
            if duplicate:
                current = json.loads(duplicate["payload"])
                if any(current.get(key) != payload.get(key) for key in immutable):
                    raise ValueError("Bet execution identity already exists with different immutable fields")
                return current
            connection.execute(
                text(
                    "INSERT INTO bet_executions (execution_id, prediction_id, fixture_id, fixture_date, model_key, competition_id, "
                    "market, selection, line, odds, stake, requested_at, executed_at, status, source, result, profit_loss, settled_at, payload) "
                    "VALUES (:execution_id, :prediction_id, :fixture_id, :fixture_date, :model_key, :competition_id, :market, :selection, :line, :odds, :stake, :requested_at, :executed_at, :status, :source, NULL, NULL, NULL, :payload)"
                ),
                {
                    **payload,
                    "line": str(payload["line"]) if payload["line"] is not None else None,
                    "payload": json.dumps(payload, ensure_ascii=False),
                },
            )
        return payload

    def bet_execution(self, execution_id: str) -> dict[str, Any] | None:
        """Return one paper execution by its immutable identifier."""

        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT payload FROM bet_executions WHERE execution_id = :execution_id"),
                {"execution_id": execution_id},
            ).mappings().first()
        return json.loads(row["payload"]) if row else None

    def execution_for_prediction(self, prediction_id: str) -> dict[str, Any] | None:
        """Return the paper execution linked to one prediction."""

        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT payload FROM bet_executions WHERE prediction_id = :prediction_id ORDER BY requested_at DESC LIMIT 1"),
                {"prediction_id": prediction_id},
            ).mappings().first()
        return json.loads(row["payload"]) if row else None

    def bet_executions(
        self,
        status: str | None = None,
        fixture_date: str | None = None,
        model_key: str | None = None,
        competition_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List paper executions with optional lifecycle filters."""

        clauses: list[str] = []
        parameters: dict[str, Any] = {}
        for column, value in (
            ("status", status.upper() if status else None),
            ("fixture_date", fixture_date),
            ("model_key", model_key),
            ("competition_id", competition_id),
        ):
            if value:
                clauses.append(f"{column} = :{column}")
                parameters[column] = value
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(f"SELECT payload FROM bet_executions{where} ORDER BY requested_at DESC, execution_id DESC"),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows]

    def settle_bet_execution(
        self,
        execution_id: str,
        *,
        result: str,
        profit_loss: float,
        settled_at: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Append settlement fields without changing frozen execution fields."""

        with self.engine.begin() as connection:
            row = connection.execute(
                text("SELECT payload FROM bet_executions WHERE execution_id = :execution_id"),
                {"execution_id": execution_id},
            ).mappings().first()
            if not row:
                return None
            payload = json.loads(row["payload"])
            if str(payload.get("status") or "").upper() == "SETTLED":
                return payload
            frozen = {key: payload.get(key) for key in ("prediction_id", "fixture_id", "model_key", "competition_id", "market", "selection", "line", "odds", "stake", "source")}
            settlement_fields = {
                key: value
                for key, value in (metadata or {}).items()
                if key in {"clv", "closing_odds", "closing_odds_captured_at", "line_at_close", "line_changed", "result_metadata"}
            }
            payload.update(
                {
                    "status": "SETTLED",
                    "result": result,
                    "profit_loss": round(float(profit_loss), 2),
                    "settled_at": settled_at,
                    **settlement_fields,
                }
            )
            payload.update(frozen)
            connection.execute(
                text(
                    "UPDATE bet_executions SET status = 'SETTLED', result = :result, profit_loss = :profit_loss, "
                    "settled_at = :settled_at, payload = :payload WHERE execution_id = :execution_id"
                ),
                {
                    "execution_id": execution_id,
                    "result": result,
                    "profit_loss": round(float(profit_loss), 2),
                    "settled_at": settled_at,
                    "payload": json.dumps(payload, ensure_ascii=False),
                },
            )
        return payload

    save_bet_execution = create_bet_execution
    settle_execution = settle_bet_execution

    def discard_open_fixture_bets(
        self,
        fixture_id: str,
        model_key: str,
        competition_id: str,
        keep_prediction_id: str | None = None,
    ) -> int:
        """Remove superseded open simulation bets and restore the account ledger."""

        with self.engine.begin() as connection:
            clauses = [
                "fixture_id = :fixture_id",
                "model_key = :model_key",
                "competition_id = :competition_id",
                "status = 'placed'",
            ]
            parameters: dict[str, Any] = {
                "fixture_id": fixture_id,
                "model_key": model_key,
                "competition_id": competition_id,
            }
            if keep_prediction_id:
                clauses.append("prediction_id <> :keep_prediction_id")
                parameters["keep_prediction_id"] = keep_prediction_id
            rows = connection.execute(
                text(f"SELECT id FROM bets WHERE {' AND '.join(clauses)}"),
                parameters,
            ).mappings().all()
            bet_ids = {str(row["id"]) for row in rows}
            if not bet_ids:
                return 0
            execution_rows = connection.execute(
                text("SELECT payload FROM bets WHERE id IN (" + ", ".join(f":bet_{index}" for index, _ in enumerate(sorted(bet_ids))) + ")"),
                {f"bet_{index}": bet_id for index, bet_id in enumerate(sorted(bet_ids))},
            ).mappings().all()
            for execution_row in execution_rows:
                execution_payload = json.loads(execution_row["payload"])
                execution_id = execution_payload.get("execution_id")
                if execution_id:
                    connection.execute(
                        text("UPDATE bet_executions SET status = 'CANCELLED', payload = :payload WHERE execution_id = :execution_id"),
                        {
                            "execution_id": execution_id,
                            "payload": json.dumps({**execution_payload, "status": "CANCELLED"}, ensure_ascii=False),
                        },
                    )
            self._delete_values(connection, "bankroll_transactions", "reference_id", bet_ids)
            self._delete_values(connection, "bets", "id", bet_ids)
            self._rebuild_simulation_ledger(connection, competition_id, model_key)
        return len(bet_ids)

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
        settlement_metadata: dict[str, Any] | None = None,
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
            frozen = {
                key: payload.get(key)
                for key in (
                    "prediction_id",
                    "fixture_id",
                    "market",
                    "selection",
                    "handicap_line",
                    "line_at_bet",
                    "odds",
                    "bet_odds",
                    "stake",
                    "odds_snapshot_id",
                )
            }
            payload.update(
                {
                    "status": "settled",
                    "settled_at": settled_at,
                    "settlement_result": settlement_result,
                    "return_amount": amount,
                    "net_profit": round(amount - float(payload["stake"]), 2),
                    "balance_after_settlement": balance_after,
                    **(settlement_metadata or {}),
                }
            )
            payload.update(frozen)
            connection.execute(
                text("UPDATE bets SET status = 'settled', payload = :payload WHERE id = :bet_id"),
                {"payload": json.dumps(payload, ensure_ascii=False), "bet_id": bet_id},
            )
            connection.execute(
                text(
                    "UPDATE bets SET bet_odds = :bet_odds, closing_odds = :closing_odds, clv = :clv, "
                    "closing_odds_captured_at = :closing_odds_captured_at, line_at_bet = :line_at_bet, "
                    "line_at_close = :line_at_close, line_changed = :line_changed, odds_snapshot_id = :odds_snapshot_id "
                    "WHERE id = :bet_id"
                ),
                {
                    "bet_id": bet_id,
                    "bet_odds": payload.get("bet_odds") or payload.get("odds"),
                    "closing_odds": payload.get("closing_odds"),
                    "clv": payload.get("clv"),
                    "closing_odds_captured_at": payload.get("closing_odds_captured_at"),
                    "line_at_bet": str(payload["line_at_bet"]) if payload.get("line_at_bet") is not None else None,
                    "line_at_close": str(payload["line_at_close"]) if payload.get("line_at_close") is not None else None,
                    "line_changed": payload.get("line_changed"),
                    "odds_snapshot_id": payload.get("odds_snapshot_id"),
                },
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


def _odds_payload_from_quotes(quotes: list[dict[str, Any]]) -> dict[str, Any]:
    """Reconstruct the legacy odds mapping for consumers of a frozen snapshot."""

    payload: dict[str, Any] = {}
    for quote in quotes:
        selection = quote.get("selection")
        market = quote.get("market")
        if market == "1x2" and selection in {"home", "draw", "away"}:
            payload[selection] = quote.get("price")
        elif market == "asian_handicap":
            payload["asian_handicap"] = quote.get("line")
            key = "asian_handicap_home_odd" if selection == "home_handicap" else "asian_handicap_away_odd"
            payload[key] = quote.get("price")
        payload["bookmaker"] = quote.get("bookmaker")
        payload["source"] = quote.get("source")
        payload["updated_at"] = quote.get("source_updated_at") or quote.get("captured_at")
    return payload


def _odds_snapshot_document(fixture_id: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """Create a deterministic capture document from refreshed fixture evidence."""

    odds = context.get("odds")
    if not isinstance(odds, dict):
        return None
    captured_at = datetime.now(UTC).isoformat()
    source_updated_at = str(odds.get("updated_at")) if odds.get("updated_at") else None
    source = odds.get("source") or context.get("source") or "unknown"
    bookmaker = odds.get("bookmaker")
    quotes: list[dict[str, Any]] = []
    for selection in ("home", "draw", "away"):
        if odds.get(selection) is not None:
            quotes.append(
                {
                    "market": "1x2",
                    "selection": selection,
                    "line": None,
                    "price": odds.get(selection),
                    "bookmaker": bookmaker,
                    "source": source,
                    "captured_at": captured_at,
                    "source_updated_at": source_updated_at,
                }
            )
    line = odds.get("asian_handicap")
    for selection, key in (("home_handicap", "asian_handicap_home_odd"), ("away_handicap", "asian_handicap_away_odd")):
        if line is not None and odds.get(key) is not None:
            quotes.append(
                {
                    "market": "asian_handicap",
                    "selection": selection,
                    "line": line,
                    "price": odds.get(key),
                    "bookmaker": bookmaker,
                    "source": source,
                    "captured_at": captured_at,
                    "source_updated_at": source_updated_at,
                }
            )
    if not quotes:
        return None
    encoded = json.dumps({"fixture_id": fixture_id, "quotes": quotes}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return {
        "id": f"odds:{fixture_id}:{hashlib.sha256(encoded).hexdigest()[:32]}",
        "fixture_id": fixture_id,
        "captured_at": captured_at,
        "source_updated_at": source_updated_at,
        "source": source,
        "bookmaker": bookmaker,
        "quotes": quotes,
        "payload": odds,
    }


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _same_line(left: Any, right: Any) -> bool:
    if left is None and right is None:
        return True
    try:
        return abs(float(left) - float(right)) <= 1e-8
    except (TypeError, ValueError):
        return str(left) == str(right)
