from app.config import Settings


def test_dongqiudi_schedule_sync_runs_hourly_by_default() -> None:
    """Dongqiudi publishes fixtures one match-cycle ahead, so daily mapping
    misses fixtures that kick off beyond the current cycle."""

    settings = Settings(_env_file=None)

    assert settings.automation_dongqiudi_schedule_interval_minutes == 60


def test_chatgpt_has_a_fallback_model_for_timeouts() -> None:
    settings = Settings(_env_file=None)

    assert settings.chatgpt_fallback_model == "gpt-5.4-mini"


def test_league_exposure_cap_allows_two_league_day_bets() -> None:
    """单联赛 = 2 x 权益 x 2% = 4%,即同联赛当日可容纳两注。"""

    settings = Settings(_env_file=None)

    assert settings.portfolio_max_league_exposure == 0.04
    assert settings.portfolio_max_daily_exposure == 0.10
    assert settings.portfolio_priority_league_key == "csl"
    assert settings.portfolio_priority_team_name == "武汉三镇"
