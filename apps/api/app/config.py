"""Runtime configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """Application settings shared by API routes and providers."""

    model_config = SettingsConfigDict(env_file=(PROJECT_ENV, ".env"), extra="ignore")

    api_football_key: str = ""
    api_football_base_url: str = "https://v3.football.api-sports.io"
    # Deployment environment: local | test | staging | production (P15).
    environment: str = "local"
    api_deepseek_key: str = ""
    quya_llm_key: str = ""
    free_llm_quya_base_url: str = "https://api.quya.org/v1"
    free_llm_quya_model: str = "deepseek-v4-flash"
    free_llm_candidate_timeout_seconds: float = 45.0
    free_llm_enabled: bool = True
    deepseek_enabled: bool = True
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_timeout_seconds: float = 90
    deepseek_max_retries: int = 1
    deepseek_max_tokens: int = 3000
    api_chatgpt_key: str = ""
    chatgpt_model: str = "gpt-5.6-sol"
    chatgpt_base_url: str = "https://api.quya.org/v1"
    chatgpt_timeout_seconds: float = 180
    # Used as a one-shot retry when the primary model times out or returns
    # invalid output. Must be a model the same relay actually serves.
    chatgpt_fallback_model: str = "gpt-5.4-mini"
    simulation_competition_id: str = "dual-model-v1"
    admin_api_key: str = "dev-admin-key"
    database_url: str = "sqlite:///./football_ai.db"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    use_demo_data: bool = False
    schedule_provider: str = "thesportsdb"
    thesportsdb_api_key: str = "123"
    thesportsdb_base_url: str = "https://www.thesportsdb.com/api/v1/json"
    schedule_lookback_days: int = 1
    schedule_cache_ttl_minutes: int = 1440
    dongqiudi_enabled: bool = True
    dongqiudi_base_url: str = "https://www.dongqiudi.com"
    dongqiudi_sport_data_base_url: str = "https://beta-sport-data.dongdianqiu.com"
    dongqiudi_api_base_url: str = "https://beta-api.dongdianqiu.com"
    dongqiudi_timeout_seconds: float = 20
    # Match the public seven-day fixture horizon so team IDs and rosters are
    # available before a match enters the final prediction windows.
    dongqiudi_lookahead_hours: int = 168
    # Keep odds fresh for the full six-hour execution horizon. The final
    # decision still remains subject to the portfolio freshness gate.
    dongqiudi_prematch_window_minutes: int = 360
    dongqiudi_prematch_lead_hours: int = 24
    dongqiudi_prematch_refresh_minutes: int = 15
    dongqiudi_concurrency: int = 2
    # Dongqiudi's public match_list only serves the current match cycle, so
    # schedule mapping must run often enough to catch newly published cycles.
    automation_dongqiudi_schedule_interval_minutes: int = 60
    automation_dongqiudi_score_interval_minutes: int = 5
    automation_dongqiudi_prematch_interval_minutes: int = 5
    espn_base_url: str = "https://site.api.espn.com"
    standings_cache_ttl_minutes: int = 360
    team_cache_ttl_minutes: int = 360
    automation_enabled: bool = True
    automation_analysis_enabled: bool = True
    automation_tick_seconds: int = 60
    automation_fixture_interval_minutes: int = 1440
    automation_evidence_interval_minutes: int = 1440
    automation_lineup_interval_minutes: int = 5
    lineup_refresh_offsets_minutes: str = "60,30"
    prediction_refresh_offsets_hours: str = "24,12,6,1,0.5"
    automation_standings_interval_minutes: int = 360
    automation_analysis_interval_minutes: int = 5
    automation_odds_reprediction_interval_minutes: int = 15
    automation_settlement_interval_minutes: int = 15
    automation_historical_accumulation_interval_minutes: int = 1440
    # 模型质量三件套（P17 治理）：多赛季历史回填 + 周度集成权重学习。
    historical_seasons_per_league: int = 3
    historical_max_per_league_season: int = 100
    historical_max_total: int = 2400
    automation_historical_backfill_interval_minutes: int = 60
    automation_ensemble_learning_interval_minutes: int = 10080
    automation_fd_backfill_interval_minutes: int = 360
    football_data_seasons_backfill: int = 5
    automation_understat_interval_minutes: int = 360
    automation_match_stats_interval_minutes: int = 60
    match_stats_backfill_limit: int = 25
    automation_player_stats_interval_minutes: int = 1440
    player_stats_backfill_limit: int = 8
    automation_discipline_interval_minutes: int = 60
    discipline_backfill_limit: int = 25
    automation_transfers_interval_minutes: int = 1440
    transfers_backfill_limit: int = 6
    automation_weather_interval_minutes: int = 60
    weather_horizon_days: int = 7
    weather_backfill_limit: int = 30
    weather_stale_hours: int = 6
    automation_clubeelo_interval_minutes: int = 1440
    automation_squad_backfill_interval_minutes: int = 60
    squad_backfill_limit: int = 12
    automation_failure_backoff_minutes: int = 15
    prediction_lead_hours: int = 24
    evidence_refresh_minutes: int = 180
    lineup_refresh_hours: int = 2
    model_retry_minutes: int = 180
    automation_evidence_refresh_limit: int = 32
    schedule_lookahead_days: int = 7
    automation_fixed_stake: float = 100.0
    simulation_initial_bankroll: float = 5000.0
    # P2 deterministic portfolio policy. Fractions are relative to bankroll.
    notify_webhook_url: str = ""
    notify_email_to: str = ""
    notify_smtp_host: str = "smtp.qq.com"
    notify_smtp_port: int = 465
    notify_smtp_user: str = ""
    notify_smtp_pass: str = ""
    automation_notify_interval_minutes: int = 5
    portfolio_min_edge: float = 0.05
    portfolio_min_ev: float = 0.05
    portfolio_max_plausible_edge: float = 0.60
    portfolio_max_plausible_ev: float = 1.50
    portfolio_max_odds_age_minutes: float = 720.0
    portfolio_stake_fraction: float = 0.01
    portfolio_max_single_bet_fraction: float = 0.02
    portfolio_max_daily_exposure: float = 0.10
    portfolio_max_league_exposure: float = 0.04
    portfolio_max_total_exposure: float = 0.10
    portfolio_max_drawdown: float = 0.30
    portfolio_min_data_completeness: float = 0.70
    portfolio_max_league_candidates: int | None = 2
    # Thin xG baselines get shrunk toward the de-vig market prior (weight on
    # the market) before they may enter candidate selection.
    portfolio_baseline_market_shrinkage: float = 0.35
    # ADR-015：LLM 概率在组合层向去水市场先验收缩，保留权重 0.7（市场拿 0.3）。
    portfolio_llm_keep_weight: float = 0.7
    automation_fd_confirmatory_research_interval_minutes: int = 20160
    # Selection priority: CSL matches rank first, and the priority team above them.
    portfolio_priority_league_key: str = "csl"
    portfolio_priority_team_name: str = "武汉三镇"
    portfolio_ev_weight: float = 1.0
    portfolio_edge_weight: float = 1.0
    portfolio_confidence_weight: float = 0.25
    portfolio_data_quality_weight: float = 0.25
    portfolio_clv_weight: float = 0.10
    portfolio_freshness_weight: float = 0.10
    portfolio_risk_weight: float = 0.25

@lru_cache
def get_settings() -> Settings:
    """Return the cached runtime settings."""

    return Settings()
