"""Database persistence for immutable predictions and fixture cache."""

import json
import uuid
import hashlib
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.pool import StaticPool

from .team_names import to_chinese_team_name


class PredictionRepository:
    """Store prediction versions and fixtures on SQLite or MySQL."""

    _REVISION_WRITE_ATTEMPTS = 4
    _REVISION_RETRY_DELAY_SECONDS = 0.02

    def __init__(
        self,
        database_url: str,
        competition_id: str = "legacy",
        model_keys: tuple[str, ...] = ("deepseek",),
        initial_balance: float = 1000.0,
    ) -> None:
        self.database_url = self._normalize_url(database_url)
        self.is_sqlite = self.database_url.startswith("sqlite:")
        self.competition_id = competition_id
        self.model_keys = tuple(model_keys)
        self.initial_balance = max(0.0, float(initial_balance))
        self._fixture_revision = 0
        # 全量 list_fixtures 的 revision 键缓存：解析 3.5k 行 payload 约 1s，
        # 任何写操作自增 revision 后自动失效（所有写路径均已覆盖）。
        self._fixtures_cache: tuple[int, list[dict[str, Any]]] | None = None
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
                    CREATE TABLE IF NOT EXISTS player_stats_snapshots (
                        id VARCHAR(255) PRIMARY KEY,
                        league VARCHAR(64) NOT NULL,
                        season VARCHAR(32) NOT NULL,
                        team_id VARCHAR(255) NOT NULL,
                        player_id VARCHAR(255) NOT NULL,
                        synced_at VARCHAR(64) NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS venue_locations (
                        query_hash VARCHAR(64) PRIMARY KEY,
                        query_text VARCHAR(255) NOT NULL,
                        latitude DECIMAL(9, 6) NOT NULL,
                        longitude DECIMAL(9, 6) NOT NULL,
                        synced_at VARCHAR(64) NOT NULL
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
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS historical_snapshots (
                        snapshot_id VARCHAR(255) PRIMARY KEY,
                        canonical_fixture_id VARCHAR(255) NOT NULL,
                        fixture_id VARCHAR(255) NOT NULL,
                        as_of VARCHAR(64) NOT NULL,
                        snapshot_version VARCHAR(128) NOT NULL,
                        dataset_version VARCHAR(128) NULL,
                        evidence_snapshot_id VARCHAR(255) NULL,
                        odds_snapshot_id VARCHAR(255) NULL,
                        data_quality_score DECIMAL(8, 6) NULL,
                        created_at VARCHAR(64) NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS historical_predictions (
                        prediction_id VARCHAR(255) PRIMARY KEY,
                        fixture_id VARCHAR(255) NOT NULL,
                        canonical_fixture_id VARCHAR(255) NOT NULL,
                        model_key VARCHAR(64) NOT NULL,
                        model_version VARCHAR(128) NOT NULL,
                        prediction_timestamp VARCHAR(64) NOT NULL,
                        evidence_snapshot_id VARCHAR(255) NULL,
                        feature_snapshot_id VARCHAR(255) NULL,
                        actual_outcome VARCHAR(16) NULL,
                        created_at VARCHAR(64) NOT NULL,
                        payload TEXT NOT NULL,
                        UNIQUE (fixture_id, model_key, model_version, prediction_timestamp)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS feature_registry (
                        id VARCHAR(255) PRIMARY KEY,
                        feature_name VARCHAR(255) NOT NULL,
                        feature_group VARCHAR(32) NOT NULL,
                        entity_type VARCHAR(32) NOT NULL,
                        description TEXT NOT NULL,
                        formula TEXT NOT NULL,
                        source VARCHAR(255) NOT NULL,
                        calculation_version VARCHAR(128) NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        created_at VARCHAR(64) NOT NULL,
                        deprecated_at VARCHAR(64) NULL,
                        payload LONGTEXT NOT NULL,
                        UNIQUE (feature_name, calculation_version)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS feature_snapshots (
                        snapshot_id VARCHAR(255) PRIMARY KEY,
                        fixture_id VARCHAR(255) NOT NULL,
                        prediction_id VARCHAR(255) NULL,
                        evidence_snapshot_id VARCHAR(255) NULL,
                        prediction_cutoff_at VARCHAR(64) NOT NULL,
                        computed_at VARCHAR(64) NOT NULL,
                        feature_version VARCHAR(128) NOT NULL,
                        leakage_detected BOOLEAN NOT NULL,
                        payload LONGTEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS feature_values (
                        feature_value_id VARCHAR(255) PRIMARY KEY,
                        snapshot_id VARCHAR(255) NOT NULL,
                        ordinal INTEGER NOT NULL,
                        feature_name VARCHAR(255) NOT NULL,
                        feature_value LONGTEXT NOT NULL,
                        source VARCHAR(255) NOT NULL,
                        source_record_id VARCHAR(255) NOT NULL,
                        computed_at VARCHAR(64) NOT NULL,
                        available_at VARCHAR(64) NULL,
                        prediction_cutoff_at VARCHAR(64) NOT NULL,
                        feature_version VARCHAR(128) NOT NULL,
                        payload LONGTEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS player_impact_rules (
                        id VARCHAR(255) PRIMARY KEY,
                        player_id VARCHAR(255) NOT NULL,
                        role VARCHAR(64) NOT NULL,
                        impact_type VARCHAR(64) NOT NULL,
                        impact_value DECIMAL(12, 6) NOT NULL,
                        confidence DECIMAL(8, 6) NOT NULL,
                        source VARCHAR(255) NOT NULL,
                        available_at VARCHAR(64) NOT NULL,
                        rule_version VARCHAR(128) NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        created_at VARCHAR(64) NOT NULL,
                        deprecated_at VARCHAR(64) NULL,
                        payload LONGTEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS prediction_revisions (
                        prediction_id VARCHAR(255) NOT NULL,
                        revision_number INTEGER NOT NULL,
                        fixture_id VARCHAR(255) NOT NULL,
                        competition_id VARCHAR(128) NOT NULL,
                        model_key VARCHAR(64) NOT NULL,
                        prediction_cutoff_at VARCHAR(64) NOT NULL,
                        model_version VARCHAR(128) NOT NULL,
                        feature_version VARCHAR(128) NOT NULL,
                        feature_snapshot_id VARCHAR(255) NOT NULL,
                        evidence_snapshot_id VARCHAR(255) NOT NULL,
                        probability_home DECIMAL(10, 8) NOT NULL,
                        probability_draw DECIMAL(10, 8) NOT NULL,
                        probability_away DECIMAL(10, 8) NOT NULL,
                        expected_home_goals DECIMAL(10, 6) NULL,
                        expected_away_goals DECIMAL(10, 6) NULL,
                        uncertainty TEXT NULL,
                        data_quality TEXT NULL,
                        model_agreement TEXT NULL,
                        created_at VARCHAR(64) NOT NULL,
                        payload LONGTEXT NOT NULL,
                        PRIMARY KEY (prediction_id, revision_number),
                        UNIQUE (competition_id, fixture_id, model_key, revision_number)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS leakage_audits (
                        audit_id VARCHAR(255) PRIMARY KEY,
                        prediction_id VARCHAR(255) NOT NULL,
                        feature_snapshot_id VARCHAR(255) NULL,
                        status VARCHAR(16) NOT NULL,
                        prediction_cutoff_at VARCHAR(64) NULL,
                        violations LONGTEXT NOT NULL,
                        features_checked INTEGER NOT NULL,
                        features_passed INTEGER NOT NULL,
                        features_failed INTEGER NOT NULL,
                        audited_at VARCHAR(64) NOT NULL,
                        payload LONGTEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS historical_backfill_runs (
                        run_id VARCHAR(255) PRIMARY KEY,
                        started_at VARCHAR(64) NOT NULL,
                        finished_at VARCHAR(64) NULL,
                        status VARCHAR(32) NOT NULL,
                        total_fixtures INTEGER NOT NULL,
                        eligible_fixtures INTEGER NOT NULL,
                        excluded_fixtures INTEGER NOT NULL,
                        generated_predictions INTEGER NOT NULL,
                        leakage_violations INTEGER NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS raw_data_records (
                        record_id VARCHAR(255) PRIMARY KEY,
                        entity_type VARCHAR(64) NOT NULL,
                        source VARCHAR(255) NOT NULL,
                        source_record_id VARCHAR(255) NOT NULL,
                        payload_hash VARCHAR(64) NULL,
                        captured_at VARCHAR(64) NOT NULL,
                        ingested_at VARCHAR(64) NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS data_sync_runs (
                        run_id VARCHAR(255) PRIMARY KEY,
                        provider VARCHAR(255) NOT NULL,
                        league VARCHAR(16) NULL,
                        entity_type VARCHAR(64) NOT NULL,
                        started_at VARCHAR(64) NOT NULL,
                        finished_at VARCHAR(64) NULL,
                        status VARCHAR(32) NOT NULL,
                        records_seen INTEGER NOT NULL,
                        records_inserted INTEGER NOT NULL,
                        records_updated INTEGER NOT NULL,
                        records_rejected INTEGER NOT NULL,
                        error_category VARCHAR(64) NULL,
                        errors TEXT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS provider_registry (
                        provider VARCHAR(255) PRIMARY KEY,
                        capabilities TEXT NOT NULL,
                        source_priority TEXT NOT NULL,
                        updated_at VARCHAR(64) NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS team_identity_map (
                        canonical_team_id VARCHAR(255) NOT NULL,
                        league VARCHAR(16) NOT NULL,
                        season VARCHAR(32) NOT NULL,
                        source VARCHAR(255) NOT NULL,
                        source_team_id VARCHAR(255) NOT NULL,
                        normalized_name VARCHAR(255) NOT NULL,
                        display_name VARCHAR(255) NOT NULL,
                        identity_status VARCHAR(32) NOT NULL,
                        conflict BOOLEAN NOT NULL,
                        payload TEXT NOT NULL,
                        PRIMARY KEY (source, source_team_id, league, season)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS fixture_identity_map (
                        canonical_fixture_id VARCHAR(255) NOT NULL,
                        league VARCHAR(16) NOT NULL,
                        season VARCHAR(32) NOT NULL,
                        source VARCHAR(255) NOT NULL,
                        source_fixture_id VARCHAR(255) NOT NULL,
                        kickoff_at VARCHAR(64) NOT NULL,
                        identity_status VARCHAR(32) NOT NULL,
                        conflict BOOLEAN NOT NULL,
                        payload TEXT NOT NULL,
                        PRIMARY KEY (source, source_fixture_id, league, season)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS backtest_runs (
                        run_id VARCHAR(255) PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        started_at VARCHAR(64) NOT NULL,
                        finished_at VARCHAR(64) NULL,
                        dataset_version VARCHAR(128) NULL,
                        run_config TEXT NOT NULL,
                        code_version VARCHAR(128) NULL,
                        model_version VARCHAR(128) NULL,
                        feature_version VARCHAR(128) NULL,
                        ensemble_version VARCHAR(128) NULL,
                        calibration_version VARCHAR(128) NULL,
                        status VARCHAR(32) NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS model_evaluation_experiments (
                        experiment_id VARCHAR(255) PRIMARY KEY,
                        created_at VARCHAR(64) NOT NULL,
                        code_version VARCHAR(128) NOT NULL,
                        feature_version VARCHAR(128) NULL,
                        ensemble_version VARCHAR(128) NULL,
                        calibration_version VARCHAR(128) NULL,
                        league VARCHAR(16) NULL,
                        dataset_version VARCHAR(128) NULL,
                        train_range TEXT NULL,
                        validation_range TEXT NULL,
                        test_range TEXT NULL,
                        sample_count INTEGER NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS model_evaluation_metrics (
                        metric_id VARCHAR(255) PRIMARY KEY,
                        experiment_id VARCHAR(255) NOT NULL,
                        league VARCHAR(16) NOT NULL,
                        model_key VARCHAR(64) NOT NULL,
                        sample_count INTEGER NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        payload TEXT NOT NULL,
                        UNIQUE (experiment_id, league, model_key)
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
            self._ensure_column(connection, "feature_values", "registry_id", "VARCHAR(255) NULL")
            self._ensure_column(connection, "feature_values", "entity_type", "VARCHAR(32) NULL")
            self._ensure_column(connection, "feature_values", "entity_id", "VARCHAR(255) NULL")
            self._ensure_column(connection, "feature_values", "value_type", "VARCHAR(32) NULL")
            self._ensure_column(connection, "feature_values", "calculation_version", "VARCHAR(128) NULL")
            self._ensure_column(connection, "feature_values", "source_record_ids", "LONGTEXT NULL")
            self._ensure_column(connection, "feature_values", "quality_score", "DECIMAL(8, 6) NULL")
            self._ensure_column(connection, "feature_values", "missing_reason", "VARCHAR(255) NULL")
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
            self._ensure_column(connection, "raw_data_records", "payload_hash", "VARCHAR(64) NULL")
            self._ensure_column(connection, "model_evaluation_experiments", "train_range", "TEXT NULL")
            self._ensure_column(connection, "model_evaluation_experiments", "validation_range", "TEXT NULL")
            self._ensure_column(connection, "model_evaluation_experiments", "test_range", "TEXT NULL")
            self._backfill_raw_payload_hash(connection)
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
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS competition_registry (
                        competition_key VARCHAR(32) PRIMARY KEY,
                        competition_type VARCHAR(16) NOT NULL,
                        capabilities TEXT NOT NULL,
                        updated_at VARCHAR(64) NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS fixture_conflicts (
                        conflict_id VARCHAR(255) PRIMARY KEY,
                        canonical_fixture_id VARCHAR(255) NOT NULL,
                        competition_key VARCHAR(32) NOT NULL,
                        conflict_type VARCHAR(32) NOT NULL,
                        source_a VARCHAR(255) NOT NULL,
                        source_b VARCHAR(255) NOT NULL,
                        value_a TEXT NULL,
                        value_b TEXT NULL,
                        resolution VARCHAR(64) NOT NULL,
                        resolved BOOLEAN NOT NULL,
                        detected_at VARCHAR(64) NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS model_registry (
                        model_key VARCHAR(64) NOT NULL,
                        model_version VARCHAR(128) NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        competition_scope VARCHAR(64) NULL,
                        feature_version VARCHAR(128) NULL,
                        dataset_fingerprint VARCHAR(255) NULL,
                        training_cutoff VARCHAR(64) NULL,
                        calibration_version VARCHAR(128) NULL,
                        artifact_hash VARCHAR(64) NOT NULL,
                        created_at VARCHAR(64) NOT NULL,
                        payload TEXT NOT NULL,
                        PRIMARY KEY (model_key, model_version)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS market_snapshots (
                        market_snapshot_id VARCHAR(255) PRIMARY KEY,
                        fixture_id VARCHAR(255) NOT NULL,
                        market VARCHAR(64) NOT NULL,
                        captured_at VARCHAR(64) NOT NULL,
                        persisted_at VARCHAR(64) NULL,
                        overround DECIMAL(10, 6) NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
            )
            self._ensure_column(connection, "market_snapshots", "persisted_at", "VARCHAR(64) NULL")
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS research_runs (
                        run_id VARCHAR(255) PRIMARY KEY,
                        status VARCHAR(32) NOT NULL,
                        job_id VARCHAR(255) NULL,
                        created_at VARCHAR(64) NOT NULL,
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
                    "player_stats_snapshots",
                    "venue_locations",
                    "bets",
                    "bet_executions",
                    "bankroll_transactions",
                    "fixture_settlements",
                    "historical_snapshots",
                    "historical_predictions",
                    "feature_registry",
                    "feature_snapshots",
                    "feature_values",
                    "player_impact_rules",
                    "prediction_revisions",
                    "leakage_audits",
                    "historical_backfill_runs",
                    "raw_data_records",
                    "data_sync_runs",
                    "provider_registry",
                    "team_identity_map",
                    "fixture_identity_map",
                    "backtest_runs",
                    "model_evaluation_experiments",
                    "model_evaluation_metrics",
                    "job_runs",
                    "competition_registry",
                    "fixture_conflicts",
                    "model_registry",
                    "market_snapshots",
                    "research_runs",
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
            self._ensure_index(
                connection,
                "idx_historical_snapshots_fixture_as_of",
                "historical_snapshots",
                "CREATE INDEX idx_historical_snapshots_fixture_as_of ON historical_snapshots (fixture_id, as_of)",
            )
            self._ensure_index(
                connection,
                "idx_historical_predictions_fixture_as_of",
                "historical_predictions",
                "CREATE INDEX idx_historical_predictions_fixture_as_of ON historical_predictions (fixture_id, prediction_timestamp)",
            )
            self._ensure_index(
                connection,
                "idx_feature_registry_group_status",
                "feature_registry",
                "CREATE INDEX idx_feature_registry_group_status ON feature_registry (feature_group, status, feature_name)",
            )
            self._ensure_index(
                connection,
                "idx_feature_snapshots_fixture_cutoff",
                "feature_snapshots",
                "CREATE INDEX idx_feature_snapshots_fixture_cutoff ON feature_snapshots (fixture_id, prediction_cutoff_at)",
            )
            self._ensure_index(
                connection,
                "idx_feature_values_snapshot_available",
                "feature_values",
                "CREATE INDEX idx_feature_values_snapshot_available ON feature_values (snapshot_id, available_at)",
            )
            self._ensure_index(
                connection,
                "idx_feature_values_entity_name",
                "feature_values",
                "CREATE INDEX idx_feature_values_entity_name ON feature_values (entity_type, entity_id, feature_name)",
            )
            self._ensure_index(
                connection,
                "idx_player_impact_rules_player_cutoff",
                "player_impact_rules",
                "CREATE INDEX idx_player_impact_rules_player_cutoff ON player_impact_rules (player_id, available_at, status)",
            )
            self._ensure_index(
                connection,
                "idx_prediction_revisions_fixture_model",
                "prediction_revisions",
                "CREATE INDEX idx_prediction_revisions_fixture_model ON prediction_revisions (competition_id, fixture_id, model_key, revision_number)",
            )
            self._ensure_index(
                connection,
                "idx_leakage_audits_prediction",
                "leakage_audits",
                "CREATE INDEX idx_leakage_audits_prediction ON leakage_audits (prediction_id, audited_at)",
            )
            self._ensure_index(
                connection,
                "idx_historical_backfill_runs_started",
                "historical_backfill_runs",
                "CREATE INDEX idx_historical_backfill_runs_started ON historical_backfill_runs (started_at, run_id)",
            )
            self._ensure_index(
                connection,
                "idx_raw_data_entity_captured",
                "raw_data_records",
                "CREATE INDEX idx_raw_data_entity_captured ON raw_data_records (entity_type, captured_at)",
            )
            self._ensure_index(
                connection,
                "idx_raw_data_source_hash",
                "raw_data_records",
                "CREATE INDEX idx_raw_data_source_hash ON raw_data_records (source, source_record_id, payload_hash)",
            )
            self._ensure_index(
                connection,
                "idx_data_sync_runs_started",
                "data_sync_runs",
                "CREATE INDEX idx_data_sync_runs_started ON data_sync_runs (started_at, run_id)",
            )
            self._ensure_index(
                connection,
                "idx_fixture_identity_canonical",
                "fixture_identity_map",
                "CREATE INDEX idx_fixture_identity_canonical ON fixture_identity_map (canonical_fixture_id)",
            )
            self._ensure_index(
                connection,
                "idx_team_identity_canonical",
                "team_identity_map",
                "CREATE INDEX idx_team_identity_canonical ON team_identity_map (canonical_team_id)",
            )
            self._ensure_index(
                connection,
                "idx_backtest_runs_started",
                "backtest_runs",
                "CREATE INDEX idx_backtest_runs_started ON backtest_runs (started_at, run_id)",
            )
            self._ensure_index(
                connection,
                "idx_model_evaluation_experiments_created",
                "model_evaluation_experiments",
                "CREATE INDEX idx_model_evaluation_experiments_created ON model_evaluation_experiments (created_at, experiment_id)",
            )
            self._ensure_index(
                connection,
                "idx_model_evaluation_metrics_lookup",
                "model_evaluation_metrics",
                "CREATE INDEX idx_model_evaluation_metrics_lookup ON model_evaluation_metrics (experiment_id, league, model_key)",
            )
            self._backfill_model_columns(connection)
            self._backfill_prediction_integrity_columns(connection)
            self._backfill_bet_evaluation_columns(connection)
            self._ensure_simulation_accounts(connection)
            if self.is_sqlite:
                self._migrate_provider_id_constraint(connection)
            self._localize_cached_fixtures(connection)
        from .feature_registry import FeatureRegistry

        FeatureRegistry(self).seed()

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

    @staticmethod
    def _backfill_raw_payload_hash(connection: Connection) -> None:
        """Populate the hash column for pre-P5 raw rows without rewriting payloads."""

        rows = connection.execute(
            text("SELECT record_id, payload FROM raw_data_records WHERE payload_hash IS NULL")
        ).mappings().all()
        for row in rows:
            try:
                record = json.loads(row["payload"])
                payload = record.get("payload") if isinstance(record, dict) else {}
                payload_hash = hashlib.sha256(
                    json.dumps(payload or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
                ).hexdigest()
            except (TypeError, json.JSONDecodeError):
                continue
            connection.execute(
                text("UPDATE raw_data_records SET payload_hash = :payload_hash WHERE record_id = :record_id"),
                {"record_id": row["record_id"], "payload_hash": payload_hash},
            )

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
                text("SELECT id, initial_balance, created_at, payload FROM simulation_accounts WHERE competition_id = :competition_id AND model_key = :model_key"),
                {"competition_id": self.competition_id, "model_key": model_key},
            ).mappings().first()
            if not existing:
                account = {
                    "id": account_id,
                    "competition_id": self.competition_id,
                    "model_key": model_key,
                    "initial_balance": self.initial_balance,
                    "created_at": created_at,
                }
                connection.execute(
                    text("INSERT INTO simulation_accounts (id, competition_id, model_key, initial_balance, created_at, payload) VALUES (:id, :competition_id, :model_key, :initial_balance, :created_at, :payload)"),
                    {**account, "payload": json.dumps(account, ensure_ascii=False)},
                )
            elif float(existing["initial_balance"] or 0) < self.initial_balance:
                previous = float(existing["initial_balance"] or 0)
                account = json.loads(existing["payload"] or "{}")
                account.update({"initial_balance": self.initial_balance})
                connection.execute(
                    text("UPDATE simulation_accounts SET initial_balance = :initial_balance, payload = :payload WHERE id = :id"),
                    {
                        "id": existing["id"],
                        "initial_balance": self.initial_balance,
                        "payload": json.dumps(account, ensure_ascii=False),
                    },
                )
                adjustment_id = f"bankroll-initial-adjustment:{self.competition_id}:{model_key}"
                adjustment_exists = connection.execute(
                    text("SELECT id FROM bankroll_transactions WHERE id = :id"),
                    {"id": adjustment_id},
                ).first()
                if adjustment_exists is None:
                    balance_before_adjustment = self._current_balance(
                        connection,
                        model_key,
                        self.competition_id,
                    )
                    adjustment = {
                        "id": adjustment_id,
                        "created_at": created_at,
                        "kind": "initial_credit_adjustment",
                        "reference_id": None,
                        "amount": round(self.initial_balance - previous, 2),
                        "balance_after": round(balance_before_adjustment + self.initial_balance - previous, 2),
                        "model_key": model_key,
                        "competition_id": self.competition_id,
                    }
                    connection.execute(
                        text("INSERT INTO bankroll_transactions (id, created_at, kind, reference_id, amount, balance_after, model_key, competition_id, payload) VALUES (:id, :created_at, :kind, :reference_id, :amount, :balance_after, :model_key, :competition_id, :payload)"),
                        {**adjustment, "payload": json.dumps(adjustment, ensure_ascii=False)},
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
                    "amount": self.initial_balance,
                    "balance_after": self.initial_balance,
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
        """Insert a legacy prediction or route a Round 2 prediction atomically."""

        if "feature_snapshot_id" in prediction:
            self.save_prediction_with_revision(prediction)
            return

        with self.engine.begin() as connection:
            self._insert_prediction(connection, prediction)

    def _insert_prediction(
        self,
        connection: Connection,
        prediction: dict[str, Any],
        *,
        idempotent: bool = False,
    ) -> None:
        phase = str(prediction.get("phase") or "").casefold()
        if phase.startswith("live"):
            raise ValueError(
                "Live predictions must use a separate live_prediction store"
            )
        payload = json.dumps(prediction, ensure_ascii=False)
        if idempotent:
            existing = connection.execute(
                text("SELECT payload FROM predictions WHERE id = :id"),
                {"id": prediction["id"]},
            ).mappings().first()
            if existing:
                if json.loads(existing["payload"]) != prediction:
                    raise ValueError(f"Prediction {prediction['id']} is immutable")
                return
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
                "payload": payload,
            },
        )

    def save_feature_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Persist one immutable point-in-time feature snapshot and its values."""

        snapshot_id = str(snapshot.get("snapshot_id") or snapshot.get("id") or "")
        fixture_id = str(snapshot.get("fixture_id") or snapshot.get("match_id") or "")
        prediction_cutoff_at = str(snapshot.get("prediction_cutoff_at") or "")
        computed_at = str(snapshot.get("computed_at") or snapshot.get("captured_at") or "")
        feature_version = str(snapshot.get("feature_version") or "")
        required = {
            "snapshot_id": snapshot_id,
            "fixture_id": fixture_id,
            "prediction_cutoff_at": prediction_cutoff_at,
            "computed_at": computed_at,
            "feature_version": feature_version,
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ValueError(f"Feature snapshot fields are required: {', '.join(missing)}")
        raw_features = snapshot.get("features")
        if not isinstance(raw_features, list):
            raise ValueError("Feature snapshot features must be a list")

        normalized_features: list[dict[str, Any]] = []
        for ordinal, raw_feature in enumerate(raw_features):
            if not isinstance(raw_feature, dict):
                raise ValueError(f"Feature at index {ordinal} must be an object")
            feature_name = str(raw_feature.get("feature_name") or "")
            source = str(raw_feature.get("source") or "")
            source_record_id = raw_feature.get("source_record_id")
            available_at = raw_feature.get("available_at")
            if "feature_value" in raw_feature:
                feature_value = raw_feature["feature_value"]
            elif "value" in raw_feature:
                feature_value = raw_feature["value"]
            else:
                raise ValueError(f"Feature {feature_name or ordinal} is missing feature_value")
            feature_required = {
                "feature_name": feature_name,
                "source": source,
                "source_record_id": source_record_id,
            }
            feature_missing = [
                key for key, value in feature_required.items()
                if value is None or (isinstance(value, str) and not value)
            ]
            if feature_missing:
                raise ValueError(
                    f"Feature {feature_name or ordinal} fields are required: {', '.join(feature_missing)}"
                )
            if "available_at" not in raw_feature:
                raise ValueError(f"Feature {feature_name or ordinal} fields are required: available_at")
            identity = "|".join(
                (snapshot_id, str(ordinal), feature_name, source, str(source_record_id))
            )
            source_record_ids = raw_feature.get("source_record_ids")
            if not isinstance(source_record_ids, list):
                source_record_ids = [source_record_id]
            source_record_ids = [
                str(value) for value in source_record_ids if value not in (None, "")
            ]
            quality_score = raw_feature.get("quality_score")
            if quality_score is not None:
                quality_score = float(quality_score)
                if not 0 <= quality_score <= 1:
                    raise ValueError(
                        f"Feature {feature_name or ordinal} quality_score must be between 0 and 1"
                    )
            normalized_features.append(
                {
                    **raw_feature,
                    "feature_value_id": "feature-" + hashlib.sha256(identity.encode()).hexdigest(),
                    "snapshot_id": snapshot_id,
                    "feature_name": feature_name,
                    "feature_value": feature_value,
                    "source": source,
                    "source_record_id": str(source_record_id),
                    "source_record_ids": source_record_ids,
                    "registry_id": raw_feature.get("registry_id"),
                    "entity_type": raw_feature.get("entity_type"),
                    "entity_id": raw_feature.get("entity_id"),
                    "value_type": raw_feature.get("value_type") or _feature_value_type(feature_value),
                    "calculation_version": raw_feature.get("calculation_version")
                    or raw_feature.get("feature_version")
                    or feature_version,
                    "quality_score": quality_score,
                    "missing_reason": raw_feature.get("missing_reason"),
                    "computed_at": str(raw_feature.get("computed_at") or computed_at),
                    "available_at": available_at,
                    "prediction_cutoff_at": str(
                        raw_feature.get("prediction_cutoff_at") or prediction_cutoff_at
                    ),
                    "feature_version": str(raw_feature.get("feature_version") or feature_version),
                }
            )
        normalized_snapshot = {
            **snapshot,
            "snapshot_id": snapshot_id,
            "fixture_id": fixture_id,
            "prediction_id": None,
            "prediction_cutoff_at": prediction_cutoff_at,
            "computed_at": computed_at,
            "feature_version": feature_version,
            "leakage_detected": bool(snapshot.get("leakage_detected", False)),
            "features": normalized_features,
        }
        with self.engine.begin() as connection:
            existing = connection.execute(
                text("SELECT payload FROM feature_snapshots WHERE snapshot_id = :snapshot_id"),
                {"snapshot_id": snapshot_id},
            ).mappings().first()
            if existing:
                persisted = json.loads(existing["payload"])
                persisted_features = [
                    json.loads(row["payload"])
                    for row in connection.execute(
                        text(
                            "SELECT payload FROM feature_values WHERE snapshot_id = :snapshot_id "
                            "ORDER BY ordinal ASC, feature_value_id ASC"
                        ),
                        {"snapshot_id": snapshot_id},
                    ).mappings().all()
                ]
                persisted["features"] = persisted_features
                if self._feature_snapshot_identity(persisted) != self._feature_snapshot_identity(
                    normalized_snapshot
                ):
                    raise ValueError(f"Feature snapshot {snapshot_id} is immutable")
                return persisted
            connection.execute(
                text(
                    "INSERT INTO feature_snapshots "
                    "(snapshot_id, fixture_id, prediction_id, evidence_snapshot_id, prediction_cutoff_at, "
                    "computed_at, feature_version, leakage_detected, payload) VALUES "
                    "(:snapshot_id, :fixture_id, :prediction_id, :evidence_snapshot_id, :prediction_cutoff_at, "
                    ":computed_at, :feature_version, :leakage_detected, :payload)"
                ),
                {
                    **normalized_snapshot,
                    "prediction_id": None,
                    "evidence_snapshot_id": snapshot.get("evidence_snapshot_id"),
                    "payload": json.dumps(normalized_snapshot, ensure_ascii=False),
                },
            )
            for ordinal, feature in enumerate(normalized_features):
                connection.execute(
                    text(
                        "INSERT INTO feature_values "
                        "(feature_value_id, snapshot_id, ordinal, feature_name, feature_value, source, "
                        "source_record_id, registry_id, entity_type, entity_id, value_type, calculation_version, "
                        "source_record_ids, quality_score, missing_reason, computed_at, available_at, "
                        "prediction_cutoff_at, feature_version, payload) "
                        "VALUES (:feature_value_id, :snapshot_id, :ordinal, :feature_name, :feature_value, :source, "
                        ":source_record_id, :registry_id, :entity_type, :entity_id, :value_type, :calculation_version, "
                        ":source_record_ids, :quality_score, :missing_reason, :computed_at, :available_at, "
                        ":prediction_cutoff_at, :feature_version, :payload)"
                    ),
                    {
                        **feature,
                        "ordinal": ordinal,
                        "feature_value": json.dumps(feature["feature_value"], ensure_ascii=False),
                        "source_record_ids": json.dumps(
                            feature["source_record_ids"], ensure_ascii=False
                        ),
                        "payload": json.dumps(feature, ensure_ascii=False),
                    },
                )
        return normalized_snapshot

    @staticmethod
    def _feature_snapshot_identity(snapshot: dict[str, Any]) -> dict[str, Any]:
        """Return hash-defining fields; computed_at is intentionally excluded."""

        return {
            "snapshot_id": snapshot.get("snapshot_id") or snapshot.get("id"),
            "fixture_id": snapshot.get("fixture_id") or snapshot.get("match_id"),
            "evidence_snapshot_id": snapshot.get("evidence_snapshot_id"),
            "prediction_cutoff_at": snapshot.get("prediction_cutoff_at"),
            "feature_version": snapshot.get("feature_version"),
            "leakage_detected": bool(snapshot.get("leakage_detected", False)),
            "features": [
                {
                    "feature_name": feature.get("feature_name"),
                    "feature_value": feature.get("feature_value", feature.get("value")),
                    "source": feature.get("source"),
                    "source_record_id": feature.get("source_record_id"),
                    "source_record_ids": feature.get("source_record_ids"),
                    "registry_id": feature.get("registry_id"),
                    "entity_type": feature.get("entity_type"),
                    "entity_id": feature.get("entity_id"),
                    "value_type": feature.get("value_type"),
                    "calculation_version": feature.get("calculation_version"),
                    "quality_score": feature.get("quality_score"),
                    "missing_reason": feature.get("missing_reason"),
                    "available_at": feature.get("available_at"),
                    "prediction_cutoff_at": feature.get("prediction_cutoff_at"),
                    "feature_version": feature.get("feature_version"),
                    "snapshot_id": feature.get("snapshot_id"),
                }
                for feature in snapshot.get("features") or []
            ],
        }

    def feature_values(self, snapshot_id: str) -> list[dict[str, Any]]:
        """Return the immutable per-feature records for one snapshot."""

        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT payload FROM feature_values WHERE snapshot_id = :snapshot_id "
                    "ORDER BY ordinal ASC, feature_value_id ASC"
                ),
                {"snapshot_id": snapshot_id},
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows]

    def feature_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        """Return one feature snapshot with its persisted point-in-time values."""

        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT payload FROM feature_snapshots WHERE snapshot_id = :snapshot_id"),
                {"snapshot_id": snapshot_id},
            ).mappings().first()
        if not row:
            return None
        snapshot = json.loads(row["payload"])
        snapshot["features"] = self.feature_values(snapshot_id)
        return snapshot

    def feature_snapshots(
        self,
        fixture_id: str | None = None,
        prediction_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List immutable feature snapshots, optionally narrowed to one prediction."""

        clauses: list[str] = []
        parameters: dict[str, Any] = {}
        if fixture_id:
            clauses.append("fixture_id = :fixture_id")
            parameters["fixture_id"] = fixture_id
        if prediction_id:
            clauses.append(
                "snapshot_id IN (SELECT feature_snapshot_id FROM prediction_revisions "
                "WHERE prediction_id = :prediction_id)"
            )
            parameters["prediction_id"] = prediction_id
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT snapshot_id, payload FROM feature_snapshots{where} "
                    "ORDER BY prediction_cutoff_at ASC, snapshot_id ASC"
                ),
                parameters,
            ).mappings().all()
        snapshots = []
        for row in rows:
            snapshot = json.loads(row["payload"])
            snapshot["features"] = self.feature_values(str(row["snapshot_id"]))
            snapshots.append(snapshot)
        return snapshots

    def save_feature_registry(self, item: dict[str, Any]) -> dict[str, Any]:
        """Insert one immutable feature definition or update lifecycle fields."""

        required = (
            "id",
            "feature_name",
            "feature_group",
            "entity_type",
            "description",
            "formula",
            "source",
            "calculation_version",
            "status",
            "created_at",
        )
        if any(item.get(key) in (None, "") for key in required):
            raise ValueError("Feature registry definition fields are required")
        values = {
            **item,
            "deprecated_at": item.get("deprecated_at"),
            "payload": json.dumps(item, ensure_ascii=False),
        }
        with self.engine.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT payload FROM feature_registry WHERE id = :id OR "
                    "(feature_name = :feature_name AND calculation_version = :calculation_version)"
                ),
                values,
            ).mappings().first()
            if row:
                existing = json.loads(row["payload"])
                immutable = (
                    "id",
                    "feature_name",
                    "feature_group",
                    "entity_type",
                    "description",
                    "formula",
                    "source",
                    "calculation_version",
                    "created_at",
                    "payload",
                )
                if any(existing.get(key) != item.get(key) for key in immutable):
                    raise ValueError(
                        f"Feature definition {item['feature_name']}:{item['calculation_version']} is immutable"
                    )
                if existing.get("status") == "deprecated" and item.get("status") == "active":
                    return existing
                if (
                    existing.get("status") != item.get("status")
                    or existing.get("deprecated_at") != item.get("deprecated_at")
                ):
                    connection.execute(
                        text(
                            "UPDATE feature_registry SET status = :status, deprecated_at = :deprecated_at, "
                            "payload = :payload WHERE id = :id"
                        ),
                        values,
                    )
                return item
            connection.execute(
                text(
                    "INSERT INTO feature_registry "
                    "(id, feature_name, feature_group, entity_type, description, formula, source, "
                    "calculation_version, status, created_at, deprecated_at, payload) VALUES "
                    "(:id, :feature_name, :feature_group, :entity_type, :description, :formula, :source, "
                    ":calculation_version, :status, :created_at, :deprecated_at, :payload)"
                ),
                values,
            )
        return item

    def feature_registry(
        self,
        feature_name: str | None = None,
        calculation_version: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: dict[str, Any] = {}
        for column, value in (
            ("feature_name", feature_name),
            ("calculation_version", calculation_version),
            ("status", status),
        ):
            if value:
                clauses.append(f"{column} = :{column}")
                parameters[column] = value
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT payload FROM feature_registry{where} "
                    "ORDER BY feature_name, calculation_version"
                ),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows]

    def save_player_impact_rule(self, item: dict[str, Any]) -> dict[str, Any]:
        """Insert one immutable, versioned player impact rule."""

        required = (
            "id",
            "player_id",
            "role",
            "impact_type",
            "impact_value",
            "confidence",
            "source",
            "available_at",
            "rule_version",
            "status",
            "created_at",
        )
        if any(item.get(key) in (None, "") for key in required):
            raise ValueError("Player impact rule fields are required")
        confidence = float(item["confidence"])
        if not 0 <= confidence <= 1:
            raise ValueError("Player impact rule confidence must be between 0 and 1")
        values = {
            **item,
            "impact_value": float(item["impact_value"]),
            "confidence": confidence,
            "deprecated_at": item.get("deprecated_at"),
            "payload": json.dumps(item, ensure_ascii=False),
        }
        with self.engine.begin() as connection:
            row = connection.execute(
                text("SELECT payload FROM player_impact_rules WHERE id = :id"),
                {"id": item["id"]},
            ).mappings().first()
            if row:
                existing = json.loads(row["payload"])
                immutable = tuple(key for key in required if key != "status") + ("payload",)
                if any(existing.get(key) != item.get(key) for key in immutable):
                    raise ValueError(f"Player impact rule {item['id']} is immutable")
                if (
                    existing.get("status") != item.get("status")
                    or existing.get("deprecated_at") != item.get("deprecated_at")
                ):
                    connection.execute(
                        text(
                            "UPDATE player_impact_rules SET status = :status, deprecated_at = :deprecated_at, "
                            "payload = :payload WHERE id = :id"
                        ),
                        values,
                    )
                    return item
                return existing
            connection.execute(
                text(
                    "INSERT INTO player_impact_rules "
                    "(id, player_id, role, impact_type, impact_value, confidence, source, available_at, "
                    "rule_version, status, created_at, deprecated_at, payload) VALUES "
                    "(:id, :player_id, :role, :impact_type, :impact_value, :confidence, :source, :available_at, "
                    ":rule_version, :status, :created_at, :deprecated_at, :payload)"
                ),
                values,
            )
        return item

    def player_impact_rules(
        self,
        *,
        player_ids: Iterable[str] | None = None,
        available_at_lte: str | None = None,
        status: str | None = "active",
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: dict[str, Any] = {}
        normalized_ids = sorted(
            {str(value) for value in player_ids or [] if value not in (None, "")}
        )
        if normalized_ids:
            placeholders = []
            for index, player_id in enumerate(normalized_ids):
                key = f"player_id_{index}"
                placeholders.append(f":{key}")
                parameters[key] = player_id
            clauses.append(f"player_id IN ({', '.join(placeholders)})")
        if available_at_lte:
            clauses.append("available_at <= :available_at_lte")
            parameters["available_at_lte"] = available_at_lte
        if status:
            clauses.append("status = :status")
            parameters["status"] = status
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT payload FROM player_impact_rules{where} "
                    "ORDER BY player_id, impact_type, available_at, rule_version, id"
                ),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows]

    def save_prediction_revision(self, revision: dict[str, Any]) -> dict[str, Any]:
        """Append one immutable revision, allocating its scoped number if omitted."""

        return self._with_revision_retry(
            lambda connection: self._insert_prediction_revision(connection, revision),
            retry_on_conflict=revision.get("revision_number") is None,
        )

    def save_prediction_with_revision(
        self,
        prediction: dict[str, Any],
        revision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Atomically persist an immutable serving prediction and audit revision."""

        candidate = {**prediction, **(revision or {})}
        candidate["prediction_id"] = prediction["id"]
        candidate.setdefault("fixture_id", prediction.get("fixture_id"))
        return self._with_revision_retry(
            lambda connection: self._save_prediction_with_revision_in_transaction(
                connection,
                prediction,
                candidate,
            ),
            retry_on_conflict=candidate.get("revision_number") is None,
        )

    def save_prediction_with_production_evidence(
        self,
        prediction: dict[str, Any],
        revision: dict[str, Any],
        round5_result: dict[str, Any],
        *,
        kickoff_at: Any,
        leakage_audit_id: str,
    ) -> dict[str, Any]:
        """Atomically persist one revision and its verified Round 5 evidence."""

        if bool(getattr(self, "is_historical_replay", False)):
            raise ValueError("Historical replay cannot persist production evidence")
        candidate = {**prediction, **revision, "prediction_id": prediction["id"]}
        candidate.setdefault("fixture_id", prediction.get("fixture_id"))
        self._require_matching_round5_model_probability(candidate, round5_result)
        return self._with_revision_retry(
            lambda connection: self._save_prediction_with_production_evidence_in_transaction(
                connection,
                prediction,
                candidate,
                round5_result,
                kickoff_at=kickoff_at,
                leakage_audit_id=leakage_audit_id,
            ),
            retry_on_conflict=candidate.get("revision_number") is None,
        )

    @staticmethod
    def _require_matching_round5_model_probability(
        revision: dict[str, Any],
        round5_result: dict[str, Any],
    ) -> None:
        audit = round5_result.get("round5_probability_audit")
        model_probability = (
            audit.get("model_probability") if isinstance(audit, dict) else None
        )
        outcomes = ("home", "draw", "away")
        if not isinstance(model_probability, dict):
            raise ValueError("Round 5 model_probability is required")
        try:
            expected = {outcome: float(model_probability[outcome]) for outcome in outcomes}
            columns = {
                "home": float(revision["probability_home"]),
                "draw": float(revision["probability_draw"]),
                "away": float(revision["probability_away"]),
            }
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                "Prediction revision probabilities must match Round 5 model_probability"
            ) from error
        if columns != expected:
            raise ValueError(
                "Prediction revision probabilities must match Round 5 model_probability"
            )
        for field in ("probabilities", "model_probabilities"):
            value = revision.get(field)
            if value is None:
                continue
            if not isinstance(value, dict):
                raise ValueError(
                    "Prediction revision probabilities must match Round 5 model_probability"
                )
            try:
                normalized = {outcome: float(value[outcome]) for outcome in outcomes}
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    "Prediction revision probabilities must match Round 5 model_probability"
                ) from error
            if normalized != expected:
                raise ValueError(
                    "Prediction revision probabilities must match Round 5 model_probability"
                )
        for field in ("probability_model_version", "probability_calculation_version"):
            if not revision.get(field) or revision[field] != audit.get(field):
                raise ValueError(
                    f"Prediction revision {field} must match Round 5 audit"
                )

    def _save_prediction_with_production_evidence_in_transaction(
        self,
        connection: Connection,
        prediction: dict[str, Any],
        revision: dict[str, Any],
        round5_result: dict[str, Any],
        *,
        kickoff_at: Any,
        leakage_audit_id: str,
    ) -> dict[str, Any]:
        self._insert_prediction(connection, prediction, idempotent=True)
        stored_revision = self._insert_prediction_revision(connection, revision)
        revision_id = (
            f"{stored_revision['prediction_id']}:{stored_revision['revision_number']}"
        )
        market_snapshot_id = (
            f"round5-production:{hashlib.sha256(revision_id.encode()).hexdigest()[:32]}"
        )
        existing_market = connection.execute(
            text(
                "SELECT persisted_at FROM market_snapshots "
                "WHERE market_snapshot_id = :market_snapshot_id"
            ),
            {"market_snapshot_id": market_snapshot_id},
        ).mappings().first()
        if existing_market and not existing_market["persisted_at"]:
            raise ValueError("Existing production evidence has no persistence time")
        authoritative_kickoff = _parse_datetime(kickoff_at)
        if existing_market is None:
            fixture_query = "SELECT kickoff, payload FROM fixtures WHERE id = :fixture_id"
            if connection.dialect.name == "mysql":
                fixture_query += " FOR UPDATE"
            fixture_row = connection.execute(
                text(fixture_query),
                {"fixture_id": stored_revision["fixture_id"]},
            ).mappings().first()
            fixture_kickoff = _parse_datetime(
                fixture_row["kickoff"] if fixture_row else None
            )
            if fixture_kickoff is None:
                raise ValueError("Production fixture kickoff was not found")
            persisted_fixture = json.loads(fixture_row["payload"])
            if str(persisted_fixture.get("status") or "").casefold() != "scheduled":
                raise ValueError("Production fixture is no longer scheduled")
            if authoritative_kickoff != fixture_kickoff:
                raise ValueError(
                    "Production kickoff does not match the persisted fixture"
                )
            authoritative_kickoff = fixture_kickoff
        persisted_at = (
            str(existing_market["persisted_at"])
            if existing_market
            else datetime.now(UTC).isoformat()
        )
        market_snapshot = self._round5_production_record(
            connection,
            round5_result,
            stored_revision,
            kickoff_at=authoritative_kickoff,
            persisted_at=persisted_at,
            leakage_audit_id=leakage_audit_id,
        )
        stored_market_snapshot = self._insert_market_snapshot(
            connection,
            market_snapshot,
            persisted_at=persisted_at,
        )
        if existing_market is None:
            if datetime.now(UTC) >= authoritative_kickoff:
                raise ValueError(
                    "Production evidence transaction must complete before kickoff"
                )
        return {
            "revision": stored_revision,
            "market_snapshot": stored_market_snapshot,
        }

    def _save_prediction_with_revision_in_transaction(
        self,
        connection: Connection,
        prediction: dict[str, Any],
        revision: dict[str, Any],
    ) -> dict[str, Any]:
        self._insert_prediction(connection, prediction, idempotent=True)
        return self._insert_prediction_revision(connection, revision)

    def _with_revision_retry(
        self,
        writer: Callable[[Connection], dict[str, Any]],
        *,
        retry_on_conflict: bool,
    ) -> dict[str, Any]:
        """Retry only transaction races while allocating a scoped revision number.

        The retry starts a fresh transaction so the MAX(revision_number) query
        sees the competing commit.  Validation and immutable-content errors are
        deliberately not retried.
        """

        for attempt in range(self._REVISION_WRITE_ATTEMPTS):
            try:
                with self.engine.begin() as connection:
                    return writer(connection)
            except (IntegrityError, OperationalError) as error:
                if (
                    not retry_on_conflict
                    or attempt + 1 >= self._REVISION_WRITE_ATTEMPTS
                    or not self._is_retryable_revision_error(error)
                ):
                    raise
                time.sleep(self._REVISION_RETRY_DELAY_SECONDS * (attempt + 1))
        raise RuntimeError("revision write retry loop exited unexpectedly")

    @staticmethod
    def _is_retryable_revision_error(error: Exception) -> bool:
        message = str(error).casefold()
        if isinstance(error, IntegrityError):
            statement = str(getattr(error, "statement", "") or "").casefold()
            if not any(
                table in statement or table in message
                for table in ("predictions", "prediction_revisions", "market_snapshots")
            ):
                return False
            original = getattr(error, "orig", None)
            arguments = getattr(original, "args", ())
            if arguments and str(arguments[0]) == "1062":
                return True
            if getattr(original, "sqlite_errorcode", None) in {1555, 2067}:
                return True
            return "unique constraint failed" in message or (
                "duplicate entry" in message and "for key" in message
            )
        if isinstance(error, OperationalError):
            return any(
                token in message
                for token in ("database is locked", "deadlock", "lock wait timeout")
            )
        return False

    def _insert_prediction_revision(
        self,
        connection: Connection,
        revision: dict[str, Any],
    ) -> dict[str, Any]:
        prediction_id = str(revision.get("prediction_id") or revision.get("id") or "")
        fixture_id = str(revision.get("fixture_id") or revision.get("match_id") or "")
        model_version = str(revision.get("model_version") or "")
        model_key = str(
            revision.get("model_key")
            or (revision.get("ai") or {}).get("provider")
            or model_version.split(":", 1)[0]
            or "deepseek"
        )
        competition_id = str(revision.get("competition_id") or self.competition_id)
        prediction_cutoff_at = str(
            revision.get("prediction_cutoff_at")
            or revision.get("prediction_timestamp")
            or revision.get("created_at")
            or ""
        )
        feature_snapshot_id = str(
            revision.get("feature_snapshot_id")
            or (revision.get("feature_snapshot") or {}).get("snapshot_id")
            or (revision.get("feature_snapshot") or {}).get("id")
            or ""
        )
        feature_version = str(
            revision.get("feature_version")
            or (revision.get("feature_snapshot") or {}).get("feature_version")
            or ""
        )
        evidence_snapshot_id = str(revision.get("evidence_snapshot_id") or "")
        created_at = str(revision.get("created_at") or "")
        required = {
            "prediction_id": prediction_id,
            "fixture_id": fixture_id,
            "competition_id": competition_id,
            "model_key": model_key,
            "prediction_cutoff_at": prediction_cutoff_at,
            "model_version": model_version,
            "feature_version": feature_version,
            "feature_snapshot_id": feature_snapshot_id,
            "evidence_snapshot_id": evidence_snapshot_id,
            "created_at": created_at,
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ValueError(f"Prediction revision fields are required: {', '.join(missing)}")

        probabilities = revision.get("probabilities") or revision.get("model_probabilities") or {}
        expected_goals = revision.get("expected_goals") or {}
        probability_home = revision.get("probability_home", probabilities.get("home"))
        probability_draw = revision.get("probability_draw", probabilities.get("draw"))
        probability_away = revision.get("probability_away", probabilities.get("away"))
        if any(value is None for value in (probability_home, probability_draw, probability_away)):
            raise ValueError("Prediction revision probabilities are required")

        requested_revision_number = revision.get("revision_number")
        existing_for_prediction = connection.execute(
            text(
                "SELECT revision_number, payload FROM prediction_revisions "
                "WHERE prediction_id = :prediction_id ORDER BY revision_number DESC LIMIT 1"
            ),
            {"prediction_id": prediction_id},
        ).mappings().first()
        if requested_revision_number is None and existing_for_prediction:
            revision_number = int(existing_for_prediction["revision_number"])
        elif requested_revision_number is None:
            revision_number = int(
                connection.execute(
                    text(
                        "SELECT COALESCE(MAX(revision_number), 0) FROM prediction_revisions "
                        "WHERE competition_id = :competition_id AND fixture_id = :fixture_id "
                        "AND model_key = :model_key"
                    ),
                    {
                        "competition_id": competition_id,
                        "fixture_id": fixture_id,
                        "model_key": model_key,
                    },
                ).scalar()
                or 0
            ) + 1
        else:
            revision_number = int(requested_revision_number)
        if revision_number < 1:
            raise ValueError("Prediction revision_number must be positive")

        normalized = {
            **revision,
            "prediction_id": prediction_id,
            "fixture_id": fixture_id,
            "match_id": revision.get("match_id") or fixture_id,
            "revision_number": revision_number,
            "competition_id": competition_id,
            "model_key": model_key,
            "prediction_cutoff_at": prediction_cutoff_at,
            "model_version": model_version,
            "feature_version": feature_version,
            "feature_snapshot_id": feature_snapshot_id,
            "evidence_snapshot_id": evidence_snapshot_id,
            "probability_home": float(probability_home),
            "probability_draw": float(probability_draw),
            "probability_away": float(probability_away),
            "expected_home_goals": revision.get(
                "expected_home_goals", expected_goals.get("home")
            ),
            "expected_away_goals": revision.get(
                "expected_away_goals", expected_goals.get("away")
            ),
            "uncertainty": revision.get("uncertainty"),
            "data_quality": revision.get("data_quality", revision.get("data_completeness")),
            "model_agreement": revision.get("model_agreement"),
            "created_at": created_at,
        }
        self._require_complete_revision_audit_chain(connection, normalized)
        existing = connection.execute(
            text(
                "SELECT payload FROM prediction_revisions "
                "WHERE prediction_id = :prediction_id AND revision_number = :revision_number"
            ),
            {"prediction_id": prediction_id, "revision_number": revision_number},
        ).mappings().first()
        if existing:
            persisted = json.loads(existing["payload"])
            if persisted != normalized:
                raise ValueError(
                    f"Prediction revision {prediction_id}/{revision_number} is immutable"
                )
            return persisted

        values = {
            **normalized,
            "expected_home_goals": normalized["expected_home_goals"],
            "expected_away_goals": normalized["expected_away_goals"],
            "uncertainty": self._json_value(normalized["uncertainty"]),
            "data_quality": self._json_value(normalized["data_quality"]),
            "model_agreement": self._json_value(normalized["model_agreement"]),
            "payload": json.dumps(normalized, ensure_ascii=False),
        }
        connection.execute(
            text(
                "INSERT INTO prediction_revisions "
                "(prediction_id, revision_number, fixture_id, competition_id, model_key, prediction_cutoff_at, "
                "model_version, feature_version, feature_snapshot_id, evidence_snapshot_id, probability_home, "
                "probability_draw, probability_away, expected_home_goals, expected_away_goals, uncertainty, "
                "data_quality, model_agreement, created_at, payload) VALUES "
                "(:prediction_id, :revision_number, :fixture_id, :competition_id, :model_key, :prediction_cutoff_at, "
                ":model_version, :feature_version, :feature_snapshot_id, :evidence_snapshot_id, :probability_home, "
                ":probability_draw, :probability_away, :expected_home_goals, :expected_away_goals, :uncertainty, "
                ":data_quality, :model_agreement, :created_at, :payload)"
            ),
            values,
        )
        return normalized

    def _require_complete_revision_audit_chain(
        self,
        connection: Connection,
        revision: dict[str, Any],
    ) -> None:
        """Reject orphaned or unaudited Round 2 prediction revisions."""

        prediction_id = str(revision["prediction_id"])
        feature_snapshot_id = str(revision["feature_snapshot_id"])
        evidence_snapshot_id = str(revision["evidence_snapshot_id"])

        def load_payload(table: str, key: str, value: str) -> dict[str, Any] | None:
            row = connection.execute(
                text(f"SELECT payload FROM {table} WHERE {key} = :value"),
                {"value": value},
            ).mappings().first()
            return json.loads(row["payload"]) if row else None

        prediction = load_payload("predictions", "id", prediction_id)
        if prediction is None:
            raise ValueError(
                f"Prediction revision audit chain is incomplete: prediction {prediction_id} was not found"
            )
        feature_snapshot = load_payload(
            "feature_snapshots", "snapshot_id", feature_snapshot_id
        )
        if feature_snapshot is None:
            raise ValueError(
                "Prediction revision audit chain is incomplete: feature snapshot "
                f"{feature_snapshot_id} was not found"
            )
        evidence_snapshot = load_payload(
            "evidence_snapshots", "id", evidence_snapshot_id
        )
        if evidence_snapshot is None:
            raise ValueError(
                "Prediction revision audit chain is incomplete: evidence snapshot "
                f"{evidence_snapshot_id} was not found"
            )

        def require_equal(
            owner: str,
            field: str,
            actual: Any,
            expected: Any,
        ) -> None:
            if field == "prediction_cutoff_at":
                actual_at = _parse_datetime(actual)
                expected_at = _parse_datetime(expected)
                matches = (
                    actual_at is not None
                    and expected_at is not None
                    and actual_at == expected_at
                )
            else:
                matches = str(actual or "") == str(expected or "")
            if not matches:
                raise ValueError(
                    "Prediction revision audit chain identity mismatch: "
                    f"{owner}.{field}={actual!r}, revision.{field}={expected!r}"
                )

        prediction_identity = {
            "prediction_id": prediction.get("id"),
            "fixture_id": prediction.get("fixture_id") or prediction.get("match_id"),
            "competition_id": prediction.get("competition_id"),
            "model_key": prediction.get("model_key")
            or (prediction.get("ai") or {}).get("provider"),
            "prediction_cutoff_at": prediction.get("prediction_cutoff_at")
            or prediction.get("prediction_timestamp")
            or prediction.get("created_at"),
            "model_version": prediction.get("model_version"),
            "feature_version": prediction.get("feature_version"),
            "feature_snapshot_id": prediction.get("feature_snapshot_id"),
            "evidence_snapshot_id": prediction.get("evidence_snapshot_id"),
        }
        for field, actual in prediction_identity.items():
            require_equal("prediction", field, actual, revision.get(field))

        snapshot_identity = {
            "fixture_id": feature_snapshot.get("fixture_id")
            or feature_snapshot.get("match_id"),
            "prediction_cutoff_at": feature_snapshot.get("prediction_cutoff_at"),
            "feature_version": feature_snapshot.get("feature_version"),
            "feature_snapshot_id": feature_snapshot.get("snapshot_id")
            or feature_snapshot.get("id"),
            "evidence_snapshot_id": feature_snapshot.get("evidence_snapshot_id"),
        }
        for field, actual in snapshot_identity.items():
            require_equal("feature_snapshot", field, actual, revision.get(field))
        if bool(feature_snapshot.get("leakage_detected")):
            raise ValueError(
                "Prediction revision audit chain is invalid: feature snapshot declares leakage"
            )

        require_equal(
            "evidence_snapshot",
            "evidence_snapshot_id",
            evidence_snapshot.get("id") or evidence_snapshot.get("snapshot_id"),
            evidence_snapshot_id,
        )
        require_equal(
            "evidence_snapshot",
            "fixture_id",
            evidence_snapshot.get("fixture_id") or evidence_snapshot.get("match_id"),
            revision.get("fixture_id"),
        )

        # Re-run the canonical leakage checks instead of trusting a caller-
        # supplied PASS row.  The prediction insert is still uncommitted here,
        # so references are read from this transaction and exposed through a
        # small read-only adapter to avoid a second connection seeing stale
        # state.
        from .leakage_audit import LeakageAuditService

        class _AuditReferenceReader:
            def __init__(self, evidence: dict[str, Any], repository: "PredictionRepository") -> None:
                self._evidence = evidence
                self._repository = repository

            def evidence_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
                expected_id = self._evidence.get("id") or self._evidence.get("snapshot_id")
                return self._evidence if str(expected_id) == str(snapshot_id) else None

            def odds_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
                return self._repository.odds_snapshot(snapshot_id)

        re_audit = LeakageAuditService(
            _AuditReferenceReader(evidence_snapshot, self)  # type: ignore[arg-type]
        ).audit_feature_snapshot(
            feature_snapshot,
            prediction_id=prediction_id,
            persist=False,
            expected_prediction=prediction,
            expected_revision=revision,
        )
        if re_audit["status"] != "PASS":
            raise ValueError(
                "Prediction revision audit chain rejected by leakage re-audit"
            )

        audit_row = connection.execute(
            text(
                "SELECT payload FROM leakage_audits "
                "WHERE prediction_id = :prediction_id "
                "AND feature_snapshot_id = :feature_snapshot_id "
                "AND prediction_cutoff_at = :prediction_cutoff_at "
                "ORDER BY audited_at DESC, audit_id DESC LIMIT 1"
            ),
            {
                "prediction_id": prediction_id,
                "feature_snapshot_id": feature_snapshot_id,
                "prediction_cutoff_at": revision.get("prediction_cutoff_at"),
            },
        ).mappings().first()
        if audit_row is None:
            raise ValueError(
                "Prediction revision audit chain is incomplete: PASS leakage audit was not found"
            )
        audit = json.loads(audit_row["payload"])
        if str(audit.get("status") or "").upper() != "PASS":
            raise ValueError(
                "Prediction revision audit chain is invalid: latest leakage audit is not PASS"
            )
        require_equal(
            "leakage_audit",
            "prediction_id",
            audit.get("prediction_id"),
            prediction_id,
        )
        require_equal(
            "leakage_audit",
            "feature_snapshot_id",
            audit.get("feature_snapshot_id") or audit.get("snapshot_id"),
            feature_snapshot_id,
        )
        require_equal(
            "leakage_audit",
            "prediction_cutoff_at",
            audit.get("prediction_cutoff_at"),
            revision.get("prediction_cutoff_at"),
        )

    @staticmethod
    def _json_value(value: Any) -> str | None:
        return None if value is None else json.dumps(value, ensure_ascii=False)

    def prediction_revision(
        self,
        prediction_id: str,
        revision_number: int | None = None,
    ) -> dict[str, Any] | None:
        """Return a specific revision, or the latest one for a prediction ID."""

        clause = " AND revision_number = :revision_number" if revision_number is not None else ""
        parameters: dict[str, Any] = {"prediction_id": prediction_id}
        if revision_number is not None:
            parameters["revision_number"] = int(revision_number)
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT payload FROM prediction_revisions WHERE prediction_id = :prediction_id"
                    f"{clause} ORDER BY revision_number DESC LIMIT 1"
                ),
                parameters,
            ).mappings().first()
        return json.loads(row["payload"]) if row else None

    def prediction_revisions(
        self,
        prediction_id: str | None = None,
        fixture_id: str | None = None,
        model_key: str | None = None,
        competition_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List append-only revisions in deterministic scoped order."""

        clauses: list[str] = []
        parameters: dict[str, Any] = {}
        for column, value in (
            ("prediction_id", prediction_id),
            ("fixture_id", fixture_id),
            ("model_key", model_key),
            ("competition_id", competition_id),
        ):
            if value:
                clauses.append(f"{column} = :{column}")
                parameters[column] = value
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT payload FROM prediction_revisions{where} "
                    "ORDER BY competition_id, fixture_id, model_key, revision_number"
                ),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows]

    def save_leakage_audit(self, audit: dict[str, Any]) -> dict[str, Any]:
        """Append a leakage audit result without mutating prior audit evidence."""

        status = str(audit.get("status") or "").upper()
        if status not in {"PASS", "FAIL", "WARN"}:
            raise ValueError("Leakage audit status must be PASS, FAIL or WARN")
        prediction_id = str(audit.get("prediction_id") or "")
        if not prediction_id:
            raise ValueError("Leakage audit prediction_id is required")
        audit_id = str(audit.get("audit_id") or uuid.uuid4())
        audited_at = str(
            audit.get("audited_at")
            or audit.get("created_at")
            or datetime.now(UTC).replace(microsecond=0).isoformat()
        )
        violations = list(audit.get("violations") or [])
        normalized = {
            **audit,
            "audit_id": audit_id,
            "prediction_id": prediction_id,
            "status": status,
            "violations": violations,
            "features_checked": int(audit.get("features_checked") or 0),
            "features_passed": int(audit.get("features_passed") or 0),
            "features_failed": int(audit.get("features_failed") or 0),
            "audited_at": audited_at,
        }
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO leakage_audits "
                    "(audit_id, prediction_id, feature_snapshot_id, status, prediction_cutoff_at, violations, "
                    "features_checked, features_passed, features_failed, audited_at, payload) VALUES "
                    "(:audit_id, :prediction_id, :feature_snapshot_id, :status, :prediction_cutoff_at, :violations, "
                    ":features_checked, :features_passed, :features_failed, :audited_at, :payload)"
                ),
                {
                    **normalized,
                    "feature_snapshot_id": audit.get("feature_snapshot_id")
                    or audit.get("snapshot_id"),
                    "prediction_cutoff_at": audit.get("prediction_cutoff_at"),
                    "violations": json.dumps(violations, ensure_ascii=False),
                    "payload": json.dumps(normalized, ensure_ascii=False),
                },
            )
        return normalized

    def leakage_audit(self, audit_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT payload FROM leakage_audits WHERE audit_id = :audit_id"),
                {"audit_id": audit_id},
            ).mappings().first()
        return json.loads(row["payload"]) if row else None

    def leakage_audits(
        self,
        prediction_id: str | None = None,
        feature_snapshot_ids: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """List audits, optionally restricted to selected feature snapshots."""

        clauses: list[str] = []
        parameters: dict[str, Any] = {}
        if prediction_id:
            clauses.append("prediction_id = :prediction_id")
            parameters["prediction_id"] = prediction_id
        if feature_snapshot_ids is not None:
            snapshot_ids = sorted(
                {
                    str(snapshot_id)
                    for snapshot_id in feature_snapshot_ids
                    if snapshot_id not in (None, "")
                }
            )
            if not snapshot_ids:
                return []
            placeholders = []
            for index, snapshot_id in enumerate(snapshot_ids):
                parameter = f"feature_snapshot_id_{index}"
                placeholders.append(f":{parameter}")
                parameters[parameter] = snapshot_id
            clauses.append(f"feature_snapshot_id IN ({', '.join(placeholders)})")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT payload FROM leakage_audits{where} "
                    "ORDER BY audited_at ASC, audit_id ASC"
                ),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows]

    def reproduce_prediction(
        self,
        prediction_id: str,
        revision_number: int | None = None,
    ) -> dict[str, Any]:
        """Resolve the immutable inputs and model artifact for one prediction revision."""

        prediction = self.prediction(prediction_id)
        revision = self.prediction_revision(prediction_id, revision_number)
        source = revision or prediction or {}
        feature_snapshot_id = source.get("feature_snapshot_id") or (
            source.get("feature_snapshot") or {}
        ).get("snapshot_id")
        evidence_snapshot_id = source.get("evidence_snapshot_id")
        feature_snapshot = (
            self.feature_snapshot(str(feature_snapshot_id)) if feature_snapshot_id else None
        )
        evidence_snapshot = (
            self.evidence_snapshot(str(evidence_snapshot_id)) if evidence_snapshot_id else None
        )
        model_version = str(source.get("model_version") or "")
        model_key = str(
            source.get("model_key")
            or (source.get("ai") or {}).get("provider")
            or model_version.split(":", 1)[0]
            or ""
        )
        model_artifact = next(
            (
                item
                for item in self.model_registry(model_key=model_key)
                if str(item.get("model_version")) == model_version
            ),
            None,
        ) if model_key and model_version else None
        if (
            model_artifact is None
            and model_version.startswith("poisson-")
            and "+dc-fit-" in model_version
        ):
            fitted_version = model_version.rsplit("+", 1)[-1]
            model_artifact = next(
                (
                    item
                    for item in self.model_registry(model_key="dixon_coles")
                    if str(item.get("model_version")) == fitted_version
                ),
                None,
            )
        missing_references = []
        for name, value in (
            ("prediction", prediction),
            ("prediction_revision", revision),
            ("feature_snapshot", feature_snapshot),
            ("evidence_snapshot", evidence_snapshot),
        ):
            if value is None:
                missing_references.append(name)
        identity = {
            "match_id": source.get("match_id") or source.get("fixture_id"),
            "prediction_id": prediction_id,
            "prediction_revision": revision.get("revision_number") if revision else revision_number,
            "model_version": model_version or None,
            "feature_version": source.get("feature_version"),
            "feature_snapshot_id": feature_snapshot_id,
            "evidence_snapshot_id": evidence_snapshot_id,
        }
        for field in (
            "match_id",
            "prediction_revision",
            "model_version",
            "feature_version",
            "feature_snapshot_id",
            "evidence_snapshot_id",
        ):
            if identity.get(field) in (None, ""):
                missing_references.append(field)

        consistency_violations: list[dict[str, Any]] = []

        def require_equal(field: str, left: Any, right: Any, owners: str) -> None:
            if left in (None, "") or right in (None, ""):
                return
            if left != right:
                consistency_violations.append(
                    {"field": field, "owners": owners, "left": left, "right": right}
                )

        if prediction and revision:
            for field in (
                "fixture_id",
                "competition_id",
                "model_key",
                "model_version",
                "prediction_cutoff_at",
                "feature_version",
                "feature_snapshot_id",
                "evidence_snapshot_id",
            ):
                require_equal(field, prediction.get(field), revision.get(field), "prediction/revision")
            for outcome in ("home", "draw", "away"):
                require_equal(
                    f"probability_{outcome}",
                    (prediction.get("probabilities") or {}).get(outcome),
                    revision.get(f"probability_{outcome}"),
                    "prediction/revision",
                )
        if revision and feature_snapshot:
            require_equal(
                "feature_snapshot_id",
                revision.get("feature_snapshot_id"),
                feature_snapshot.get("snapshot_id") or feature_snapshot.get("feature_snapshot_id"),
                "revision/feature_snapshot",
            )
            require_equal(
                "prediction_cutoff_at",
                revision.get("prediction_cutoff_at"),
                feature_snapshot.get("prediction_cutoff_at"),
                "revision/feature_snapshot",
            )
            require_equal(
                "feature_version",
                revision.get("feature_version"),
                feature_snapshot.get("feature_version"),
                "revision/feature_snapshot",
            )
            require_equal(
                "evidence_snapshot_id",
                revision.get("evidence_snapshot_id"),
                feature_snapshot.get("evidence_snapshot_id"),
                "revision/feature_snapshot",
            )
        if revision and evidence_snapshot:
            require_equal(
                "fixture_id",
                revision.get("fixture_id"),
                evidence_snapshot.get("fixture_id"),
                "revision/evidence_snapshot",
            )
            cutoff_at = _parse_datetime(revision.get("prediction_cutoff_at"))
            evidence_at = _parse_datetime(
                evidence_snapshot.get("captured_at") or evidence_snapshot.get("created_at")
            )
            if cutoff_at and evidence_at and evidence_at > cutoff_at:
                consistency_violations.append(
                    {
                        "field": "captured_at",
                        "owners": "revision/evidence_snapshot",
                        "left": evidence_at.isoformat(),
                        "right": cutoff_at.isoformat(),
                    }
                )
        if revision and model_artifact:
            require_equal(
                "feature_version",
                revision.get("feature_version"),
                model_artifact.get("feature_version"),
                "revision/model_artifact",
            )

        model_input_features = {
            str(item.get("feature_name")): item.get("feature_value")
            for item in (feature_snapshot or {}).get("features") or []
            if str(item.get("feature_name") or "").startswith("model_input.")
            and item.get("status") == "available"
        }
        missing_references = list(dict.fromkeys(missing_references))
        reproducible = not missing_references and not consistency_violations
        return {
            "status": "PASS" if reproducible else "FAIL",
            "reproducible": reproducible,
            "identity": identity,
            "prediction": prediction,
            "revision": revision,
            "feature_snapshot": feature_snapshot,
            "evidence_snapshot": evidence_snapshot,
            "model_artifact": model_artifact,
            "artifact_status": "registered" if model_artifact else "not_registered",
            "missing_references": missing_references,
            "consistency_violations": consistency_violations,
            "model_input_features": model_input_features,
        }

    prediction_reproducibility_bundle = reproduce_prediction

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

    def evidence_snapshots(self, fixture_id: str | None = None) -> list[dict[str, Any]]:
        """List immutable evidence snapshots in capture order."""

        clauses = []
        parameters: dict[str, Any] = {}
        if fixture_id:
            clauses.append("fixture_id = :fixture_id")
            parameters["fixture_id"] = fixture_id
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT payload FROM evidence_snapshots"
                    f"{where} ORDER BY captured_at, created_at, id"
                ),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows]

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
                # Quote rows are read back in id order, which is not the
                # caller's order; compare content, not sequence.
                signature = lambda quote: json.dumps(quote, ensure_ascii=False, sort_keys=True)  # noqa: E731
                existing_quotes = sorted((json.loads(row["payload"]) for row in existing), key=signature)
                if (
                    existing_quotes != sorted(quotes, key=signature)
                    or existing[0]["fixture_id"] != snapshot["fixture_id"]
                    or existing[0]["captured_at"] != snapshot["captured_at"]
                    or existing[0]["source_updated_at"] != snapshot.get("source_updated_at")
                    # bookmaker 列存的是报价级值，与首个报价比较而不是快照级字段。
                    or existing[0]["bookmaker"] != next((quote.get("bookmaker") for quote in quotes if quote.get("bookmaker")), None)
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
        """List immutable odds captures, newest capture last.

        One query loads every quote row and groups by snapshot id — the
        previous per-snapshot round trip made this an N+1 scan (~2000
        queries per audit on the odds-heavy fixtures).
        """

        clauses = ["1 = 1"]
        parameters: dict[str, Any] = {}
        if fixture_id:
            clauses.append("fixture_id = :fixture_id")
            parameters["fixture_id"] = fixture_id
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT snapshot_id, fixture_id, captured_at, source_updated_at, bookmaker, source, payload "
                    f"FROM odds_snapshots WHERE {' AND '.join(clauses)} ORDER BY captured_at, snapshot_id, id"
                ),
                parameters,
            ).mappings().all()
        grouped: dict[str, list[Any]] = {}
        order: list[str] = []
        for row in rows:
            snapshot_id = row["snapshot_id"]
            if snapshot_id not in grouped:
                grouped[snapshot_id] = []
                order.append(snapshot_id)
            grouped[snapshot_id].append(row)
        snapshots: list[dict[str, Any]] = []
        for snapshot_id in order:
            group = grouped[snapshot_id]
            quotes = [json.loads(item["payload"]) for item in group]
            snapshots.append(
                {
                    "id": snapshot_id,
                    "fixture_id": group[0]["fixture_id"],
                    "captured_at": group[0]["captured_at"],
                    "source_updated_at": group[0]["source_updated_at"],
                    "bookmaker": group[0]["bookmaker"],
                    "source": group[0]["source"],
                    "quotes": quotes,
                    "payload": _odds_payload_from_quotes(quotes),
                }
            )
        return snapshots

    def save_historical_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Insert one immutable historical reconstruction."""

        required = ("snapshot_id", "canonical_fixture_id", "fixture_id", "as_of", "snapshot_version")
        if any(not snapshot.get(key) for key in required):
            raise ValueError("Historical snapshot identity fields are required")
        with self.engine.begin() as connection:
            existing = connection.execute(
                text("SELECT payload FROM historical_snapshots WHERE snapshot_id = :snapshot_id"),
                {"snapshot_id": snapshot["snapshot_id"]},
            ).mappings().first()
            if existing:
                if json.loads(existing["payload"]) != snapshot:
                    raise ValueError("Historical snapshot is immutable")
                return
            connection.execute(
                text(
                    "INSERT INTO historical_snapshots ("
                    "snapshot_id, canonical_fixture_id, fixture_id, as_of, snapshot_version, "
                    "dataset_version, evidence_snapshot_id, odds_snapshot_id, data_quality_score, "
                    "created_at, payload) VALUES ("
                    ":snapshot_id, :canonical_fixture_id, :fixture_id, :as_of, :snapshot_version, "
                    ":dataset_version, :evidence_snapshot_id, :odds_snapshot_id, :data_quality_score, "
                    ":created_at, :payload)"
                ),
                {
                    "snapshot_id": snapshot["snapshot_id"],
                    "canonical_fixture_id": snapshot["canonical_fixture_id"],
                    "fixture_id": snapshot["fixture_id"],
                    "as_of": snapshot["as_of"],
                    "snapshot_version": snapshot["snapshot_version"],
                    "dataset_version": snapshot.get("dataset_version"),
                    "evidence_snapshot_id": snapshot.get("evidence_snapshot_id"),
                    "odds_snapshot_id": snapshot.get("odds_snapshot_id"),
                    "data_quality_score": snapshot.get("data_quality_score"),
                    "created_at": snapshot.get("created_at") or datetime.now(UTC).isoformat(),
                    "payload": json.dumps(snapshot, ensure_ascii=False),
                },
            )

    def historical_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        """Return one immutable historical snapshot."""

        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT payload FROM historical_snapshots WHERE snapshot_id = :snapshot_id"),
                {"snapshot_id": snapshot_id},
            ).mappings().first()
        return json.loads(row["payload"]) if row else None

    def historical_snapshots(
        self,
        fixture_id: str | None = None,
        as_of: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """List immutable historical snapshots with bounded read-only paging."""

        clauses = []
        parameters: dict[str, Any] = {}
        if fixture_id:
            clauses.append("fixture_id = :fixture_id")
            parameters["fixture_id"] = fixture_id
        if as_of:
            clauses.append("as_of <= :as_of")
            parameters["as_of"] = as_of
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT payload FROM historical_snapshots"
                    f"{where} ORDER BY as_of, snapshot_id"
                ),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows[: max(1, min(int(limit), 500))]]

    def save_historical_prediction(self, prediction: dict[str, Any]) -> dict[str, Any]:
        """Insert one immutable P7.2 prediction outside the production chain."""

        required = (
            "prediction_id",
            "fixture_id",
            "canonical_fixture_id",
            "model_key",
            "model_version",
            "prediction_timestamp",
        )
        if any(not prediction.get(key) for key in required):
            raise ValueError("Historical prediction identity fields are required")
        payload = json.dumps(prediction, ensure_ascii=False)
        with self.engine.begin() as connection:
            existing = connection.execute(
                text("SELECT payload FROM historical_predictions WHERE prediction_id = :prediction_id"),
                {"prediction_id": prediction["prediction_id"]},
            ).mappings().first()
            if existing:
                stored = json.loads(existing["payload"])
                if stored != prediction:
                    raise ValueError("Historical prediction is immutable")
                return stored
            duplicate = connection.execute(
                text(
                    "SELECT payload FROM historical_predictions WHERE fixture_id = :fixture_id "
                    "AND model_key = :model_key AND model_version = :model_version "
                    "AND prediction_timestamp = :prediction_timestamp"
                ),
                {
                    "fixture_id": prediction["fixture_id"],
                    "model_key": prediction["model_key"],
                    "model_version": prediction["model_version"],
                    "prediction_timestamp": prediction["prediction_timestamp"],
                },
            ).mappings().first()
            if duplicate:
                return json.loads(duplicate["payload"])
            connection.execute(
                text(
                    "INSERT INTO historical_predictions ("
                    "prediction_id, fixture_id, canonical_fixture_id, model_key, model_version, "
                    "prediction_timestamp, evidence_snapshot_id, feature_snapshot_id, actual_outcome, "
                    "created_at, payload) VALUES ("
                    ":prediction_id, :fixture_id, :canonical_fixture_id, :model_key, :model_version, "
                    ":prediction_timestamp, :evidence_snapshot_id, :feature_snapshot_id, :actual_outcome, "
                    ":created_at, :payload)"
                ),
                {
                    "prediction_id": prediction["prediction_id"],
                    "fixture_id": prediction["fixture_id"],
                    "canonical_fixture_id": prediction["canonical_fixture_id"],
                    "model_key": prediction["model_key"],
                    "model_version": prediction["model_version"],
                    "prediction_timestamp": prediction["prediction_timestamp"],
                    "evidence_snapshot_id": prediction.get("evidence_snapshot_id"),
                    "feature_snapshot_id": prediction.get("feature_snapshot_id"),
                    "actual_outcome": prediction.get("actual_outcome"),
                    "created_at": prediction.get("created_at") or prediction["prediction_timestamp"],
                    "payload": payload,
                },
            )
        return prediction

    def historical_predictions(
        self,
        fixture_id: str | None = None,
        model_key: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """List immutable P7.2 predictions in deterministic time order."""

        clauses: list[str] = []
        parameters: dict[str, Any] = {}
        if fixture_id:
            clauses.append("fixture_id = :fixture_id")
            parameters["fixture_id"] = fixture_id
        if model_key:
            clauses.append("model_key = :model_key")
            parameters["model_key"] = model_key
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT payload FROM historical_predictions"
                    f"{where} ORDER BY prediction_timestamp, prediction_id"
                ),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows[: max(1, min(int(limit), 5000))]]

    def save_historical_backfill_run(self, run: dict[str, Any]) -> dict[str, Any]:
        """Persist one immutable P7.2 run summary."""

        required = ("run_id", "started_at", "status")
        if any(not run.get(key) for key in required):
            raise ValueError("Historical backfill run identity fields are required")
        with self.engine.begin() as connection:
            existing = connection.execute(
                text("SELECT payload FROM historical_backfill_runs WHERE run_id = :run_id"),
                {"run_id": run["run_id"]},
            ).mappings().first()
            if existing:
                stored = json.loads(existing["payload"])
                if stored != run:
                    raise ValueError("Historical backfill run is immutable")
                return stored
            connection.execute(
                text(
                    "INSERT INTO historical_backfill_runs ("
                    "run_id, started_at, finished_at, status, total_fixtures, eligible_fixtures, "
                    "excluded_fixtures, generated_predictions, leakage_violations, payload) VALUES ("
                    ":run_id, :started_at, :finished_at, :status, :total_fixtures, :eligible_fixtures, "
                    ":excluded_fixtures, :generated_predictions, :leakage_violations, :payload)"
                ),
                {
                    "run_id": run["run_id"],
                    "started_at": run["started_at"],
                    "finished_at": run.get("finished_at"),
                    "status": run["status"],
                    "total_fixtures": int(run.get("total_fixtures") or 0),
                    "eligible_fixtures": int(run.get("eligible_fixtures") or 0),
                    "excluded_fixtures": int(run.get("excluded_fixtures") or 0),
                    "generated_predictions": int(run.get("generated_predictions") or 0),
                    "leakage_violations": int(run.get("leakage_violations") or 0),
                    "payload": json.dumps(run, ensure_ascii=False),
                },
            )
        return run

    def historical_backfill_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        """List P7.2 run summaries newest first."""

        with self.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT payload FROM historical_backfill_runs ORDER BY started_at DESC, run_id DESC")
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows[: max(1, min(int(limit), 300))]]

    def save_raw_data_record(self, record: dict[str, Any]) -> None:
        """Insert one append-only raw source record."""

        required = ("record_id", "entity_type", "source", "source_record_id", "captured_at", "ingested_at")
        if any(not record.get(key) for key in required):
            raise ValueError("Raw data provenance fields are required")
        payload = record.get("payload") or {}
        computed_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        if record.get("payload_hash") and str(record["payload_hash"]) != computed_hash:
            raise ValueError("Raw data record is immutable: payload_hash does not match payload")
        payload_hash = computed_hash
        record = {**record, "payload_hash": payload_hash}
        with self.engine.begin() as connection:
            existing = connection.execute(
                text("SELECT source, source_record_id, payload_hash, payload FROM raw_data_records WHERE record_id = :record_id"),
                {"record_id": record["record_id"]},
            ).mappings().first()
            if existing:
                # Capture/ingest timestamps are observation metadata; the same
                # source payload remains one immutable version.
                if (
                    str(existing.get("source")) == str(record["source"])
                    and str(existing.get("source_record_id")) == str(record["source_record_id"])
                    and str(existing.get("payload_hash")) == str(payload_hash)
                ):
                    return
                if json.loads(existing["payload"]) != record:
                    raise ValueError("Raw data record is immutable")
                return
            duplicate = connection.execute(
                text(
                    "SELECT payload FROM raw_data_records WHERE source = :source "
                    "AND source_record_id = :source_record_id AND payload_hash = :payload_hash LIMIT 1"
                ),
                {
                    "source": record["source"],
                    "source_record_id": record["source_record_id"],
                    "payload_hash": payload_hash,
                },
            ).mappings().first()
            if duplicate:
                return
            connection.execute(
                text(
                    "INSERT INTO raw_data_records (record_id, entity_type, source, source_record_id, payload_hash, "
                    "captured_at, ingested_at, payload) VALUES ("
                    ":record_id, :entity_type, :source, :source_record_id, :payload_hash, :captured_at, :ingested_at, :payload)"
                ),
                {
                    "record_id": record["record_id"],
                    "entity_type": record["entity_type"],
                    "source": record["source"],
                    "source_record_id": record["source_record_id"],
                    "payload_hash": payload_hash,
                    "captured_at": record["captured_at"],
                    "ingested_at": record["ingested_at"],
                    "payload": json.dumps(record, ensure_ascii=False),
                },
            )

    def raw_data_records(
        self,
        entity_type: str | None = None,
        source: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """List raw source records without normalization or overwrite."""

        clauses = []
        parameters: dict[str, Any] = {}
        if entity_type:
            clauses.append("entity_type = :entity_type")
            parameters["entity_type"] = entity_type
        if source:
            clauses.append("source = :source")
            parameters["source"] = source
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT payload FROM raw_data_records"
                    f"{where} ORDER BY captured_at, record_id"
                ),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows[: max(1, min(int(limit), 1000))]]

    def save_data_sync_run(self, run: dict[str, Any]) -> None:
        """Persist one append-only data synchronization run."""

        required = ("run_id", "provider", "entity_type", "started_at", "status")
        if any(not run.get(key) for key in required):
            raise ValueError("Data sync run identity fields are required")
        with self.engine.begin() as connection:
            existing = connection.execute(
                text("SELECT payload FROM data_sync_runs WHERE run_id = :run_id"),
                {"run_id": run["run_id"]},
            ).mappings().first()
            if existing:
                if json.loads(existing["payload"]) != run:
                    raise ValueError("Data sync run is immutable")
                return
            connection.execute(
                text(
                    "INSERT INTO data_sync_runs (run_id, provider, league, entity_type, started_at, finished_at, "
                    "status, records_seen, records_inserted, records_updated, records_rejected, error_category, errors, payload) "
                    "VALUES (:run_id, :provider, :league, :entity_type, :started_at, :finished_at, :status, "
                    ":records_seen, :records_inserted, :records_updated, :records_rejected, :error_category, :errors, :payload)"
                ),
                {
                    "run_id": run["run_id"],
                    "provider": run["provider"],
                    "league": run.get("league"),
                    "entity_type": run["entity_type"],
                    "started_at": run["started_at"],
                    "finished_at": run.get("finished_at"),
                    "status": run["status"],
                    "records_seen": int(run.get("records_seen") or 0),
                    "records_inserted": int(run.get("records_inserted") or 0),
                    "records_updated": int(run.get("records_updated") or 0),
                    "records_rejected": int(run.get("records_rejected") or 0),
                    "error_category": run.get("error_category"),
                    "errors": json.dumps(run.get("errors") or [], ensure_ascii=False),
                    "payload": json.dumps(run, ensure_ascii=False),
                },
            )

    def update_data_sync_run(self, run_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """Finalize a sync run while preserving its original start record."""

        with self.engine.begin() as connection:
            row = connection.execute(
                text("SELECT payload FROM data_sync_runs WHERE run_id = :run_id"),
                {"run_id": run_id},
            ).mappings().first()
            if not row:
                return None
            payload = json.loads(row["payload"])
            payload.update(updates)
            connection.execute(
                text(
                    "UPDATE data_sync_runs SET finished_at = :finished_at, status = :status, records_seen = :records_seen, "
                    "records_inserted = :records_inserted, records_updated = :records_updated, records_rejected = :records_rejected, "
                    "error_category = :error_category, errors = :errors, payload = :payload WHERE run_id = :run_id"
                ),
                {
                    "run_id": run_id,
                    "finished_at": payload.get("finished_at"),
                    "status": payload.get("status"),
                    "records_seen": int(payload.get("records_seen") or 0),
                    "records_inserted": int(payload.get("records_inserted") or 0),
                    "records_updated": int(payload.get("records_updated") or 0),
                    "records_rejected": int(payload.get("records_rejected") or 0),
                    "error_category": payload.get("error_category"),
                    "errors": json.dumps(payload.get("errors") or [], ensure_ascii=False),
                    "payload": json.dumps(payload, ensure_ascii=False),
                },
            )
            return payload

    def data_sync_runs(
        self,
        provider: str | None = None,
        league: str | None = None,
        entity_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List synchronization runs newest first."""

        clauses = []
        parameters: dict[str, Any] = {}
        for column, value in (("provider", provider), ("league", league), ("entity_type", entity_type)):
            if value:
                clauses.append(f"{column} = :{column}")
                parameters[column] = value
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT payload FROM data_sync_runs" f"{where} ORDER BY started_at DESC, run_id DESC"),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows[: max(1, min(int(limit), 300))]]

    def save_provider_registry(self, item: dict[str, Any]) -> None:
        """Upsert provider capability metadata, which is configuration rather than history."""

        with self.engine.begin() as connection:
            values = {
                "provider": item["provider"],
                "capabilities": json.dumps(item.get("capabilities") or {}, ensure_ascii=False),
                "source_priority": json.dumps(item.get("source_priority") or {}, ensure_ascii=False),
                "updated_at": item.get("updated_at") or datetime.now(UTC).isoformat(),
                "payload": json.dumps(item, ensure_ascii=False),
            }
            existing = connection.execute(
                text("SELECT provider FROM provider_registry WHERE provider = :provider"),
                {"provider": values["provider"]},
            ).first()
            if existing:
                connection.execute(
                    text("UPDATE provider_registry SET capabilities = :capabilities, source_priority = :source_priority, updated_at = :updated_at, payload = :payload WHERE provider = :provider"),
                    values,
                )
            else:
                connection.execute(
                    text("INSERT INTO provider_registry (provider, capabilities, source_priority, updated_at, payload) VALUES (:provider, :capabilities, :source_priority, :updated_at, :payload)"),
                    values,
                )

    def provider_registry(self) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(text("SELECT payload FROM provider_registry ORDER BY provider")).mappings().all()
        return [json.loads(row["payload"]) for row in rows]

    def save_team_identity(self, item: dict[str, Any]) -> None:
        """Upsert one source-to-canonical team mapping."""

        with self.engine.begin() as connection:
            values = {
                **item,
                "season": str(item.get("season") or "unknown"),
                "conflict": bool(item.get("conflict")),
                "payload": json.dumps(item, ensure_ascii=False),
            }
            key = {field: values[field] for field in ("source", "source_team_id", "league", "season")}
            existing = connection.execute(
                text("SELECT source FROM team_identity_map WHERE source = :source AND source_team_id = :source_team_id AND league = :league AND season = :season"),
                key,
            ).first()
            if existing:
                connection.execute(
                    text("UPDATE team_identity_map SET canonical_team_id = :canonical_team_id, normalized_name = :normalized_name, display_name = :display_name, identity_status = :identity_status, conflict = :conflict, payload = :payload WHERE source = :source AND source_team_id = :source_team_id AND league = :league AND season = :season"),
                    values,
                )
            else:
                connection.execute(
                    text("INSERT INTO team_identity_map (canonical_team_id, league, season, source, source_team_id, normalized_name, display_name, identity_status, conflict, payload) VALUES (:canonical_team_id, :league, :season, :source, :source_team_id, :normalized_name, :display_name, :identity_status, :conflict, :payload)"),
                    values,
                )

    def save_fixture_identity(self, item: dict[str, Any]) -> None:
        """Upsert one source-to-canonical fixture mapping."""

        with self.engine.begin() as connection:
            values = {
                **item,
                "season": str(item.get("season") or "unknown"),
                "conflict": bool(item.get("conflict")),
                "payload": json.dumps(item, ensure_ascii=False),
            }
            key = {field: values[field] for field in ("source", "source_fixture_id", "league", "season")}
            existing = connection.execute(
                text("SELECT source FROM fixture_identity_map WHERE source = :source AND source_fixture_id = :source_fixture_id AND league = :league AND season = :season"),
                key,
            ).first()
            if existing:
                connection.execute(
                    text("UPDATE fixture_identity_map SET canonical_fixture_id = :canonical_fixture_id, kickoff_at = :kickoff_at, identity_status = :identity_status, conflict = :conflict, payload = :payload WHERE source = :source AND source_fixture_id = :source_fixture_id AND league = :league AND season = :season"),
                    values,
                )
            else:
                connection.execute(
                    text("INSERT INTO fixture_identity_map (canonical_fixture_id, league, season, source, source_fixture_id, kickoff_at, identity_status, conflict, payload) VALUES (:canonical_fixture_id, :league, :season, :source, :source_fixture_id, :kickoff_at, :identity_status, :conflict, :payload)"),
                    values,
                )

    def team_identities(self, league: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        clauses = " WHERE league = :league" if league else ""
        parameters = {"league": league} if league else {}
        with self.engine.connect() as connection:
            rows = connection.execute(text("SELECT payload FROM team_identity_map" f"{clauses} ORDER BY league, normalized_name"), parameters).mappings().all()
        return [json.loads(row["payload"]) for row in rows[: max(1, min(int(limit), 1000))]]

    def fixture_identities(self, league: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        clauses = " WHERE league = :league" if league else ""
        parameters = {"league": league} if league else {}
        with self.engine.connect() as connection:
            rows = connection.execute(text("SELECT payload FROM fixture_identity_map" f"{clauses} ORDER BY league, kickoff_at"), parameters).mappings().all()
        return [json.loads(row["payload"]) for row in rows[: max(1, min(int(limit), 1000))]]

    def save_competition_registry(self, items: list[dict[str, Any]]) -> None:
        """Persist the P9 competition registry snapshot, which is configuration."""

        with self.engine.begin() as connection:
            for item in items:
                values = {
                    "competition_key": item["key"],
                    "competition_type": item["competition_type"],
                    "capabilities": json.dumps(item.get("capabilities") or {}, ensure_ascii=False),
                    "updated_at": item.get("updated_at") or datetime.now(UTC).isoformat(),
                    "payload": json.dumps(item, ensure_ascii=False),
                }
                existing = connection.execute(
                    text("SELECT competition_key FROM competition_registry WHERE competition_key = :competition_key"),
                    {"competition_key": values["competition_key"]},
                ).first()
                if existing:
                    connection.execute(
                        text("UPDATE competition_registry SET competition_type = :competition_type, capabilities = :capabilities, updated_at = :updated_at, payload = :payload WHERE competition_key = :competition_key"),
                        values,
                    )
                else:
                    connection.execute(
                        text("INSERT INTO competition_registry (competition_key, competition_type, capabilities, updated_at, payload) VALUES (:competition_key, :competition_type, :capabilities, :updated_at, :payload)"),
                        values,
                    )

    def competition_registry(self) -> list[dict[str, Any]]:
        """Return the persisted competition registry rows."""

        with self.engine.connect() as connection:
            rows = connection.execute(text("SELECT payload FROM competition_registry ORDER BY competition_key")).mappings().all()
        return [json.loads(row["payload"]) for row in rows]

    def save_fixture_conflict(self, item: dict[str, Any]) -> None:
        """Upsert one cross-source fixture conflict keyed by stable conflict id."""

        required = ("conflict_id", "canonical_fixture_id", "conflict_type", "source_a", "source_b")
        if any(not item.get(key) for key in required):
            raise ValueError("Fixture conflict identity fields are required")
        with self.engine.begin() as connection:
            values = {
                **item,
                "resolved": bool(item.get("resolved")),
                "detected_at": item.get("detected_at") or datetime.now(UTC).replace(microsecond=0).isoformat(),
                "payload": json.dumps(item, ensure_ascii=False),
            }
            for field in ("value_a", "value_b"):
                if not isinstance(values.get(field), (str, type(None))):
                    values[field] = json.dumps(values[field], ensure_ascii=False, sort_keys=True)
            existing = connection.execute(
                text("SELECT conflict_id FROM fixture_conflicts WHERE conflict_id = :conflict_id"),
                {"conflict_id": values["conflict_id"]},
            ).first()
            if existing:
                connection.execute(
                    text("UPDATE fixture_conflicts SET value_a = :value_a, value_b = :value_b, resolved = :resolved, detected_at = :detected_at, payload = :payload WHERE conflict_id = :conflict_id"),
                    values,
                )
            else:
                connection.execute(
                    text("INSERT INTO fixture_conflicts (conflict_id, canonical_fixture_id, competition_key, conflict_type, source_a, source_b, value_a, value_b, resolution, resolved, detected_at, payload) VALUES (:conflict_id, :canonical_fixture_id, :competition_key, :conflict_type, :source_a, :source_b, :value_a, :value_b, :resolution, :resolved, :detected_at, :payload)"),
                    values,
                )

    def fixture_conflicts(self, limit: int = 500, resolved: bool | None = None) -> list[dict[str, Any]]:
        """List recorded cross-source fixture conflicts newest first."""

        clause = " WHERE resolved = :resolved" if resolved is not None else ""
        parameters: dict[str, Any] = {"resolved": resolved} if resolved is not None else {}
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT payload FROM fixture_conflicts" f"{clause} ORDER BY detected_at DESC, conflict_id DESC"),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows[: max(1, min(int(limit), 1000))]]

    def save_model_registry(self, item: dict[str, Any]) -> None:
        """Upsert one model artifact; its artifact hash is immutable."""

        required = ("model_key", "model_version", "artifact_hash")
        if any(not item.get(key) for key in required):
            raise ValueError("Model registry identity fields are required")
        with self.engine.begin() as connection:
            existing = connection.execute(
                text("SELECT artifact_hash FROM model_registry WHERE model_key = :model_key AND model_version = :model_version"),
                {"model_key": item["model_key"], "model_version": item["model_version"]},
            ).first()
            if existing and existing[0] != item["artifact_hash"]:
                raise ValueError(f"Model {item['model_key']}:{item['model_version']} is immutable")
            values = {
                **item,
                "payload": json.dumps(item, ensure_ascii=False),
            }
            if existing:
                connection.execute(
                    text("UPDATE model_registry SET status = :status, payload = :payload WHERE model_key = :model_key AND model_version = :model_version"),
                    values,
                )
            else:
                connection.execute(
                    text(
                        "INSERT INTO model_registry (model_key, model_version, status, competition_scope, feature_version, "
                        "dataset_fingerprint, training_cutoff, calibration_version, artifact_hash, created_at, payload) "
                        "VALUES (:model_key, :model_version, :status, :competition_scope, :feature_version, "
                        ":dataset_fingerprint, :training_cutoff, :calibration_version, :artifact_hash, :created_at, :payload)"
                    ),
                    values,
                )

    def model_registry(self, model_key: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        """List model registry records, newest version first."""

        clauses = []
        parameters: dict[str, Any] = {}
        for column, value in (("model_key", model_key), ("status", status)):
            if value:
                clauses.append(f"{column} = :{column}")
                parameters[column] = value
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT payload FROM model_registry" f"{where} ORDER BY model_key, created_at DESC"),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows]

    def _round5_production_record(
        self,
        connection: Connection,
        round5_result: dict[str, Any],
        revision: dict[str, Any],
        *,
        kickoff_at: Any,
        persisted_at: str,
        leakage_audit_id: str,
    ) -> dict[str, Any]:
        """Bind a deterministic Round 5 result to its committed revision."""

        from .production_evidence import (
            PRODUCTION_EVIDENCE_KIND,
            PRODUCTION_EVIDENCE_VERSION,
            validate_production_evidence,
        )

        raw_record = round5_result.get("market_snapshot")
        raw_audit = round5_result.get("round5_probability_audit")
        if not isinstance(raw_record, dict) or not isinstance(raw_audit, dict):
            raise ValueError("Round 5 production result is incomplete")
        fixture_id = str(revision.get("fixture_id") or "")
        feature_snapshot_id = str(revision.get("feature_snapshot_id") or "")
        if str(raw_record.get("fixture_id") or "") != fixture_id:
            raise ValueError("Round 5 fixture does not match prediction revision")
        if str(raw_audit.get("feature_snapshot_id") or "") != feature_snapshot_id:
            raise ValueError("Round 5 feature snapshot does not match prediction revision")

        cutoff = _parse_datetime(revision.get("prediction_cutoff_at"))
        kickoff = _parse_datetime(kickoff_at)
        persisted = _parse_datetime(persisted_at)
        if cutoff is None or kickoff is None or persisted is None:
            raise ValueError("Production evidence timestamps must be valid")
        if cutoff >= kickoff:
            raise ValueError("Prediction cutoff must be before kickoff")
        if persisted < cutoff or persisted >= kickoff:
            raise ValueError("Production persistence time must be between cutoff and kickoff")

        feature_row = connection.execute(
            text("SELECT payload FROM feature_snapshots WHERE snapshot_id = :snapshot_id"),
            {"snapshot_id": feature_snapshot_id},
        ).mappings().first()
        if feature_row is None:
            raise ValueError("Production feature snapshot was not found")
        feature_snapshot = json.loads(feature_row["payload"])

        leakage_row = connection.execute(
            text("SELECT payload FROM leakage_audits WHERE audit_id = :audit_id"),
            {"audit_id": leakage_audit_id},
        ).mappings().first()
        if leakage_row is None:
            raise ValueError("Production leakage audit was not found")
        leakage_audit = json.loads(leakage_row["payload"])
        if str(leakage_audit.get("prediction_id") or "") != str(revision.get("prediction_id") or ""):
            raise ValueError("Leakage audit does not belong to prediction revision")

        source_odds_snapshot_ids = [
            str(value)
            for value in raw_audit.get("source_odds_snapshot_ids") or []
            if value not in (None, "")
        ]
        odds_snapshots = [
            self._odds_snapshot_in_connection(connection, snapshot_id)
            for snapshot_id in source_odds_snapshot_ids
        ]
        if any(snapshot is None for snapshot in odds_snapshots):
            raise ValueError("Production odds snapshot was not found")

        revision_number = int(revision["revision_number"])
        prediction_id = str(revision["prediction_id"])
        revision_id = f"{prediction_id}:{revision_number}"
        audit = {
            **raw_audit,
            "prediction_id": prediction_id,
            "prediction_revision_number": revision_number,
            "prediction_revision_id": revision_id,
            "model_key": revision.get("model_key"),
            "serving_model_version": revision.get("model_version"),
            "kickoff_at": kickoff.isoformat(),
            "persisted_at": persisted.isoformat(),
            "leakage_audit_id": leakage_audit_id,
            "production_evidence_version": PRODUCTION_EVIDENCE_VERSION,
            "evidence_kind": PRODUCTION_EVIDENCE_KIND,
            "production_evidence_valid": True,
        }
        audit.pop("market_snapshot_id", None)
        market_prior = round5_result.get("market_prior_detail")
        if not isinstance(market_prior, dict):
            market_prior = (raw_record.get("payload") or {}).get("market_prior")
        market_snapshot_id = (
            f"round5-production:{hashlib.sha256(revision_id.encode()).hexdigest()[:32]}"
        )
        audit["market_snapshot_id"] = market_snapshot_id
        payload = {
            "snapshot_type": "round5_probability_audit",
            "audit": audit,
            "market_prior": market_prior,
        }
        record = {
            **raw_record,
            "market_snapshot_id": market_snapshot_id,
            "fixture_id": fixture_id,
            "prediction_revision_id": revision_id,
            "persisted_at": persisted.isoformat(),
            "payload": payload,
        }
        normalized = validate_production_evidence(
            payload,
            feature_snapshot=feature_snapshot,
            odds_snapshots=[snapshot for snapshot in odds_snapshots if snapshot is not None],
            leakage_audit=leakage_audit,
            replay=False,
        )
        audit.update(normalized)
        return record

    @staticmethod
    def _odds_snapshot_in_connection(
        connection: Connection,
        snapshot_id: str,
    ) -> dict[str, Any] | None:
        rows = connection.execute(
            text(
                "SELECT snapshot_id, fixture_id, captured_at, source_updated_at, bookmaker, source, payload "
                "FROM odds_snapshots WHERE snapshot_id = :snapshot_id ORDER BY id"
            ),
            {"snapshot_id": snapshot_id},
        ).mappings().all()
        if not rows:
            return None
        return {
            "id": snapshot_id,
            "fixture_id": rows[0]["fixture_id"],
            "captured_at": rows[0]["captured_at"],
            "source_updated_at": rows[0]["source_updated_at"],
            "bookmaker": rows[0]["bookmaker"],
            "source": rows[0]["source"],
            "quotes": [json.loads(row["payload"]) for row in rows],
        }

    def save_market_snapshot(self, item: dict[str, Any]) -> None:
        """Persist a research/legacy snapshot without production provenance."""

        if item.get("persisted_at") not in (None, ""):
            raise ValueError(
                "persisted_at is assigned only by the atomic production evidence writer"
            )
        try:
            with self.engine.begin() as connection:
                self._insert_market_snapshot(connection, item, persisted_at=None)
        except IntegrityError as error:
            # A concurrent identical capture may win between SELECT and INSERT.
            # Re-read after rollback so identical content remains idempotent.
            with self.engine.connect() as connection:
                existing = connection.execute(
                    text(
                        "SELECT persisted_at, payload FROM market_snapshots "
                        "WHERE market_snapshot_id = :market_snapshot_id"
                    ),
                    {"market_snapshot_id": item.get("market_snapshot_id")},
                ).mappings().first()
            if not existing:
                raise
            if self._market_snapshot_identity(json.loads(existing["payload"])) != self._market_snapshot_identity(item):
                raise ValueError("Market snapshot is immutable") from error

    def _insert_market_snapshot(
        self,
        connection: Connection,
        item: dict[str, Any],
        *,
        persisted_at: str | None,
    ) -> dict[str, Any]:
        required = ("market_snapshot_id", "fixture_id", "market", "captured_at")
        if any(not item.get(key) for key in required):
            raise ValueError("Market snapshot identity fields are required")
        normalized = {**item, "persisted_at": persisted_at} if persisted_at else dict(item)
        existing = connection.execute(
            text(
                "SELECT persisted_at, payload FROM market_snapshots "
                "WHERE market_snapshot_id = :market_snapshot_id"
            ),
            {"market_snapshot_id": normalized["market_snapshot_id"]},
        ).mappings().first()
        if existing:
            stored = json.loads(existing["payload"])
            if self._market_snapshot_identity(stored) != self._market_snapshot_identity(normalized):
                raise ValueError("Market snapshot is immutable")
            stored["persisted_at"] = existing["persisted_at"]
            return stored
        connection.execute(
            text(
                "INSERT INTO market_snapshots "
                "(market_snapshot_id, fixture_id, market, captured_at, persisted_at, overround, payload) "
                "VALUES (:market_snapshot_id, :fixture_id, :market, :captured_at, :persisted_at, :overround, :payload)"
            ),
            {
                "market_snapshot_id": normalized["market_snapshot_id"],
                "fixture_id": normalized["fixture_id"],
                "market": normalized["market"],
                "captured_at": normalized["captured_at"],
                "persisted_at": persisted_at,
                "overround": normalized.get("overround"),
                "payload": json.dumps(normalized, ensure_ascii=False),
            },
        )
        return normalized

    @staticmethod
    def _market_snapshot_identity(item: dict[str, Any]) -> dict[str, Any]:
        """Compare immutable content while excluding the physical write time."""

        identity = dict(item)
        identity.pop("persisted_at", None)
        payload = identity.get("payload")
        if isinstance(payload, dict):
            payload = json.loads(json.dumps(payload, ensure_ascii=False))
            audit = payload.get("audit")
            if isinstance(audit, dict):
                audit.pop("persisted_at", None)
                audit.pop("production_persisted_at", None)
            identity["payload"] = payload
        return identity

    def market_snapshots(self, fixture_id: str) -> list[dict[str, Any]]:
        """List persisted market snapshots for one fixture, oldest capture first."""

        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT persisted_at, payload FROM market_snapshots "
                    "WHERE fixture_id = :fixture_id ORDER BY captured_at, market_snapshot_id"
                ),
                {"fixture_id": fixture_id},
            ).mappings().all()
        result = []
        for row in rows:
            item = json.loads(row["payload"])
            item["persisted_at"] = row["persisted_at"]
            result.append(item)
        return result

    def save_research_run(self, run: dict[str, Any]) -> None:
        """Insert one content-addressed research run; duplicates are ignored."""

        required = ("run_id", "status")
        if any(not run.get(key) for key in required):
            raise ValueError("Research run identity fields are required")
        with self.engine.begin() as connection:
            existing = connection.execute(
                text("SELECT payload FROM research_runs WHERE run_id = :run_id"),
                {"run_id": run["run_id"]},
            ).mappings().first()
            if existing:
                stored = json.loads(existing["payload"])
                if stored.get("status") != run["status"]:
                    raise ValueError("Research run is immutable")
                return
            connection.execute(
                text("INSERT INTO research_runs (run_id, status, job_id, created_at, payload) VALUES (:run_id, :status, :job_id, :created_at, :payload)"),
                {
                    "run_id": run["run_id"],
                    "status": run["status"],
                    "job_id": run.get("job_id"),
                    "created_at": run.get("created_at") or datetime.now(UTC).isoformat(),
                    "payload": json.dumps(run, ensure_ascii=False),
                },
            )

    def research_runs(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """List research runs newest first."""

        where = " WHERE status = :status" if status else ""
        parameters: dict[str, Any] = {"status": status} if status else {}
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT payload FROM research_runs" f"{where} ORDER BY created_at DESC, run_id DESC"),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows[: max(1, min(int(limit), 500))]]

    def research_run(self, run_id: str) -> dict[str, Any] | None:
        """Return one research run by id."""

        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT payload FROM research_runs WHERE run_id = :run_id"),
                {"run_id": run_id},
            ).mappings().first()
        return json.loads(row["payload"]) if row else None

    def upsert_fixture(self, fixture: dict[str, Any], synced_at: str | None = None) -> None:
        """Upsert one fixture without replacing another historical date window."""

        synced_at = synced_at or datetime.now(UTC).replace(microsecond=0).isoformat()
        with self.engine.begin() as connection:
            existing = connection.execute(text("SELECT payload FROM fixtures WHERE id = :id"), {"id": fixture["id"]}).mappings().first()
            if existing:
                previous = json.loads(existing["payload"])
                for field in ("evidence", "evidence_synced_at", "lineup_confirmed"):
                    if field in previous and field not in fixture:
                        fixture[field] = previous[field]
                connection.execute(
                    text("UPDATE fixtures SET provider_id = :provider_id, league_key = :league_key, fixture_date = :fixture_date, kickoff = :kickoff, payload = :payload, synced_at = :synced_at WHERE id = :id"),
                    {"id": fixture["id"], "provider_id": fixture.get("provider_id"), "league_key": fixture["league_key"], "fixture_date": fixture["fixture_date"], "kickoff": fixture["kickoff"], "payload": json.dumps(fixture, ensure_ascii=False), "synced_at": synced_at},
                )
            else:
                connection.execute(
                    text("INSERT INTO fixtures (id, provider_id, league_key, fixture_date, kickoff, payload, synced_at) VALUES (:id, :provider_id, :league_key, :fixture_date, :kickoff, :payload, :synced_at)"),
                    {"id": fixture["id"], "provider_id": fixture.get("provider_id"), "league_key": fixture["league_key"], "fixture_date": fixture["fixture_date"], "kickoff": fixture["kickoff"], "payload": json.dumps(fixture, ensure_ascii=False), "synced_at": synced_at},
                )
        self._fixture_revision += 1

    def fixture_revision(self) -> int:
        """Return the in-process revision for invalidating read caches."""

        return self._fixture_revision

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
            and not str(item.get("phase") or "").casefold().startswith("live")
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
            if str(item.get("phase") or "").casefold().startswith("live"):
                continue
            key = str(item.get("model_key") or (item.get("ai") or {}).get("provider") or "deepseek")
            groups.setdefault(key, []).append(item)
        return [
            max(group, key=lambda item: (str(item.get("created_at") or ""), str(item["id"])))
            for _, group in sorted(groups.items())
        ]

    def fixture_ids_with_current_predictions(
        self,
        prompt_version: str,
        competition_id: str | None = None,
    ) -> set[str]:
        """Return fixtures with at least one prediction on the active prompt contract."""

        clauses = ["prompt_version = :prompt_version", "LOWER(phase) NOT LIKE 'live%'"]
        parameters: dict[str, Any] = {"prompt_version": prompt_version}
        if competition_id:
            clauses.append("competition_id = :competition_id")
            parameters["competition_id"] = competition_id
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT DISTINCT fixture_id FROM predictions WHERE {' AND '.join(clauses)}"
                ),
                parameters,
            ).mappings().all()
        return {str(row["fixture_id"]) for row in rows}

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

        clauses: list[str] = ["LOWER(p.phase) NOT LIKE 'live%'"]
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
        """Report superseded rows that are protected as permanent audit history."""

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
        """Preserve the prediction audit chain; operational cleanup lives elsewhere."""

        with self.engine.connect() as connection:
            plan = self._prediction_retention_plan(
                connection,
                prompt_version,
                competition_id,
                fixture_id,
                model_key,
            )
        return {
            **self._prediction_retention_summary(plan, prompt_version),
            "balances": [],
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
        parameters: dict[str, Any] = {}
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
        protected_revision_rows = [
            row
            for row in connection.execute(
                text("SELECT prediction_id, feature_snapshot_id FROM prediction_revisions")
            ).mappings().all()
            if str(row["prediction_id"]) in prediction_ids
        ]
        revision_count = len(protected_revision_rows)
        revision_snapshot_ids = {
            str(row["feature_snapshot_id"])
            for row in protected_revision_rows
            if row["feature_snapshot_id"] is not None
        }
        audit_count = sum(
            1
            for row in connection.execute(
                text("SELECT prediction_id FROM leakage_audits")
            ).mappings().all()
            if str(row["prediction_id"]) in prediction_ids
        )
        feature_snapshot_count = 0
        for row in connection.execute(
            text("SELECT prediction_id, payload FROM feature_snapshots")
        ).mappings().all():
            linked_prediction_id = row["prediction_id"]
            if linked_prediction_id is None:
                try:
                    linked_prediction_id = json.loads(row["payload"]).get("prediction_id")
                except (TypeError, json.JSONDecodeError):
                    linked_prediction_id = None
            payload = json.loads(row["payload"])
            snapshot_id = payload.get("snapshot_id") or payload.get("id")
            if (
                linked_prediction_id is not None
                and str(linked_prediction_id) in prediction_ids
            ) or (snapshot_id is not None and str(snapshot_id) in revision_snapshot_ids):
                feature_snapshot_count += 1
        protected_counts = {
            "predictions": len(prediction_ids),
            "bets": len(bet_ids),
            "fixture_settlements": settlement_count,
            "bankroll_transactions": transaction_count,
            "evidence_snapshots": len(snapshot_ids),
            "feature_snapshots": feature_snapshot_count,
            "prediction_revisions": revision_count,
            "leakage_audits": audit_count,
        }
        return {
            "prediction_ids": set(),
            "bet_ids": set(),
            "snapshot_ids": set(),
            "affected_accounts": [],
            "counts": {key: 0 for key in protected_counts},
            "protected_counts": protected_counts,
        }

    @staticmethod
    def _prediction_retention_summary(plan: dict[str, Any], prompt_version: str) -> dict[str, Any]:
        counts = dict(plan["counts"])
        protected_counts = dict(plan.get("protected_counts") or {})
        return {
            "prompt_version": prompt_version,
            "delete_counts": counts,
            "protected_counts": protected_counts,
            "history_count": protected_counts.get("predictions", 0),
            "retention_status": "audit_chain_protected",
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
            window_rows = connection.execute(
                text("SELECT id, payload FROM fixtures WHERE fixture_date BETWEEN :start_date AND :end_date"),
                {"start_date": start_date, "end_date": end_date},
            ).mappings().all()
            protected_fixtures = []
            for row in window_rows:
                previous = json.loads(row["payload"])
                source = previous.get("source")
                if (
                    source == "dongqiudi"
                    or (previous.get("external_ids") or {}).get("dongqiudi")
                    # football-data 历史库行不参与赛程窗口替换，防止被每日同步清掉。
                    or source == "football-data"
                ):
                    protected_fixtures.append(previous)
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
                    for field in ("evidence", "evidence_synced_at", "lineup_confirmed", "dongqiudi", "dongqiudi_sync", "free_team_data", "free_team_data_synced_at"):
                        if field in previous:
                            fixture[field] = previous[field]
                    fixture["external_ids"] = {**(previous.get("external_ids") or {}), **(fixture.get("external_ids") or {})}
            for protected in protected_fixtures:
                if not any(item["id"] == protected["id"] for item in unique_fixtures):
                    unique_fixtures.append(protected)
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
        self._fixture_revision += 1

    def list_fixtures(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        league_key: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """List cached fixtures ordered by kickoff.

        The unfiltered full scan (every row's payload parsed) is cached per
        fixture revision; filtered windows keep their indexed SQL path.
        """

        if start_date is None and end_date is None and league_key is None and limit is None:
            cached = self._fixtures_cache
            if cached is not None and cached[0] == self._fixture_revision:
                return list(cached[1])
            rows = self._scan_fixtures(None, None, None, None)
            self._fixtures_cache = (self._fixture_revision, rows)
            return list(rows)
        return self._scan_fixtures(start_date, end_date, league_key, limit)

    def _scan_fixtures(
        self,
        start_date: str | None,
        end_date: str | None,
        league_key: str | None,
        limit: int | None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: dict[str, Any] = {}
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
        ordering = " ORDER BY kickoff ASC, id ASC"
        if limit is not None:
            parameters["row_limit"] = max(0, int(limit))
            ordering = " ORDER BY kickoff DESC, id DESC LIMIT :row_limit"
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(f"SELECT payload FROM fixtures{where}{ordering}"),
                parameters,
            ).mappings().all()
        fixtures = [json.loads(row["payload"]) for row in rows]
        return list(reversed(fixtures)) if limit is not None else fixtures

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
            previous_context = payload.get("evidence") or {}
            for field in ("odds_by_bookmaker", "dongqiudi_analysis"):
                if field not in context and field in previous_context:
                    context[field] = previous_context[field]
            payload["evidence"] = context
            payload["evidence_synced_at"] = context.get("synced_at")
            payload["lineup_confirmed"] = bool((context.get("lineup") or {}).get("confirmed"))
            connection.execute(
                text("UPDATE fixtures SET payload = :payload WHERE id = :fixture_id"),
                {"payload": json.dumps(payload, ensure_ascii=False), "fixture_id": fixture_id},
            )
        self._fixture_revision += 1
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
            self._fixture_revision += 1
            return fixture

    def count_fixtures_by_prefix(self, prefix: str) -> int:
        with self.engine.begin() as connection:
            count = connection.execute(
                text("SELECT COUNT(*) FROM fixtures WHERE id LIKE :pattern"),
                {"pattern": f"{prefix}%"},
            ).scalar()
            return int(count or 0)

    def save_sync_marker(self, name: str, item_count: int = 0) -> None:
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        with self.engine.begin() as connection:
            exists = connection.execute(
                text("SELECT name FROM sync_metadata WHERE name = :name"),
                {"name": name},
            ).first()
            if exists:
                connection.execute(
                    text("UPDATE sync_metadata SET synced_at = :synced_at, item_count = :item_count WHERE name = :name"),
                    {"name": name, "synced_at": now, "item_count": int(item_count)},
                )
            else:
                connection.execute(
                    text("INSERT INTO sync_metadata (name, synced_at, item_count) VALUES (:name, :synced_at, :item_count)"),
                    {"name": name, "synced_at": now, "item_count": int(item_count)},
                )

    def sync_marker(self, name: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT name, synced_at, item_count FROM sync_metadata WHERE name = :name"),
                {"name": name},
            ).mappings().first()
        return dict(row) if row else None

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
        """Merge dated market-value history for each canonical player."""

        with self.engine.begin() as connection:
            for value in values:
                existing = connection.execute(
                    text(
                        "SELECT payload FROM player_value_snapshots "
                        "WHERE canonical_player_id = :canonical_player_id"
                    ),
                    {"canonical_player_id": value["canonical_player_id"]},
                ).mappings().first()
                payload = _merge_player_value_payload(
                    json.loads(existing["payload"]) if existing else None,
                    value,
                )
                parameters = {
                    "canonical_player_id": value["canonical_player_id"],
                    "updated_at": payload.get("cached_at") or datetime.now(UTC).replace(microsecond=0).isoformat(),
                    "payload": json.dumps(payload, ensure_ascii=False),
                }
                if existing:
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

    def player_values(
        self,
        canonical_player_ids: list[str],
        as_of: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Return each player's newest value at or before an optional cutoff."""

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
        selected = [
            _player_value_at(json.loads(row["payload"]), as_of)
            for row in rows
        ]
        return [item for item in selected if item is not None]

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

    def save_player_stats(self, rows: list[dict[str, Any]]) -> int:
        """Upsert per-player season statistics snapshots (idempotent)."""

        if not rows:
            return 0
        with self.engine.begin() as connection:
            for row in rows:
                parameters = {
                    "id": row["id"],
                    "league": row.get("league") or "",
                    "season": str(row.get("season") or ""),
                    "team_id": str(row.get("team_id") or ""),
                    "player_id": str(row.get("player_id") or ""),
                    "synced_at": row.get("synced_at") or datetime.now(UTC).replace(microsecond=0).isoformat(),
                    "payload": json.dumps(row, ensure_ascii=False),
                }
                exists = connection.execute(
                    text("SELECT id FROM player_stats_snapshots WHERE id = :id"),
                    parameters,
                ).first()
                if exists:
                    connection.execute(
                        text(
                            "UPDATE player_stats_snapshots SET league = :league, season = :season, "
                            "team_id = :team_id, player_id = :player_id, synced_at = :synced_at, payload = :payload "
                            "WHERE id = :id"
                        ),
                        parameters,
                    )
                else:
                    connection.execute(
                        text(
                            "INSERT INTO player_stats_snapshots "
                            "(id, league, season, team_id, player_id, synced_at, payload) "
                            "VALUES (:id, :league, :season, :team_id, :player_id, :synced_at, :payload)"
                        ),
                        parameters,
                    )
        return len(rows)

    def player_stats(self, player_ids: list[str], season: str) -> list[dict[str, Any]]:
        """Return season statistics snapshots for the requested player ids."""

        if not player_ids:
            return []
        parameters = {f"player_{index}": player_id for index, player_id in enumerate(player_ids)}
        parameters["season"] = str(season)
        placeholders = ", ".join(f":{key}" for key in parameters if key.startswith("player_"))
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT payload FROM player_stats_snapshots "
                    f"WHERE player_id IN ({placeholders}) AND season = :season "
                    "ORDER BY synced_at"
                ),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows]

    def player_stats_synced_at(self, team_id: str, season: str) -> str | None:
        """Latest sync timestamp across a team's player statistics rows."""

        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT MAX(synced_at) AS latest FROM player_stats_snapshots "
                    "WHERE team_id = :team_id AND season = :season AND player_id != '__league_teams__'"
                ),
                {"team_id": str(team_id), "season": str(season)},
            ).mappings().first()
        return row["latest"] if row else None

    def save_league_teams(self, league: str, season: str, teams: list[dict[str, Any]]) -> None:
        """Cache one league-season's provider team list (one request per season)."""

        identifier = f"pstats:espn:teams:{league}:{season}"
        self.save_player_stats(
            [
                {
                    "id": identifier,
                    "league": league,
                    "season": str(season),
                    "team_id": f"league:{league}",
                    "player_id": "__league_teams__",
                    "synced_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                    "teams": teams,
                }
            ]
        )

    def league_teams(self, league: str, season: str) -> list[dict[str, Any]] | None:
        """Return the cached provider team list, or None when never synced."""

        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT payload FROM player_stats_snapshots "
                    "WHERE id = :id AND player_id = '__league_teams__'"
                ),
                {"id": f"pstats:espn:teams:{league}:{season}"},
            ).mappings().first()
        return json.loads(row["payload"]).get("teams") if row else None

    def save_team_transfers(
        self,
        team_id: str,
        season: str,
        transfers: list[dict[str, Any]],
        synced_at: str | None = None,
        *,
        source: str = "api-football",
    ) -> None:
        """Store one team's transfer records (one row per team-season)."""

        provider = str(source or "api-football").strip().casefold()
        identifier = f"transfers:{provider}:{team_id}:{season}"
        self.save_player_stats(
            [
                {
                    "id": identifier,
                    "league": "",
                    "season": str(season),
                    "team_id": str(team_id),
                    "player_id": "__transfers__",
                    "synced_at": synced_at or datetime.now(UTC).replace(microsecond=0).isoformat(),
                    "source": provider,
                    "transfers": transfers,
                }
            ]
        )

    def team_transfers_row(
        self,
        team_id: str,
        season: str,
        *,
        source: str = "api-football",
    ) -> dict[str, Any] | None:
        """Return one team's stored transfer records, or None when never synced."""

        provider = str(source or "api-football").strip().casefold()
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT payload FROM player_stats_snapshots "
                    "WHERE id = :id AND player_id = '__transfers__'"
                ),
                {"id": f"transfers:{provider}:{team_id}:{season}"},
            ).mappings().first()
        return json.loads(row["payload"]) if row else None

    def save_venue_location(self, query: str, latitude: float, longitude: float) -> None:
        """Cache one geocoded venue query (geocoders are rate limited)."""

        query_text = str(query or "").strip()
        if not query_text:
            return
        query_hash = hashlib.sha1(query_text.encode("utf-8")).hexdigest()
        parameters = {
            "query_hash": query_hash,
            "query_text": query_text[:255],
            "latitude": float(latitude),
            "longitude": float(longitude),
            "synced_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        }
        with self.engine.begin() as connection:
            exists = connection.execute(
                text("SELECT query_hash FROM venue_locations WHERE query_hash = :query_hash"),
                parameters,
            ).first()
            if exists:
                connection.execute(
                    text(
                        "UPDATE venue_locations SET latitude = :latitude, longitude = :longitude, "
                        "synced_at = :synced_at WHERE query_hash = :query_hash"
                    ),
                    parameters,
                )
            else:
                connection.execute(
                    text(
                        "INSERT INTO venue_locations (query_hash, query_text, latitude, longitude, synced_at) "
                        "VALUES (:query_hash, :query_text, :latitude, :longitude, :synced_at)"
                    ),
                    parameters,
                )

    def venue_location(self, query: str) -> tuple[float, float] | None:
        """Return the cached coordinates for one geocode query."""

        query_text = str(query or "").strip()
        if not query_text:
            return None
        query_hash = hashlib.sha1(query_text.encode("utf-8")).hexdigest()
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT latitude, longitude FROM venue_locations WHERE query_hash = :query_hash"),
                {"query_hash": query_hash},
            ).mappings().first()
        return (float(row["latitude"]), float(row["longitude"])) if row else None

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

    def prediction(self, prediction_id: str) -> dict[str, Any] | None:
        """Return one immutable prediction by its stable ID."""

        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT payload FROM predictions WHERE id = :prediction_id"),
                {"prediction_id": prediction_id},
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

    def bets_for_predictions(self, prediction_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        """Return simulated bets keyed by prediction ID in one database read."""

        ids = sorted({str(value) for value in prediction_ids if value})
        if not ids:
            return {}
        placeholders = ", ".join(f":prediction_{index}" for index, _ in enumerate(ids))
        parameters = {f"prediction_{index}": prediction_id for index, prediction_id in enumerate(ids)}
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT prediction_id, payload FROM bets "
                    f"WHERE prediction_id IN ({placeholders})"
                ),
                parameters,
            ).mappings().all()
        return {
            str(row["prediction_id"]): json.loads(row["payload"])
            for row in rows
        }

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

    def update_fixture_settlement_outcome(self, prediction_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """Apply a post-settlement score correction to one evaluation row.

        Only label-derived fields change (outcome/correct/brier/log_loss/rps/
        score); the frozen forecast side stays untouched. The correction is
        stamped so audits can tell corrected rows from first-pass ones.
        """

        with self.engine.begin() as connection:
            row = connection.execute(
                text("SELECT payload FROM fixture_settlements WHERE prediction_id = :prediction_id"),
                {"prediction_id": prediction_id},
            ).mappings().first()
            if not row:
                return None
            payload = json.loads(row["payload"])
            allowed = {"actual_outcome", "correct", "brier_score", "log_loss", "rps", "score"}
            payload.update({key: updates[key] for key in updates if key in allowed})
            payload["score_corrected_at"] = updates.get("score_corrected_at")
            payload["prior_actual_outcome"] = updates.get("prior_actual_outcome")
            connection.execute(
                text("UPDATE fixture_settlements SET payload = :payload WHERE prediction_id = :prediction_id"),
                {"payload": json.dumps(payload, ensure_ascii=False), "prediction_id": prediction_id},
            )
            return payload

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

    def save_backtest_run(self, run: dict[str, Any]) -> dict[str, Any]:
        """Persist one reproducible backtest run record."""

        required = ("run_id", "name", "started_at", "status")
        if any(not run.get(key) for key in required):
            raise ValueError("Backtest run identity fields are required")
        try:
            with self.engine.begin() as connection:
                existing = connection.execute(
                    text("SELECT payload FROM backtest_runs WHERE run_id = :run_id"),
                    {"run_id": run["run_id"]},
                ).mappings().first()
                if existing:
                    stored = json.loads(existing["payload"])
                    if stored != run:
                        raise ValueError("Backtest run is immutable")
                    return stored
                connection.execute(
                    text(
                        "INSERT INTO backtest_runs ("
                        "run_id, name, started_at, finished_at, dataset_version, run_config, "
                        "code_version, model_version, feature_version, ensemble_version, "
                        "calibration_version, status, payload) VALUES ("
                        ":run_id, :name, :started_at, :finished_at, :dataset_version, :run_config, "
                        ":code_version, :model_version, :feature_version, :ensemble_version, "
                        ":calibration_version, :status, :payload)"
                    ),
                    {
                        "run_id": run["run_id"],
                        "name": run["name"],
                        "started_at": run["started_at"],
                        "finished_at": run.get("finished_at"),
                        "dataset_version": run.get("dataset_version"),
                        "run_config": json.dumps(run.get("config") or {}, ensure_ascii=False),
                        "code_version": run.get("code_version"),
                        "model_version": run.get("model_version"),
                        "feature_version": run.get("feature_version"),
                        "ensemble_version": run.get("ensemble_version"),
                        "calibration_version": run.get("calibration_version"),
                        "status": run["status"],
                        "payload": json.dumps(run, ensure_ascii=False),
                    },
                )
        except IntegrityError as error:
            if not self._is_backtest_run_unique_conflict(error):
                raise
            stored = self.backtest_run(str(run["run_id"]))
            if stored is None:
                raise
            if stored != run:
                raise ValueError("Backtest run is immutable") from error
            return stored
        return run

    @staticmethod
    def _is_backtest_run_unique_conflict(error: IntegrityError) -> bool:
        original = getattr(error, "orig", None)
        arguments = getattr(original, "args", ())
        vendor_code = arguments[0] if arguments else None
        if str(vendor_code) == "1062":
            return True

        sqlite_code = getattr(original, "sqlite_errorcode", None)
        sqlite_name = str(getattr(original, "sqlite_errorname", "")).upper()
        if sqlite_code in {1555, 2067} or sqlite_name in {
            "SQLITE_CONSTRAINT_PRIMARYKEY",
            "SQLITE_CONSTRAINT_UNIQUE",
        }:
            return True

        message = str(original or error).casefold()
        statement = str(getattr(error, "statement", "") or "").casefold()
        targets_backtest_runs = (
            "backtest_runs" in statement or "backtest_runs" in message
        )
        return targets_backtest_runs and (
            "unique constraint failed" in message
            or ("duplicate entry" in message and "for key" in message)
        )

    def backtest_run(self, run_id: str) -> dict[str, Any] | None:
        """Return one persisted backtest run."""

        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT payload FROM backtest_runs WHERE run_id = :run_id"),
                {"run_id": run_id},
            ).mappings().first()
        return json.loads(row["payload"]) if row else None

    def backtest_runs(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """List persisted backtest runs newest first."""

        where = " WHERE status = :status" if status else ""
        parameters = {"status": status} if status else {}
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT payload FROM backtest_runs"
                    f"{where} ORDER BY started_at DESC, run_id DESC"
                ),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows[: max(1, min(int(limit), 200))]]

    def save_model_evaluation_experiment(self, experiment: dict[str, Any]) -> dict[str, Any]:
        """Persist one immutable P6 evaluation experiment."""

        required = ("experiment_id", "created_at", "code_version", "status")
        if any(not experiment.get(key) for key in required):
            raise ValueError("Model evaluation experiment identity fields are required")
        with self.engine.begin() as connection:
            existing = connection.execute(
                text("SELECT payload FROM model_evaluation_experiments WHERE experiment_id = :experiment_id"),
                {"experiment_id": experiment["experiment_id"]},
            ).mappings().first()
            if existing:
                stored = json.loads(existing["payload"])
                if stored != experiment:
                    raise ValueError("Model evaluation experiment is immutable")
                return stored
            connection.execute(
                text(
                    "INSERT INTO model_evaluation_experiments ("
                    "experiment_id, created_at, code_version, feature_version, ensemble_version, calibration_version, "
                    "league, dataset_version, train_range, validation_range, test_range, sample_count, status, payload) VALUES ("
                    ":experiment_id, :created_at, :code_version, :feature_version, :ensemble_version, :calibration_version, "
                    ":league, :dataset_version, :train_range, :validation_range, :test_range, :sample_count, :status, :payload)"
                ),
                {
                    "experiment_id": experiment["experiment_id"],
                    "created_at": experiment["created_at"],
                    "code_version": experiment["code_version"],
                    "feature_version": experiment.get("feature_version"),
                    "ensemble_version": experiment.get("ensemble_version"),
                    "calibration_version": experiment.get("calibration_version"),
                    "league": experiment.get("league"),
                    "dataset_version": experiment.get("dataset_version"),
                    "train_range": json.dumps(experiment.get("train_range") or {}, ensure_ascii=False),
                    "validation_range": json.dumps(experiment.get("validation_range") or {}, ensure_ascii=False),
                    "test_range": json.dumps(experiment.get("test_range") or {}, ensure_ascii=False),
                    "sample_count": int(experiment.get("sample_count") or 0),
                    "status": experiment["status"],
                    "payload": json.dumps(experiment, ensure_ascii=False),
                },
            )
        return experiment

    def model_evaluation_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT payload FROM model_evaluation_experiments WHERE experiment_id = :experiment_id"),
                {"experiment_id": experiment_id},
            ).mappings().first()
        return json.loads(row["payload"]) if row else None

    def model_evaluation_experiments(
        self,
        league: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = " WHERE league = :league" if league else ""
        parameters = {"league": league} if league else {}
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT payload FROM model_evaluation_experiments" f"{clauses} ORDER BY created_at DESC, experiment_id DESC"),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows[: max(1, min(int(limit), 200))]]

    def save_model_evaluation_metrics(self, experiment_id: str, metrics: Iterable[dict[str, Any]]) -> None:
        """Persist immutable model/league metric rows for one experiment."""

        with self.engine.begin() as connection:
            for metric in metrics:
                league = str(metric.get("league") or "GLOBAL")
                model_key = str(metric.get("model_key") or "unknown")
                metric_id = f"{experiment_id}:{league}:{model_key}"
                item = {**metric, "experiment_id": experiment_id, "metric_id": metric_id}
                existing = connection.execute(
                    text("SELECT payload FROM model_evaluation_metrics WHERE metric_id = :metric_id"),
                    {"metric_id": metric_id},
                ).mappings().first()
                if existing:
                    if json.loads(existing["payload"]) != item:
                        raise ValueError("Model evaluation metric is immutable")
                    continue
                connection.execute(
                    text(
                        "INSERT INTO model_evaluation_metrics (metric_id, experiment_id, league, model_key, sample_count, status, payload) "
                        "VALUES (:metric_id, :experiment_id, :league, :model_key, :sample_count, :status, :payload)"
                    ),
                    {
                        "metric_id": metric_id,
                        "experiment_id": experiment_id,
                        "league": league,
                        "model_key": model_key,
                        "sample_count": int(metric.get("sample_count") or 0),
                        "status": metric.get("status") or "unavailable",
                        "payload": json.dumps(item, ensure_ascii=False),
                    },
                )

    def model_evaluation_metrics(
        self,
        experiment_id: str | None = None,
        league: str | None = None,
        model_key: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        clauses = []
        parameters: dict[str, Any] = {}
        for column, value in (("experiment_id", experiment_id), ("league", league), ("model_key", model_key)):
            if value:
                clauses.append(f"{column} = :{column}")
                parameters[column] = value
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT payload FROM model_evaluation_metrics" f"{where} ORDER BY league, model_key"),
                parameters,
            ).mappings().all()
        return [json.loads(row["payload"]) for row in rows[: max(1, min(int(limit), 1000))]]

    def save_model_evaluation(self, experiment: dict[str, Any]) -> dict[str, Any]:
        """Persist the experiment and its flattened model metrics idempotently."""

        stored = self.save_model_evaluation_experiment(experiment)
        metrics: list[dict[str, Any]] = []
        for league, report in (experiment.get("reports") or {}).items():
            for model_key, metric in (report.get("models") or {}).items():
                metrics.append({"league": league, "model_key": model_key, **metric})
        self.save_model_evaluation_metrics(experiment["experiment_id"], metrics)
        return stored

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


def _merge_player_value_payload(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """Preserve prior dated values while refreshing one player's payload."""

    if not existing and not incoming.get("history"):
        return dict(incoming)
    if existing and not existing.get("history") and not incoming.get("history"):
        return dict(incoming)
    records: dict[tuple[str, str, float], dict[str, Any]] = {}
    for payload in (existing or {}, incoming):
        history = payload.get("history") if isinstance(payload.get("history"), list) else []
        if not history:
            history = [_player_value_history_entry(payload)]
        for record in history:
            if not isinstance(record, dict):
                continue
            try:
                amount = float(record.get("market_value_eur"))
            except (TypeError, ValueError):
                continue
            as_of = str(record.get("market_value_as_of") or "")
            source = str(record.get("market_value_source") or "")
            if not as_of or not source or _parse_datetime(as_of) is None:
                continue
            key = (as_of, source, amount)
            previous = records.get(key)
            if previous is None or str(record.get("captured_at") or "") >= str(previous.get("captured_at") or ""):
                records[key] = dict(record)
    history = sorted(
        records.values(),
        key=lambda item: (
            _parse_datetime(item.get("market_value_as_of")) or datetime.min.replace(tzinfo=UTC),
            str(item.get("captured_at") or ""),
        ),
    )
    if not history:
        return dict(incoming)
    latest = history[-1]
    result = {**(existing or {}), **incoming, **latest}
    result["canonical_player_id"] = incoming["canonical_player_id"]
    result["cached_at"] = incoming.get("cached_at") or latest.get("captured_at")
    result["history"] = history
    return result


def _player_value_history_entry(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: payload.get(key)
        for key in (
            "market_value_eur",
            "market_value_currency",
            "market_value_source",
            "market_value_as_of",
            "provider_player_id",
            "provider_person_id",
            "player_name",
            "source_url",
            "captured_at",
        )
    } | {"captured_at": payload.get("captured_at") or payload.get("cached_at")}


def _player_value_at(payload: dict[str, Any], as_of: Any | None) -> dict[str, Any] | None:
    history = payload.get("history") if isinstance(payload.get("history"), list) else []
    if not history:
        if as_of is None:
            return payload
        record_at = _parse_datetime(payload.get("market_value_as_of"))
        cutoff = _parse_datetime(as_of)
        return payload if record_at is not None and cutoff is not None and record_at <= cutoff else None
    cutoff = _parse_datetime(as_of) if as_of is not None else None
    if as_of is not None and cutoff is None:
        return None
    candidates = [
        item
        for item in history
        if isinstance(item, dict)
        and (record_at := _parse_datetime(item.get("market_value_as_of"))) is not None
        and (cutoff is None or record_at <= cutoff)
    ]
    if not candidates:
        return None
    selected = max(
        candidates,
        key=lambda item: (
            _parse_datetime(item.get("market_value_as_of")) or datetime.min.replace(tzinfo=UTC),
            str(item.get("captured_at") or ""),
        ),
    )
    result = dict(payload)
    result.pop("history", None)
    result.update(selected)
    result["cached_at"] = payload.get("cached_at") or selected.get("captured_at")
    return result


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


def _feature_value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


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
