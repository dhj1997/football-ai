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
    api_deepseek_key: str = ""
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_timeout_seconds: float = 90
    deepseek_max_retries: int = 1
    deepseek_max_tokens: int = 3000
    api_chatgpt_key: str = ""
    chatgpt_model: str = "gpt-5.6-sol"
    chatgpt_base_url: str = "https://api.quya.org/v1"
    simulation_competition_id: str = "dual-model-v1"
    admin_api_key: str = "dev-admin-key"
    database_url: str = "sqlite:///./football_ai.db"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    use_demo_data: bool = False
    schedule_provider: str = "thesportsdb"
    thesportsdb_api_key: str = "123"
    thesportsdb_base_url: str = "https://www.thesportsdb.com/api/v1/json"
    schedule_lookback_days: int = 1
    schedule_cache_ttl_minutes: int = 60
    espn_base_url: str = "https://site.api.espn.com"
    standings_cache_ttl_minutes: int = 360
    team_cache_ttl_minutes: int = 360
    automation_enabled: bool = True
    automation_tick_seconds: int = 60
    automation_fixture_interval_minutes: int = 60
    automation_standings_interval_minutes: int = 360
    automation_analysis_interval_minutes: int = 5
    automation_settlement_interval_minutes: int = 15
    automation_failure_backoff_minutes: int = 15
    prediction_lead_hours: int = 36
    evidence_refresh_minutes: int = 180
    lineup_refresh_hours: int = 2
    model_retry_minutes: int = 180
    automation_evidence_refresh_limit: int = 1

@lru_cache
def get_settings() -> Settings:
    """Return the cached runtime settings."""

    return Settings()
