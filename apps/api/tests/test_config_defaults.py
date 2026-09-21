from app.config import Settings


def test_dongqiudi_schedule_sync_runs_hourly_by_default() -> None:
    """Dongqiudi publishes fixtures one match-cycle ahead, so daily mapping
    misses fixtures that kick off beyond the current cycle."""

    settings = Settings(_env_file=None)

    assert settings.automation_dongqiudi_schedule_interval_minutes == 60
    assert settings.dongqiudi_lookahead_hours == 168
    assert settings.automation_squad_backfill_interval_minutes == 60
    assert settings.squad_backfill_limit == 12
    assert settings.dongqiudi_prematch_window_minutes == 360
    assert settings.dongqiudi_prematch_refresh_minutes == 15
    assert settings.automation_odds_reprediction_interval_minutes == 15


def test_chatgpt_has_a_fallback_model_for_timeouts() -> None:
    settings = Settings(_env_file=None)

    assert settings.chatgpt_fallback_model == "gpt-5.4-mini"


def test_deepseek_defaults_to_shadow_execution_only() -> None:
    settings = Settings(_env_file=None)

    assert settings.deepseek_execution_mode == "shadow"
    assert settings.chatgpt_execution_mode == "active"


def test_league_exposure_cap_allows_two_league_day_bets() -> None:
    """单联赛 = 2 x 权益 x 2% = 4%,即同联赛当日可容纳两注。"""

    settings = Settings(_env_file=None)

    assert settings.portfolio_max_league_exposure == 0.04
    assert settings.portfolio_max_daily_exposure == 0.10
    assert settings.portfolio_priority_league_key == "csl"
    assert settings.portfolio_priority_team_name == "武汉三镇"


def test_baseline_shrinks_toward_market_by_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.portfolio_baseline_market_shrinkage == 0.35


def test_short_term_stake_policy_defaults_to_one_percent_with_two_percent_cap() -> None:
    settings = Settings(_env_file=None)

    assert settings.portfolio_stake_fraction == 0.01
    assert settings.portfolio_max_single_bet_fraction == 0.02
    assert settings.automation_fd_confirmatory_research_interval_minutes == 20160
