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
    admin_api_key: str = "dev-admin-key"
    database_url: str = "sqlite:///./football_ai.db"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    use_demo_data: bool = False
    schedule_provider: str = "thesportsdb"
    thesportsdb_api_key: str = "123"
    thesportsdb_base_url: str = "https://www.thesportsdb.com/api/v1/json"
    schedule_lookback_days: int = 1

    @property
    def sqlite_path(self) -> str:
        """Return the local SQLite path from the configured database URL."""

        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("The MVP runtime currently requires a sqlite:/// database URL")
        return self.database_url.removeprefix(prefix)


@lru_cache
def get_settings() -> Settings:
    """Return the cached runtime settings."""

    return Settings()
