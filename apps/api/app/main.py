"""FastAPI entry point for continuous football analysis and simulation."""

import asyncio
from dataclasses import replace
from contextlib import asynccontextmanager, suppress
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .automation import AutomationRunner
from .backtest_engine import build_backtest_rows, run_backtest_engine
from .config import Settings, get_settings
from .bankroll import BankrollService, DualBankrollService
from .chatgpt_provider import ChatGptProvider
from .competition_registry import COMPETITION_REGISTRY
from .data import CHINA_TZ, demo_context, demo_fixtures, unavailable_context
from .data_quality_engine import provider_reliability
from .database import PredictionRepository
from .deepseek_provider import DeepSeekProvider
from .dongqiudi_provider import DongqiudiProvider
from .dongqiudi_sync import DongqiudiSyncService
from .dual_prediction_service import DualPredictionService
from .evidence_provider import ApiFootballEvidenceProvider
from .explainability import build_explanation_graph
from .evidence_chain import (
    EvidenceProviderChain,
    localize_evidence_players,
    merge_evidence,
)
from .historical_validation import assess_data_quality, serialize_public
from .historical_accumulation import HistoricalOOSAccumulationService
from .league_data_pipeline import (
    SUPPORTED_LEAGUES,
    HistoricalLeagueDataService,
    build_default_provider_registry,
    normalize_league_code,
    public_registry,
    run_three_league_backtest,
)
from .model_evaluation import ModelEvaluationService
from .espn_evidence_provider import EspnEvidenceProvider
from .league_provider import EspnLeagueProvider
from .league_sync import LeagueSyncService
from .market_decision import apply_market_decision
from .market_intelligence import MarketIntelligenceService
from .market_prior import (
    MarketPriorError,
    Round5ProbabilityEngine,
    persist_round5_market_snapshot,
)
from .observability import (
    ALERT_RULES,
    MetricsRegistry,
    SLO_CATALOG,
    emit_observability_log,
    evaluate_alerts,
    new_correlation_id,
    observe_system_state,
)
from .model_platform import (
    BASELINE_VERSION,
    DIXON_COLES_VERSION,
    ELO_PRIOR_VERSION,
    POISSON_V2_VERSION,
)
from .model_fitting import fit_from_repository, fitted_record, load_fitted_params
from .prediction import set_fitted_params_provider
from .clubeelo_provider import ClubEloProvider, refresh_ratings as refresh_clubeelo_ratings
from .football_data_provider import fetch_season_csv, sync_season
from .free_llm_provider import FreeLlmChainProvider, probe_chain
from .match_stats_sync import sync_match_stats
from .understat_provider import (
    UNDERSTAT_LEAGUE_MAP,
    fetch_league_data as fetch_understat_league_data,
    sync_understat_xg,
)
from .model_registry import ModelRegistry, ModelRegistryError
from .provider import ApiFootballProvider
from .prediction_service import PredictionService
from .prompt_contract import DEFAULT_PROMPT_CONTRACT
from .research_engine import (
    filter_settlement_rows_by_source,
    leakage_audit as audit_research_rows,
    run_research,
    validate_hypothesis,
)
from .player_identity import public_payload
from .player_impact import apply_player_impact
from .player_name_provider import (
    ChatGptPlayerNameProvider,
    DeepSeekPlayerNameProvider,
    FallbackPlayerNameProvider,
    PlayerNameService,
)
from .player_value_provider import DongqiudiPlayerValueProvider, PlayerValueService
from .player_stats import PlayerStatsService, sync_player_stats
from .weather_provider import WeatherProvider
from .weather_sync import sync_weather
from .portfolio import PortfolioConfig
from .production import (
    EnvironmentContract,
    _settings_view,
    mysql_backup_verification_status,
    require_mysql_runtime,
    run_migrations,
    run_smoke_checks,
)
from .prediction_intelligence import (
    build_feature_snapshot,
    build_feature_snapshot_v2,
    build_performance_profiles,
    parse_timestamp,
    run_backtest,
    weighted_ensemble,
)
from .feature_coverage import build_feature_coverage
from .no_ml_guard import NoMLNumericPathError
from .probability_engine import ProbabilityEngineError, TransparentProbabilityEngine
from .schedule_provider import TheSportsDbProvider
from .schedule_sync import ScheduleSyncService, deduplicate_fixtures
from .settlement import SettlementService
from .team_names import to_chinese_team_name
from .recent_form import RecentFormService
from .team_provider import EspnTeamProvider
from .team_sync import TeamSyncService
from .temporal_backtest import (
    BACKTEST_VERSION,
    TemporalBacktestService,
    build_round6_backtest_run,
)


MODEL_LABELS = {
    "deepseek": "DeepSeek",
    "chatgpt": "GPT-5.6 Sol",
}

MATCH_EVIDENCE_SOURCES = ("thesportsdb-partial", "dongqiudi")


class RuntimeModelConfigUpdate(BaseModel):
    """Editable provider settings; API keys are optional replacements."""

    model_config = ConfigDict(extra="forbid")

    model: str | None = Field(default=None, min_length=1, max_length=128)
    base_url: str | None = Field(default=None, min_length=1, max_length=512)
    api_key: str | None = Field(default=None, max_length=512)


class RuntimePortfolioConfigUpdate(BaseModel):
    """High-impact subset of the deterministic paper portfolio policy."""

    model_config = ConfigDict(extra="forbid")

    min_edge: float | None = Field(default=None, ge=0, le=1)
    min_ev: float | None = Field(default=None, ge=0, le=1)
    stake_fraction: float | None = Field(default=None, ge=0, le=1)
    max_total_exposure: float | None = Field(default=None, ge=0, le=1)
    max_drawdown: float | None = Field(default=None, ge=0, le=1)


class RuntimeConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    models: dict[Literal["deepseek", "chatgpt"], RuntimeModelConfigUpdate] = Field(default_factory=dict)
    portfolio: RuntimePortfolioConfigUpdate | None = None


class Round6ProbabilityBacktestRequest(BaseModel):
    """Strict, evaluation-only Round 6 filters."""

    model_config = ConfigDict(extra="forbid", strict=True)

    start: str | None = None
    end: str | None = None
    league: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:[_-][a-z0-9]+)*$",
    )
    limit: int = Field(default=30, gt=0, le=200)

    @field_validator("start", "end")
    @classmethod
    def validate_iso_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("date must use ISO YYYY-MM-DD format") from error
        if parsed.isoformat() != value:
            raise ValueError("date must use ISO YYYY-MM-DD format")
        return value


class Round6ProbabilityBacktestQuery(Round6ProbabilityBacktestRequest):
    """Strict HTTP query representation for Round 6 filters."""

    @field_validator("limit", mode="before")
    @classmethod
    def validate_query_limit(cls, value: object) -> int:
        if (
            not isinstance(value, str)
            or not value.isascii()
            or not value.isdigit()
        ):
            raise ValueError("limit must be a positive integer")
        if value.startswith("0"):
            raise ValueError("limit must be a positive integer")
        return int(value)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task: asyncio.Task | None = None
    async def warm_and_run() -> None:
        try:
            await schedule_sync.warm_cache()
        except Exception:
            # A remote database may be temporarily unavailable; the first
            # request will retry through the normal freshness path.
            pass
        if settings.automation_enabled:
            await asyncio.sleep(5)
            await automation_runner.run_loop()

    task = asyncio.create_task(warm_and_run(), name="football-ai-warmup")
    try:
        yield
    finally:
        if task is not None:
            automation_runner.stop()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="足球赛前分析 API", version="0.1.0", lifespan=lifespan)
settings = get_settings()
require_mysql_runtime(settings)
request_metrics = MetricsRegistry(window_size=500)
# 比赛详情只读派生视图的短缓存：详情 payload 本身语义冻结，
# 30 秒内重复打开同一比赛直接命中，避免重复全表扫描与重算。
_fixture_detail_cache: dict[str, tuple[float, dict]] = {}
FIXTURE_DETAIL_CACHE_TTL_SECONDS = 30.0


def _invalidate_fixture_detail_cache(fixture_id: str | None = None) -> None:
    if fixture_id is None:
        _fixture_detail_cache.clear()
    else:
        _fixture_detail_cache.pop(fixture_id, None)
repository = PredictionRepository(
    settings.database_url,
    settings.simulation_competition_id,
    ("deepseek", "chatgpt"),
    settings.simulation_initial_bankroll,
)
repository.initialize()
provider = ApiFootballProvider(settings.api_football_key, settings.api_football_base_url)
api_football_evidence_provider = ApiFootballEvidenceProvider(
    settings.api_football_key,
    settings.api_football_base_url,
    settings.thesportsdb_api_key,
    settings.thesportsdb_base_url,
)
espn_evidence_provider = EspnEvidenceProvider(
    settings.espn_base_url,
)
dongqiudi_provider = DongqiudiProvider(
    settings.dongqiudi_base_url if settings.dongqiudi_enabled else "",
    settings.dongqiudi_sport_data_base_url,
    settings.dongqiudi_api_base_url,
    settings.dongqiudi_timeout_seconds,
)
evidence_provider = EvidenceProviderChain(
    api_football_evidence_provider,
    espn_evidence_provider,
    api_football_evidence_provider,
    dongqiudi_provider,
)
schedule_provider = TheSportsDbProvider(settings.thesportsdb_api_key, settings.thesportsdb_base_url)
league_provider = EspnLeagueProvider(settings.espn_base_url)
schedule_sync = ScheduleSyncService(
    schedule_provider,
    repository,
    settings.schedule_lookback_days,
    settings.schedule_cache_ttl_minutes,
    None,
    settings.schedule_lookahead_days,
)
deepseek_provider = DeepSeekProvider(
    settings.api_deepseek_key,
    settings.deepseek_model,
    settings.deepseek_base_url,
    settings.deepseek_timeout_seconds,
    settings.deepseek_max_retries,
    settings.deepseek_max_tokens,
)
deepseek_chain_provider = FreeLlmChainProvider(
    deepseek_provider,
    quya_base_url=settings.free_llm_quya_base_url,
    quya_model=settings.free_llm_quya_model,
    quya_api_key=settings.quya_llm_key,
    candidate_timeout_seconds=settings.free_llm_candidate_timeout_seconds,
    enabled=settings.free_llm_enabled,
)
player_value_provider = DongqiudiPlayerValueProvider(dongqiudi_provider)
player_value_service = PlayerValueService(
    player_value_provider,
    repository,
    stale_after_days=settings.player_values_stale_days,
)
player_stats_service = PlayerStatsService(repository)
chatgpt_provider = ChatGptProvider(
    settings.api_chatgpt_key,
    settings.chatgpt_model,
    settings.chatgpt_base_url,
    settings.chatgpt_timeout_seconds,
    settings.deepseek_max_retries,
    settings.deepseek_max_tokens,
    fallback_model=settings.chatgpt_fallback_model,
)
player_name_provider = FallbackPlayerNameProvider(
    ([DeepSeekPlayerNameProvider(
            settings.api_deepseek_key,
            settings.deepseek_model,
            settings.deepseek_base_url,
            settings.deepseek_timeout_seconds,
            settings.deepseek_max_retries,
            settings.deepseek_max_tokens,
        )] if settings.deepseek_enabled else [])
    + [ChatGptPlayerNameProvider(
            settings.api_chatgpt_key,
            settings.chatgpt_model,
            settings.chatgpt_base_url,
            settings.chatgpt_timeout_seconds,
            settings.deepseek_max_retries,
            settings.deepseek_max_tokens,
        )]
)
player_name_service = PlayerNameService(player_name_provider, repository)
deepseek_prediction_service = PredictionService(
    deepseek_chain_provider,
    repository,
    "deepseek",
    settings.simulation_competition_id,
    player_value_service,
    settings.simulation_initial_bankroll,
    player_stats_service=player_stats_service,
)
chatgpt_prediction_service = PredictionService(
    chatgpt_provider,
    repository,
    "chatgpt",
    settings.simulation_competition_id,
    player_value_service,
    settings.simulation_initial_bankroll,
    player_stats_service=player_stats_service,
)
model_registry_service = ModelRegistry(repository)
active_prediction_services = {
    **({"deepseek": deepseek_prediction_service} if settings.deepseek_enabled else {}),
    "chatgpt": chatgpt_prediction_service,
}
prediction_service = DualPredictionService(
    active_prediction_services,
    settings.simulation_competition_id,
    player_name_service,
    model_registry_service,
)
active_bankroll_services = {
    **({"deepseek": BankrollService(repository, PortfolioConfig.from_settings(settings), settings.simulation_initial_bankroll).configure("deepseek", settings.simulation_competition_id)} if settings.deepseek_enabled else {}),
    "chatgpt": BankrollService(repository, PortfolioConfig.from_settings(settings), settings.simulation_initial_bankroll).configure("chatgpt", settings.simulation_competition_id),
}
bankroll_service = DualBankrollService(
    active_bankroll_services,
    settings.simulation_competition_id,
)
settlement_service = SettlementService(repository, settings.simulation_competition_id)
p5_provider_registry = build_default_provider_registry(provider, schedule_provider, league_provider)
historical_data_service = HistoricalLeagueDataService(repository, p5_provider_registry)
set_fitted_params_provider(lambda: load_fitted_params(repository))
clubeelo_provider = ClubEloProvider(
    timeout_seconds=settings.clubeelo_timeout_seconds,
    max_retries=settings.clubeelo_max_retries,
)
recent_form_service = RecentFormService(repository)
market_intelligence_service = MarketIntelligenceService(repository)
model_evaluation_service = ModelEvaluationService(repository)
historical_accumulation_service = HistoricalOOSAccumulationService(
    repository,
    {
        **({"deepseek": deepseek_provider} if settings.deepseek_enabled else {}),
        "chatgpt": chatgpt_provider,
    },
)
for _provider in p5_provider_registry.descriptors():
    repository.save_provider_registry({**_provider.as_dict(), "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat()})
repository.save_competition_registry(COMPETITION_REGISTRY.as_dict())
league_sync = LeagueSyncService(
    league_provider,
    repository,
    settings.standings_cache_ttl_minutes,
)
team_provider = EspnTeamProvider(settings.espn_base_url)
team_sync = TeamSyncService(team_provider, repository, settings.team_cache_ttl_minutes)
dongqiudi_sync = DongqiudiSyncService(
    dongqiudi_provider,
    repository,
    settings.dongqiudi_lookahead_hours,
    settings.dongqiudi_prematch_window_minutes,
    settings.dongqiudi_concurrency,
    prematch_lead_hours=settings.dongqiudi_prematch_lead_hours,
    prematch_refresh_minutes=settings.dongqiudi_prematch_refresh_minutes,
)
automation_runner = AutomationRunner(
    settings,
    repository,
    schedule_sync,
    league_sync,
    evidence_provider,
    prediction_service,
    bankroll_service,
    settlement_service,
    historical_accumulation_service,
    dongqiudi_sync,
    historical_data_service=historical_data_service,
    model_registry_service=model_registry_service,
    football_data_service=fetch_season_csv,
    understat_service=fetch_understat_league_data,
    api_football_service=provider,
    espn_team_service=team_provider,
    weather_service=WeatherProvider(),
    clubeelo_service=clubeelo_provider,
    dongqiudi_team_service=dongqiudi_provider,
    squad_fallback_provider=espn_evidence_provider,
    player_value_provider=player_value_provider,
)
runtime_config_updated_at: str | None = None


def _masked_api_key(value: str) -> str | None:
    if not value:
        return None
    return f"****{value[-4:]}" if len(value) > 4 else "****"


def _runtime_model_config() -> dict:
    providers = {
        "deepseek": deepseek_provider,
        "chatgpt": chatgpt_provider,
    }
    return {
        key: {
            "key": key,
            "label": MODEL_LABELS[key],
            "model": provider.model,
            "base_url": provider.base_url,
            "api_key_configured": bool(provider.api_key),
            "api_key_hint": _masked_api_key(provider.api_key),
            "provider_ready": provider.configured,
            "enabled": settings.deepseek_enabled if key == "deepseek" else True,
        }
        for key, provider in providers.items()
    }


def _runtime_portfolio_config() -> dict:
    policy = next(iter(bankroll_service.services.values())).portfolio_config
    return {
        "min_edge": policy.min_edge,
        "min_ev": policy.min_ev,
        "stake_fraction": policy.stake_fraction,
        "max_total_exposure": policy.max_total_exposure,
        "max_drawdown": policy.max_drawdown,
    }


def _runtime_config_payload() -> dict:
    return {
        "models": _runtime_model_config(),
        "portfolio": _runtime_portfolio_config(),
        "simulation_competition_id": settings.simulation_competition_id,
        "updated_at": runtime_config_updated_at,
        "is_runtime": True,
    }


def _update_model_provider(model_key: str, patch: RuntimeModelConfigUpdate) -> None:
    provider = deepseek_provider if model_key == "deepseek" else chatgpt_provider
    model_setting = "deepseek_model" if model_key == "deepseek" else "chatgpt_model"
    base_url_setting = "deepseek_base_url" if model_key == "deepseek" else "chatgpt_base_url"
    key_setting = "api_deepseek_key" if model_key == "deepseek" else "api_chatgpt_key"
    name_source = f"{model_key}_transliteration"
    name_providers = [item for item in player_name_provider.providers if getattr(item, "source_name", "") == name_source]
    if patch.model is not None:
        value = patch.model.strip()
        if not value:
            raise HTTPException(status_code=422, detail="模型名称不能为空")
        setattr(settings, model_setting, value)
        provider.model = value
        for item in name_providers:
            item.model = value
    if patch.base_url is not None:
        value = patch.base_url.strip().rstrip("/")
        if not value:
            raise HTTPException(status_code=422, detail="API 地址不能为空")
        setattr(settings, base_url_setting, value)
        provider.base_url = value
        for item in name_providers:
            item.base_url = value
    if patch.api_key is not None:
        value = patch.api_key.strip()
        setattr(settings, key_setting, value)
        provider.api_key = value
        for item in name_providers:
            item.api_key = value

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_admin(
    x_admin_key: Annotated[str | None, Header()] = None,
    runtime: Settings = Depends(get_settings),
) -> None:
    """Reject operator actions without the server-side admin key."""

    if x_admin_key != runtime.admin_api_key:
        raise HTTPException(status_code=401, detail="管理员凭证无效")


@app.middleware("http")
async def correlation_middleware(request, call_next):
    """Attach a correlation id to every request and record bounded metrics."""

    import time

    correlation_id = request.headers.get("x-correlation-id") or new_correlation_id("req")
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Correlation-ID"] = correlation_id
    request_metrics.record_request(duration_ms, response.status_code)
    emit_observability_log(
        "http_request",
        correlation_id=correlation_id,
        component="api",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round(duration_ms, 2),
    )
    return response


def _match_preview_context(fixture: dict, all_fixtures: list[dict] | None = None) -> dict | None:
    """League-position context and each team's next three fixtures (as-of now).

    Positions come from the cached standings snapshot; upcoming fixtures from
    the local schedule store. Both are current-state views, so this block is
    only attached for scheduled (pre-kickoff) matches. ``all_fixtures`` lets
    callers share one list_fixtures() scan with other context builders.
    """

    if fixture.get("status") != "scheduled":
        return None
    league_key = str(fixture.get("league_key") or "")
    snapshot = next(
        (row for row in repository.league_snapshots(league_key or None)),
        None,
    )
    standings = (snapshot or {}).get("standings") or []

    def standing_for(team: dict) -> dict | None:
        return next(
            (row for row in standings if str((row.get("team") or {}).get("name")) == str(team.get("name"))),
            None,
        )

    def position_block(team: dict) -> dict | None:
        row = standing_for(team)
        if not row:
            return None
        return {
            "rank": row.get("rank"),
            "played": row.get("played"),
            "points": row.get("points"),
            "goal_difference": row.get("goal_difference"),
            "form_note": row.get("note"),
        }

    kickoff = str(fixture.get("kickoff") or "")
    kickoff_at = datetime.fromisoformat(kickoff.replace("Z", "+00:00")) if kickoff else None

    def upcoming_for(team: dict) -> list[dict]:
        name = str(team.get("name") or "")
        rows = [
            row
            for row in (all_fixtures if all_fixtures is not None else repository.list_fixtures())
            if row.get("status") == "scheduled"
            and (
                str((row.get("home_team") or {}).get("name")) == name
                or str((row.get("away_team") or {}).get("name")) == name
            )
            and str(row.get("kickoff") or "") > kickoff
        ]
        rows.sort(key=lambda row: str(row.get("kickoff")))
        result = []
        previous = kickoff_at
        for row in rows[:3]:
            row_kickoff = str(row.get("kickoff") or "")
            row_at = datetime.fromisoformat(row_kickoff.replace("Z", "+00:00")) if row_kickoff else None
            rest_days = (
                round((row_at - previous).total_seconds() / 86400, 1)
                if row_at and previous
                else None
            )
            previous = row_at or previous
            opponent = (
                row.get("away_team")
                if str((row.get("home_team") or {}).get("name")) == name
                else row.get("home_team")
            )
            result.append(
                {
                    "fixture_id": row.get("id"),
                    "kickoff": row_kickoff,
                    "opponent": (opponent or {}).get("name"),
                    "opponent_logo": (opponent or {}).get("logo"),
                    "is_home": str((row.get("home_team") or {}).get("name")) == name,
                    "rest_days": rest_days,
                }
            )
        return result

    home_position = position_block(fixture.get("home_team") or {})
    away_position = position_block(fixture.get("away_team") or {})
    return {
        "league_key": league_key,
        "positions": {"home": home_position, "away": away_position},
        "rank_gap": (
            abs((home_position or {}).get("rank", 0) - (away_position or {}).get("rank", 0))
            if home_position and away_position
            else None
        ),
        "upcoming": {
            "home": upcoming_for(fixture.get("home_team") or {}),
            "away": upcoming_for(fixture.get("away_team") or {}),
        },
    }


def _fixture_or_404(fixture_id: str) -> dict:
    fixture = repository.fixture(fixture_id)
    if fixture is None and settings.use_demo_data:
        fixture = next((item for item in demo_fixtures() if item["id"] == fixture_id), None)
    if not fixture:
        raise HTTPException(status_code=404, detail="未找到比赛")
    return fixture


def _public_fixture_for_detail(fixture_id: str) -> dict:
    """Return the merged public record when provider rows share one match."""

    fixture = _fixture_or_404(fixture_id)
    fixture_date = fixture.get("fixture_date")
    if not fixture_date:
        return fixture
    cached_rows = schedule_sync.cached_fixtures(fixture_date, fixture_date)
    rows = cached_rows if cached_rows is not None else repository.list_fixtures(fixture_date, fixture_date)
    merged_rows = deduplicate_fixtures(rows)
    dongqiudi_id = str((fixture.get("external_ids") or {}).get("dongqiudi") or "")
    return next(
        (
            item
            for item in merged_rows
            if item.get("id") == fixture_id
            or (dongqiudi_id and str((item.get("external_ids") or {}).get("dongqiudi") or "") == dongqiudi_id)
        ),
        fixture,
    )


async def _ensure_fixture_team_data(fixture: dict) -> dict:
    """Load missing public team profiles only for the fixture being opened."""

    free_team_data = fixture.get("free_team_data") or {}
    if all(
        any(
            profile.get(field)
            for field in ("founded", "capacity", "city")
        )
        for side in ("home", "away")
        for profile in [((free_team_data.get(side) or {}).get("profile") or {})]
    ):
        return fixture
    enrich = getattr(schedule_provider, "enrich_fixtures", None)
    if not callable(enrich):
        return fixture
    try:
        enriched_rows = await enrich([fixture], max_teams=2)
    except Exception:
        return fixture
    enriched = enriched_rows[0] if enriched_rows else fixture
    if not enriched.get("free_team_data"):
        return fixture
    repository.upsert_fixture(enriched)
    return enriched


def _kickoff_started(fixture: dict) -> bool:
    try:
        kickoff = datetime.fromisoformat(str(fixture.get("kickoff") or "").replace("Z", "+00:00"))
    except ValueError:
        return True
    kickoff = kickoff.replace(tzinfo=UTC) if kickoff.tzinfo is None else kickoff.astimezone(UTC)
    return kickoff <= datetime.now(UTC)


def _fixture_evidence_summary(fixture: dict) -> dict:
    context = fixture.get("evidence") or {}
    recent_form = context.get("recent_form") or {}
    availability = context.get("availability") or {}
    teams = context.get("teams") or {}
    checks = {
        "recent_form": bool(recent_form.get("home") and recent_form.get("away")),
        "head_to_head": bool(context.get("head_to_head")),
        "availability": bool(availability.get("updated_at")),
        "team_info": bool(teams.get("home") and teams.get("away")),
    }
    timestamps = [
        context.get("synced_at"),
        recent_form.get("updated_at"),
        availability.get("updated_at"),
        (teams.get("home") or {}).get("updated_at"),
        (teams.get("away") or {}).get("updated_at"),
    ]
    return {
        "ready_count": sum(checks.values()),
        "total_count": len(checks),
        "missing": [key for key, ready in checks.items() if not ready],
        "updated_at": max((str(value) for value in timestamps if value), default=None),
    }


def _fixture_list_item(fixture: dict, prediction_fixture_ids: set[str]) -> dict:
    fields = (
        "id",
        "provider_id",
        "fixture_date",
        "league_key",
        "league",
        "kickoff",
        "status",
        "home_team",
        "away_team",
        "score",
        "venue",
        "lineup_confirmed",
        "is_demo",
    )
    fixture_date = fixture.get("fixture_date")
    if not fixture_date and fixture.get("kickoff"):
        try:
            fixture_date = datetime.fromisoformat(str(fixture["kickoff"]).replace("Z", "+00:00")).astimezone(CHINA_TZ).date().isoformat()
        except ValueError:
            fixture_date = None
    odds = (fixture.get("evidence") or {}).get("odds")
    odds_summary = None
    if isinstance(odds, dict):
        prices = {}
        for key in ("home", "draw", "away"):
            try:
                value = float(odds.get(key))
            except (TypeError, ValueError):
                continue
            if value > 1.0:
                prices[key] = round(value, 2)
        if len(prices) == 3:
            odds_summary = {
                **prices,
                "updated_at": odds.get("updated_at") or odds.get("captured_at"),
            }
    return {
        **{key: fixture.get(key) for key in fields},
        "fixture_date": fixture_date,
        "evidence_summary": _fixture_evidence_summary(fixture),
        "odds_summary": odds_summary,
        "has_prediction": str(fixture.get("id") or "") in prediction_fixture_ids,
    }


@app.get("/health")
def health() -> dict:
    """Expose runtime health and provider readiness."""

    sync = repository.fixture_sync()
    if sync:
        mode = "cached"
    elif settings.use_demo_data:
        mode = "demo"
    elif schedule_provider.configured:
        mode = "empty"
    else:
        mode = "unconfigured"
    standings_rows = repository.league_snapshots()
    dongqiudi_last_synced_at = max(
        ((item.get("dongqiudi_sync") or {}).get("last_synced_at") for item in repository.list_fixtures() if (item.get("dongqiudi_sync") or {}).get("last_synced_at")),
        default=None,
    )
    return {
        "status": "ok",
        "database_backend": repository.engine.dialect.name,
        "provider_configured": schedule_provider.configured,
        "evidence_provider_configured": api_football_evidence_provider.public_configured,
        "evidence_sources": list(MATCH_EVIDENCE_SOURCES),
        "schedule_provider": settings.schedule_provider,
        "dongqiudi_configured": dongqiudi_provider.configured,
        "dongqiudi_last_synced_at": dongqiudi_last_synced_at,
        "schedule_provider_configured": schedule_provider.configured,
        "mode": mode,
        "last_synced_at": sync["synced_at"] if sync else None,
        "standings_provider_configured": league_provider.configured,
        "deepseek_configured": settings.deepseek_enabled and deepseek_provider.configured,
        "deepseek_enabled": settings.deepseek_enabled,
        "deepseek_model": settings.deepseek_model,
        "chatgpt_configured": chatgpt_provider.configured,
        "chatgpt_model": settings.chatgpt_model,
        "simulated_bankroll_balance": bankroll_service.summary()["balance"],
        "automation_enabled": settings.automation_enabled,
        "automation_analysis_enabled": settings.automation_analysis_enabled,
        "standings_last_synced_at": max(
            (item.get("updated_at") for item in standings_rows if item.get("updated_at")),
            default=None,
        ),
    }


@app.get("/api/fixtures")
async def fixtures(
    date_filter: Annotated[Literal["yesterday", "today", "tomorrow", "upcoming", "history"], Query(alias="date")] = "today",
    league: str = "all",
    season: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """List cached fixtures for one browse view."""

    if league != "all":
        canonical_league = normalize_league_code(league)
        if canonical_league is None:
            canonical_league = schedule_provider.normalize_league_key(league)
        if canonical_league is None:
            raise HTTPException(status_code=400, detail="仅支持英超、西甲、中超、中国足协杯、欧冠、亚冠、世界杯、亚洲杯、欧洲杯、世预赛、亚洲预选赛、欧国联")
        league = canonical_league.casefold()
    now = datetime.now(CHINA_TZ).date()
    start_date: str | None
    end_date: str | None
    if date_from is not None or date_to is not None:
        start_date = date_from
        end_date = date_to
    elif date_filter == "today":
        start_date = end_date = now.isoformat()
    elif date_filter == "yesterday":
        start_date = end_date = (now - timedelta(days=1)).isoformat()
    elif date_filter == "tomorrow":
        start_date = end_date = (now + timedelta(days=1)).isoformat()
    elif date_filter == "upcoming":
        start_date = now.isoformat()
        end_date = (now + timedelta(days=6)).isoformat()
    else:
        start_date = None
        end_date = (now - timedelta(days=1)).isoformat()
    cached_rows = schedule_sync.cached_fixtures(start_date, end_date)
    if cached_rows is None:
        try:
            await schedule_sync.warm_cache()
        except Exception:
            # Let the normal freshness path produce the existing stale/error
            # contract when the cache backend is temporarily unavailable.
            pass
        cached_rows = schedule_sync.cached_fixtures(start_date, end_date)
    cached_state = schedule_sync.cached_state()
    if cached_rows is None or cached_state["status"] == "unconfigured":
        sync_state = await schedule_sync.ensure_fresh()
        cached_rows = schedule_sync.cached_fixtures(start_date, end_date)
        if cached_rows is None:
            cached_rows = repository.list_fixtures(start_date, end_date)
    else:
        sync_state = schedule_sync.cached_state()
        if sync_state["status"] != "fresh":
            schedule_sync.refresh_in_background()
    all_rows = deduplicate_fixtures(cached_rows)
    league_key = None if league == "all" else league
    rows = all_rows if league_key is None else [row for row in all_rows if row["league_key"] == league_key]
    if season is not None:
        rows = [row for row in rows if str(row.get("season") or "") == str(season)]
    if date_filter == "history":
        rows.reverse()

    league_counts = {
        key: sum(1 for row in all_rows if row["league_key"] == key)
        for key in schedule_provider.SUPPORTED_LEAGUE_KEYS
    }
    dongqiudi_last_synced_at = max(
        ((item.get("dongqiudi_sync") or {}).get("last_synced_at") for item in all_rows if (item.get("dongqiudi_sync") or {}).get("last_synced_at")),
        default=None,
    )

    sync = repository.fixture_sync()
    if not rows and not sync and settings.use_demo_data:
        rows = demo_fixtures(now)
        if date_filter == "today":
            rows = [item for item in rows if datetime.fromisoformat(item["kickoff"]).date() == now]
        elif date_filter == "yesterday":
            rows = [item for item in rows if datetime.fromisoformat(item["kickoff"]).date() == now - timedelta(days=1)]
        elif date_filter == "tomorrow":
            rows = [item for item in rows if datetime.fromisoformat(item["kickoff"]).date() == now + timedelta(days=1)]
        elif date_filter == "upcoming":
            rows = [item for item in rows if now <= datetime.fromisoformat(item["kickoff"]).date() <= now + timedelta(days=6)]
        else:
            rows = [item for item in rows if datetime.fromisoformat(item["kickoff"]).date() < now]
        if league_key:
            rows = [item for item in rows if item["league_key"] == league_key]
        mode = "demo"
    elif rows:
        mode = "cached"
    elif sync:
        mode = "empty"
    elif sync_state["status"] == "failed":
        mode = "error"
    elif schedule_provider.configured:
        mode = "empty"
    else:
        mode = "unconfigured"
    prediction_fixture_ids = repository.fixture_ids_with_current_predictions(
        DEFAULT_PROMPT_CONTRACT.version,
        settings.simulation_competition_id,
    )
    return public_payload({
        "items": [_fixture_list_item(row, prediction_fixture_ids) for row in rows],
        "mode": mode,
        "provider_configured": schedule_provider.configured,
        "evidence_provider_configured": api_football_evidence_provider.public_configured,
        "evidence_sources": list(MATCH_EVIDENCE_SOURCES),
        "schedule_provider": settings.schedule_provider,
        "schedule_provider_configured": schedule_provider.configured,
        "dongqiudi_configured": dongqiudi_provider.configured,
        "dongqiudi_last_synced_at": dongqiudi_last_synced_at,
        "sync_status": sync_state["status"],
        "league_counts": league_counts,
        "last_synced_at": sync["synced_at"] if sync else None,
    })


@app.get("/api/standings")
async def standings(
    league: Literal["all", "epl", "laliga", "csl", "cfa_cup", "ucl", "acl"] = "all",
) -> dict:
    """Return cached current-season tables with freshness metadata."""

    sync_state = await league_sync.ensure_fresh()
    items = repository.league_snapshots(None if league == "all" else league)
    return public_payload({
        "items": items,
        "sync_status": sync_state["status"],
        "source": "espn",
        "last_synced_at": sync_state["last_synced_at"],
    })


@app.get("/api/data-sources")
def data_sources() -> dict:
    """Return the configured P5 providers and their declared capabilities."""

    return public_payload(public_registry(p5_provider_registry))


@app.get("/api/models")
def models() -> dict:
    """Return the P10 model families and the versioned registry records."""

    families = [
        {"model_key": "baseline", "family": "Baseline", "model_version": BASELINE_VERSION},
        {"model_key": "elo", "family": "Elo", "model_version": ELO_PRIOR_VERSION},
        {"model_key": "poisson", "family": "Poisson", "model_version": POISSON_V2_VERSION},
        {"model_key": "dixon_coles", "family": "Dixon-Coles", "model_version": DIXON_COLES_VERSION},
        {"model_key": "deepseek", "family": "LLM", "model_version": f"deepseek:{deepseek_provider.model}"},
        {"model_key": "chatgpt", "family": "LLM", "model_version": f"chatgpt:{chatgpt_provider.model}"},
        {"model_key": "ensemble", "family": "Ensemble", "model_version": None},
        {"model_key": "calibrated_ensemble", "family": "Calibrated Ensemble", "model_version": None},
    ]
    records = model_registry_service.list()
    return {
        "families": families,
        "records": [record.as_dict() for record in records],
        "record_count": len(records),
        "champions": {
            record.model_key: record.as_dict()
            for record in {item.model_key: item for item in records if item.status in {"champion", "active"}}.values()
        }
        if records
        else {},
    }


@app.post("/api/admin/models/{model_key}/{model_version}/status", dependencies=[Depends(require_admin)])
def update_model_status(model_key: str, model_version: str, payload: dict) -> dict:
    """Transition a registered model through its lifecycle with gate evidence."""

    target_status = str(payload.get("status") or "")
    try:
        record = model_registry_service.transition(
            model_key,
            model_version,
            target_status,
            promotion_evidence=payload.get("promotion_evidence"),
        )
    except ModelRegistryError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"updated": record.as_dict()}


@app.get("/api/competitions")
def competitions() -> dict:
    """Return the P9 six-competition registry with real fixture coverage."""

    counts: dict[str, int] = {}
    latest_kickoffs: dict[str, str] = {}
    for fixture in repository.list_fixtures():
        definition = COMPETITION_REGISTRY.get(fixture.get("league_key"))
        if definition is None:
            continue
        counts[definition.key] = counts.get(definition.key, 0) + 1
        kickoff = str(fixture.get("kickoff") or "")
        if kickoff and kickoff > latest_kickoffs.get(definition.key, ""):
            latest_kickoffs[definition.key] = kickoff
    items = [
        {
            **definition.as_dict(),
            "fixture_count": counts.get(definition.key, 0),
            "latest_kickoff": latest_kickoffs.get(definition.key),
        }
        for definition in COMPETITION_REGISTRY.definitions()
    ]
    return {"items": items, "count": len(items), "total_fixture_count": sum(counts.values())}


@app.get("/api/data-sync/runs")
def data_sync_runs(
    provider_name: str | None = Query(default=None, alias="provider"),
    league: str | None = None,
    entity_type: str | None = None,
    limit: int = 100,
) -> dict:
    """List persisted P5 synchronization runs without starting a sync."""

    code = normalize_league_code(league) if league else None
    if league and code is None:
        raise HTTPException(status_code=400, detail="仅支持 CSL、EPL、LAL")
    reader = getattr(repository, "data_sync_runs", None)
    items = reader(provider_name, code, entity_type, limit) if callable(reader) else []
    return serialize_public({"items": items, "count": len(items), "is_simulated": False})


@app.get("/api/leagues")
def leagues() -> dict:
    """Return the P5 league registry with actual canonical fixture coverage."""

    coverage = historical_data_service.coverage()
    items = [
        {
            "code": code,
            "name": config["name"],
            "fixture_count": coverage["leagues"].get(code, 0),
            "limit": coverage["limits"]["per_league"],
        }
        for code, config in SUPPORTED_LEAGUES.items()
    ]
    return {"items": items, "count": len(items), "total_fixture_count": coverage["total"], "limits": coverage["limits"]}


@app.get("/api/team-form/{team_id}")
def team_form(
    team_id: str,
    as_of: str | None = None,
    league: str | None = None,
) -> dict:
    """Return deterministic overall/home/away form for one team as-of a cutoff."""

    code = normalize_league_code(league) if league else None
    if league and code is None:
        raise HTTPException(status_code=400, detail="仅支持 CSL、EPL、LAL")
    try:
        result = recent_form_service.team_form(team_id, as_of=as_of, league=code)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return serialize_public({**result, "is_simulated": False})


@app.get("/api/fixtures/history")
def historical_fixture_list(
    league: str | None = None,
    season: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
) -> dict:
    """List bounded historical fixtures from the canonical P5 dataset."""

    code = normalize_league_code(league) if league else None
    if league and code is None:
        raise HTTPException(status_code=400, detail="仅支持 CSL、EPL、LAL")
    rows = repository.list_fixtures(
        start_date=date_from,
        end_date=date_to,
        league_key=code.casefold() if code else None,
    )
    if season:
        rows = [row for row in rows if str(row.get("season") or "") == str(season)]
    rows = rows[: max(1, min(int(limit), 300))]
    return serialize_public({"items": rows, "count": len(rows), "coverage": historical_data_service.coverage(), "is_simulated": False})


@app.get("/api/backtest/three-leagues")
def three_league_backtest(
    start: str = "2000-01-01T00:00:00+00:00",
    end: str | None = None,
) -> dict:
    """Return independent CSL/EPL/LAL P4 rolling reports plus global context."""

    rows = repository.fixture_settlements(competition_id=settings.simulation_competition_id)
    report = run_three_league_backtest(
        rows,
        start=start,
        end=end or datetime.now(UTC).replace(microsecond=0).isoformat(),
        fixture_reader=repository.fixture,
    )
    return serialize_public(report)


def _evaluate_p6(league: str | None = None) -> dict:
    result = model_evaluation_service.evaluate(league=league)
    existing_reader = getattr(repository, "model_evaluation_experiment", None)
    existing = existing_reader(result["experiment_id"]) if callable(existing_reader) else None
    if existing is not None:
        return existing
    saver = getattr(repository, "save_model_evaluation", None)
    if callable(saver):
        return saver(result)
    return result


@app.get("/api/model-evaluation")
def model_evaluation(experiment_id: str | None = None, league: str | None = None) -> dict:
    """Return one deterministic P6 experiment, creating its read-only report if needed."""

    if experiment_id:
        reader = getattr(repository, "model_evaluation_experiment", None)
        result = reader(experiment_id) if callable(reader) else None
        if result is None:
            raise HTTPException(status_code=404, detail="Model evaluation experiment was not found")
    else:
        code = normalize_league_code(league) if league else None
        if league and code is None:
            raise HTTPException(status_code=400, detail="Only CSL, EPL, and LAL are supported")
        listing = getattr(repository, "model_evaluation_experiments", None)
        stored = listing(league=code or "ALL", limit=1) if callable(listing) else []
        if stored:
            result = stored[0]
        else:
            try:
                result = _evaluate_p6(league)
            except ValueError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
    return serialize_public(result)


@app.get("/api/model-evaluation/{experiment_id}")
def model_evaluation_detail(experiment_id: str) -> dict:
    reader = getattr(repository, "model_evaluation_experiment", None)
    result = reader(experiment_id) if callable(reader) else None
    if result is None:
        raise HTTPException(status_code=404, detail="Model evaluation experiment was not found")
    return serialize_public(result)


@app.get("/api/model-comparison")
def model_comparison(experiment_id: str | None = None) -> dict:
    if experiment_id:
        result = model_evaluation(experiment_id=experiment_id)
    else:
        listing = getattr(repository, "model_evaluation_experiments", None)
        latest = listing(limit=1) if callable(listing) else []
        result = serialize_public(latest[0]) if latest else serialize_public(_evaluate_p6())
    return {"experiment_id": result.get("experiment_id"), "reports": result.get("reports") or {}, "model_comparison": result.get("model_comparison") or {}, "leakage_audit": result.get("leakage_audit") or {}}


@app.get("/api/leagues/{league}/model-evaluation")
def league_model_evaluation(league: str) -> dict:
    try:
        result = _evaluate_p6(league)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    code = normalize_league_code(league)
    report = (result.get("reports") or {}).get(code or "")
    if report is None:
        raise HTTPException(status_code=404, detail="Model evaluation league report was not found")
    return serialize_public({"experiment_id": result.get("experiment_id"), **report})


@app.get("/api/leakage-audit")
def leakage_audit(experiment_id: str | None = None) -> dict:
    result = model_evaluation(experiment_id=experiment_id) if experiment_id else _evaluate_p6()
    return serialize_public(result.get("leakage_audit") or {})


@app.get("/api/teams/{league_key}/{team_id}")
async def team_detail(
    league_key: Literal["epl", "laliga", "csl"],
    team_id: str,
) -> dict:
    """Return current-season roster, player statistics, and match records."""

    await league_sync.ensure_fresh()
    league_rows = repository.league_snapshots(league_key)
    league_snapshot = league_rows[0] if league_rows else None
    if not league_snapshot:
        raise HTTPException(status_code=503, detail="Current league data is unavailable")
    standing = next(
        (
            row
            for row in league_snapshot.get("standings") or []
            if str((row.get("team") or {}).get("provider_id")) == team_id
        ),
        None,
    )
    if not standing:
        raise HTTPException(status_code=404, detail="Team is not in the current league table")
    season_year = int((league_snapshot.get("season") or {})["year"])
    state = await team_sync.ensure_fresh(league_key, team_id, season_year)
    if state["item"] is None:
        raise HTTPException(status_code=503, detail="Current team data is unavailable")
    item = state["item"]
    roster_context = {
        "squads": {"home": item.get("roster") or [], "away": []},
        "lineup": {"home_players": [], "away_players": []},
        "availability": {"players": []},
    }
    await player_name_service.enrich(roster_context, resolve_missing=True)
    item["roster"] = roster_context["squads"]["home"]
    return public_payload({"item": item, "sync_status": state["status"]})


@app.get("/api/fixtures/{fixture_id}")
async def fixture_detail(fixture_id: str) -> dict:
    """Return a fixture, its current evidence, and its latest prediction."""

    import time as _time

    cached_entry = _fixture_detail_cache.get(fixture_id)
    if cached_entry and _time.monotonic() - cached_entry[0] < FIXTURE_DETAIL_CACHE_TTL_SECONDS:
        return cached_entry[1]
    fixture = _public_fixture_for_detail(fixture_id)
    fixture = await _ensure_fixture_team_data(fixture)
    fixture_id = fixture["id"]
    evidence_error: str | None = None
    prediction_error: str | None = None
    predictions = {
        key: repository.latest_current(
            fixture_id,
            DEFAULT_PROMPT_CONTRACT.version,
            key,
            settings.simulation_competition_id,
        )
        for key in prediction_service.model_keys
    }
    prediction = predictions.get("deepseek") or next((item for item in predictions.values() if item), None)
    context = demo_context(fixture_id) if fixture["is_demo"] else fixture.get("evidence", unavailable_context())
    _restore_dongqiudi_odds_capture_time(fixture, context)
    localize_evidence_players(context)
    free_team_data = fixture.get("free_team_data") or {}
    for side in ("home", "away"):
        team = fixture[f"{side}_team"]
        free_data = free_team_data.get(side) or {}
        free_profile = free_data.get("profile") or {}
        existing_profile = context["teams"].get(side) or {}
        profile = {**free_profile, **existing_profile}
        context["teams"][side] = profile
        profile["name"] = profile.get("name") or team["name"]
        profile["original_name"] = profile.get("original_name") or team.get("original_name") or team["name"]
        profile["logo"] = profile.get("logo") or team.get("logo")
        profile["venue"] = profile.get("venue") or fixture.get("venue")
        if not context["squads"].get(side):
            context["squads"][side] = free_data.get("squad") or []
    await player_name_service.enrich(context, resolve_missing=False)
    value_cutoff = (
        prediction.get("prediction_cutoff_at") or prediction.get("created_at")
        if prediction
        else datetime.now(UTC)
    )
    await player_value_service.enrich(
        context,
        str(fixture.get("league_key") or ""),
        cutoff_at=value_cutoff,
    )
    apply_player_impact(context)
    shared_fixtures: list[dict] | None = None
    if fixture.get("status") == "scheduled" and not fixture.get("is_demo") and str(fixture.get("league_key") or "") in {"epl", "laliga"}:
        shared_fixtures = repository.list_fixtures()
    try:
        from .team_stats import attach_team_stats

        attach_team_stats(
            repository,
            fixture,
            context,
            prediction_timestamp=fixture.get("kickoff"),
            fixtures_rows=shared_fixtures,
        )
    except Exception:
        pass
    match_preview = _match_preview_context(fixture, all_fixtures=shared_fixtures)
    for key, item in list(predictions.items()):
        if item and not item.get("decision"):
            # 决策在预测生成时已持久化并随版本冻结；只有缺失决策快照的
            # 历史行才回填，避免每次打开页面用实时数据重算。
            predictions[key] = apply_market_decision(item, context)
    prediction = predictions.get("deepseek") or next((item for item in predictions.values() if item), None)
    model_bets = {}
    for key, item in predictions.items():
        linked_bet = repository.bet_for_prediction(item["id"]) if item else None
        model_bets[key] = linked_bet
        if item:
            item["execution"] = bankroll_service.execution_for_prediction(item, fixture)
    detail_payload = public_payload({
        "fixture": fixture,
        "context": context,
        "match_preview": match_preview,
        "prediction": prediction,
        "predictions": predictions,
        "bet": model_bets.get("deepseek") or next((item for item in model_bets.values() if item), None),
        "bets": model_bets,
        "competition_id": settings.simulation_competition_id,
        "capabilities": {
            "evidence_sync": api_football_evidence_provider.public_configured,
            "dongqiudi_sync": dongqiudi_provider.configured and bool((fixture.get("external_ids") or {}).get("dongqiudi") or str(fixture.get("id") or "").startswith("dongqiudi-")),
            "dongqiudi_last_synced_at": (fixture.get("dongqiudi_sync") or {}).get("last_synced_at"),
            "evidence_sources": list(MATCH_EVIDENCE_SOURCES),
            "deepseek": settings.deepseek_enabled and deepseek_provider.configured,
            "chatgpt": chatgpt_provider.configured,
        },
        "evidence_error": evidence_error,
        "prediction_error": prediction_error,
    })
    _fixture_detail_cache[fixture_id] = (_time.monotonic(), detail_payload)
    if len(_fixture_detail_cache) > 200:
        oldest = sorted(_fixture_detail_cache.items(), key=lambda item: item[1][0])[:50]
        for key, _ in oldest:
            _fixture_detail_cache.pop(key, None)
    return detail_payload


def _restore_dongqiudi_odds_capture_time(fixture: dict, context: dict) -> None:
    """Use the stored provider capture time for legacy odds without updated_at."""

    odds = context.get("odds")
    if not isinstance(odds, dict) or odds.get("updated_at") or odds.get("captured_at"):
        return
    raw_odds = ((fixture.get("dongqiudi") or {}).get("odds") or {})
    captured_at = raw_odds.get("captured_at") or raw_odds.get("updated_at")
    if captured_at:
        context["odds"] = {**odds, "updated_at": captured_at, "captured_at": captured_at}


@app.get("/api/bankroll")
def bankroll() -> dict:
    """Return simulated balance, profit, exposure, ROI, and drawdown."""

    return bankroll_service.summary()


@app.get("/api/bets")
def simulated_bets(
    status: Literal["all", "placed", "settled"] = "all",
    fixture_date: str | None = None,
    model: Literal["all", "deepseek", "chatgpt"] = "all",
) -> dict:
    """Return the simulated bet ledger; no real-money execution exists."""

    items = repository.bets(
        None if status == "all" else status,
        fixture_date,
        None if model == "all" else model,
        settings.simulation_competition_id,
    )
    return {"items": items, "count": len(items), "is_simulated": True}


@app.get("/api/executions")
def paper_executions(
    status: Literal["all", "PENDING", "EXECUTED", "CANCELLED", "REJECTED", "SETTLED"] = "all",
    fixture_date: str | None = None,
    model: Literal["all", "deepseek", "chatgpt"] = "all",
) -> dict:
    """Return the append-only paper execution ledger; no real execution exists."""

    reader = getattr(repository, "bet_executions", None)
    items = reader(
        None if status == "all" else status,
        fixture_date,
        None if model == "all" else model,
        settings.simulation_competition_id,
    ) if callable(reader) else []
    return {"items": items, "count": len(items), "is_simulated": True}


@app.get("/api/decisions")
def prediction_decisions(
    league: Literal["all", "epl", "laliga", "csl", "cfa_cup", "ucl", "acl"] = "all",
    fixture_date: str | None = None,
    model_version: str | None = None,
    model: Literal["all", "deepseek", "chatgpt"] = "all",
) -> dict:
    """Return one auditable decision row per latest fixture/model prediction."""

    rows = repository.current_prediction_decisions(
        DEFAULT_PROMPT_CONTRACT.version,
        fixture_date,
        None if league == "all" else league,
        model_version,
        None if model == "all" else model,
        settings.simulation_competition_id,
    )
    bet_reader = getattr(repository, "bets_for_predictions", None)
    linked_bets = (
        bet_reader(
            (row.get("prediction") or {}).get("id")
            for row in rows
        )
        if callable(bet_reader)
        else {}
    )
    items: list[dict] = []
    for row in rows:
        prediction = row.get("prediction") or {}
        fixture = row.get("fixture") or {}
        decision = prediction.get("decision") or {}
        linked_bet = linked_bets.get(str(prediction["id"]))
        if linked_bet:
            current_market = decision.get("market")
            current_selection = decision.get("selection")
            bet_matches = (
                current_market == linked_bet.get("market")
                and current_selection == linked_bet.get("selection")
            )
            execution = {
                "status": "bet",
                "reason": "已进入模拟组合" if bet_matches else "已有模拟单，但当前预测候选已变化，请核对",
                "bet_id": linked_bet["id"],
                "execution_id": linked_bet.get("execution_id"),
                "execution_status": "SETTLED" if linked_bet.get("status") == "settled" else "EXECUTED",
                "risk_gate": linked_bet.get("risk_gate"),
            }
        elif decision.get("status") in {"bet", "no_bet", "insufficient_data"}:
            if fixture:
                execution = bankroll_service.execution_for_prediction(
                    prediction,
                    fixture,
                    linked_bet=None,
                    bet_lookup_complete=True,
                )
            else:
                execution = {
                    "status": decision["status"],
                    "reason": decision.get("reason") or "暂无比赛缓存",
                    "bet_id": None,
                }
        else:
            execution = {
                "status": "unknown",
                "reason": "历史记录未保存决策快照",
                "bet_id": None,
            }
        experiment = prediction.get("experiment") or {}
        items.append(
            {
                "id": prediction.get("id"),
                "fixture_id": prediction.get("fixture_id"),
                "fixture_date": fixture.get("fixture_date"),
                "kickoff": fixture.get("kickoff"),
                "league_key": fixture.get("league_key"),
                "home_team": (fixture.get("home_team") or {}).get("name"),
                "away_team": (fixture.get("away_team") or {}).get("name"),
                "created_at": prediction.get("created_at"),
                "score": fixture.get("score"),
                "model_key": prediction.get("model_key") or experiment.get("model_key"),
                "model_version": prediction.get("model_version"),
                "strategy_id": experiment.get("strategy_id") or "baseline",
                "strategy_version": experiment.get("strategy_version") or "v1",
                "strategy_name": experiment.get("strategy_name") or "基准",
                "evidence_snapshot_id": prediction.get("evidence_snapshot_id"),
                "evidence_hash": prediction.get("evidence_hash"),
                "evidence_version": prediction.get("evidence_version") or (prediction.get("ai") or {}).get("evidence_version"),
                "odds_snapshot_id": prediction.get("odds_snapshot_id"),
                "model_probabilities": prediction.get("model_probabilities") or prediction.get("probabilities"),
                "forecast": prediction.get("forecast"),
                "decision_status": decision.get("status") or "unknown",
                "market": decision.get("market") or "no_bet",
                "selection": decision.get("selection") or "none",
                "considered_market": decision.get("considered_market"),
                "considered_selection": decision.get("considered_selection"),
                "price": decision.get("price"),
                "expected_edge": decision.get("expected_edge"),
                "stake_fraction": decision.get("stake_fraction") or 0.0,
                "reason_codes": decision.get("reason_codes") or [],
                "reason": decision.get("reason") or execution["reason"],
                "execution_status": execution["status"],
                "execution_reason": execution["reason"],
                "bet_id": execution.get("bet_id"),
                "execution_id": (
                    execution.get("execution_id")
                    or ((linked_bet or {}).get("execution_id") if linked_bet else None)
                ),
                "risk_gate": execution.get("risk_gate") or (linked_bet or {}).get("risk_gate"),
                "portfolio_candidate": prediction.get("portfolio_candidate") or execution.get("portfolio_candidate") or execution.get("candidate"),
                "model_recommendation_status": (prediction.get("model_recommendation") or {}).get("status"),
            }
        )
    return {"items": public_payload(items), "count": len(items), "is_simulated": True}


@app.get("/api/metrics/predictions")
def prediction_metrics(
    league: Literal["all", "epl", "laliga", "csl", "cfa_cup", "ucl", "acl"] = "all",
    season: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    model_version: str | None = None,
    model: Literal["all", "deepseek", "chatgpt"] = "all",
) -> dict:
    """Return filterable correctness and Brier score metrics."""

    return settlement_service.metrics(
        None if league == "all" else league,
        season,
        start_date,
        end_date,
        model_version,
        None if model == "all" else model,
        settings.simulation_competition_id,
    )


@app.get("/api/strategy-performance")
def strategy_performance(
    league: Literal["all", "epl", "laliga", "csl", "cfa_cup", "ucl", "acl"] = "all",
    season: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Return comparable model/strategy rows for the performance leaderboard."""

    rows: list[dict] = []
    for model_key in prediction_service.model_keys:
        report = settlement_service.metrics(
            None if league == "all" else league,
            season,
            start_date,
            end_date,
            None,
            model_key,
            settings.simulation_competition_id,
        )
        portfolio = report.get("portfolio") or {}
        betting = report.get("betting_performance") or portfolio
        comparison = report.get("market_comparison") or {}
        gate = report.get("quality_gate") or {}
        rows.append(
            {
                "model_key": model_key,
                "strategy_id": (report.get("experiment") or {}).get("strategy_id") or "baseline",
                "strategy_version": (report.get("experiment") or {}).get("strategy_version") or "v1",
                "strategy_name": (report.get("experiment") or {}).get("strategy_name") or "基准",
                "realized_pnl": portfolio.get("realized_pnl", 0.0),
                "roi": portfolio.get("roi", 0.0),
                "bets": betting.get("bets", 0),
                "wins": betting.get("wins", 0),
                "losses": betting.get("losses", 0),
                "stake": betting.get("stake", betting.get("settled_staked", 0.0)),
                "profit": betting.get("profit", betting.get("realized_pnl", 0.0)),
                "win_rate": betting.get("win_rate", 0.0),
                "prediction_samples": report.get("sample_size", 0),
                "market_comparison_samples": comparison.get("sample_size", 0),
                "average_brier": report.get("average_brier_score"),
                "average_log_loss": report.get("average_log_loss"),
                "brier_improvement": comparison.get("brier_improvement"),
                "clv_samples": portfolio.get("clv_samples", 0),
                "average_clv": portfolio.get("average_clv"),
                "max_drawdown": portfolio.get("max_drawdown", 0.0),
                "gate_status": gate.get("status", "INSUFFICIENT_SAMPLE"),
                "quality_state": gate.get("quality_state", "SHADOW"),
                "gate_mode": gate.get("mode", "SHADOW_ONLY"),
            }
        )
    rows.sort(key=lambda item: (-float(item.get("roi") or 0), -float(item.get("realized_pnl") or 0), str(item["model_key"])))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return {"items": rows, "count": len(rows), "ranking": "ROI_THEN_PNL", "is_simulated": True}


@app.get("/api/model-performance")
def model_performance(
    league: Literal["all", "epl", "laliga", "csl", "cfa_cup", "ucl", "acl"] = "all",
    season: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Return P3 dynamic model profiles derived from P1 evaluation rows."""

    rows = repository.fixture_settlements(
        None if league == "all" else league,
        season,
        start_date,
        end_date,
        competition_id=settings.simulation_competition_id,
    )
    profiles = build_performance_profiles(rows)
    return {"items": list(profiles.values()), "count": len(profiles), "is_simulated": True}


@app.get("/api/features")
def feature_snapshots(fixture_id: str | None = None) -> dict:
    """Return persisted P3 feature snapshots without changing predictions."""

    snapshot_reader = getattr(repository, "feature_snapshots", None)
    if callable(snapshot_reader):
        snapshots = snapshot_reader(fixture_id=fixture_id)
        items = [
            {
                "fixture_id": item.get("fixture_id"),
                "prediction_id": item.get("prediction_id"),
                "feature_snapshot_id": item.get("snapshot_id"),
                "feature_snapshot": item,
            }
            for item in snapshots
        ]
        return {"items": public_payload(items), "count": len(items), "is_simulated": True}
    if fixture_id:
        predictions = repository.current_predictions_for_fixture(
            fixture_id,
            DEFAULT_PROMPT_CONTRACT.version,
            settings.simulation_competition_id,
        )
        items = [
            {
                "fixture_id": fixture_id,
                "prediction_id": item.get("id"),
                "model_key": item.get("model_key"),
                "feature_snapshot": item.get("feature_snapshot"),
            }
            for item in predictions
            if item.get("feature_snapshot")
        ]
        return {"items": public_payload(items), "count": len(items), "is_simulated": True}
    rows = repository.current_prediction_decisions(
        DEFAULT_PROMPT_CONTRACT.version,
        competition_id=settings.simulation_competition_id,
    )
    items = [
        {
            "fixture_id": (row.get("prediction") or {}).get("fixture_id"),
            "prediction_id": (row.get("prediction") or {}).get("id"),
            "model_key": (row.get("prediction") or {}).get("model_key"),
            "feature_snapshot": (row.get("prediction") or {}).get("feature_snapshot"),
        }
        for row in rows
        if (row.get("prediction") or {}).get("feature_snapshot")
    ]
    return {"items": public_payload(items), "count": len(items), "is_simulated": True}


@app.get("/api/features/{fixture_id}")
def feature_snapshot(fixture_id: str) -> dict:
    """Return one fixture's versioned P3 features."""

    return feature_snapshots(fixture_id)


@app.get("/match/{fixture_id}/features")
def match_features(
    fixture_id: str,
    prediction_id: str | None = None,
    revision: int | None = None,
) -> dict:
    """Return the exact persisted Feature Engine v2 inputs for a match."""

    snapshot_reader = getattr(repository, "feature_snapshots", None)
    if not callable(snapshot_reader):
        raise HTTPException(status_code=404, detail="Feature snapshot was not found")
    if revision is not None and not prediction_id:
        raise HTTPException(status_code=400, detail="prediction_id is required when revision is provided")
    snapshots = snapshot_reader(fixture_id=fixture_id, prediction_id=prediction_id)
    audit_reader = getattr(repository, "leakage_audits", None)
    audits = audit_reader(prediction_id=prediction_id) if callable(audit_reader) else []
    audit_status = {
        str(audit.get("feature_snapshot_id") or ""): str(audit.get("status") or "").upper()
        for audit in audits
        if audit.get("feature_snapshot_id")
    }
    snapshots = [
        item
        for item in snapshots
        if item.get("feature_version") == "round3-feature-engine-v2"
        and audit_status.get(str(item.get("snapshot_id") or "")) == "PASS"
    ]
    if revision is not None and prediction_id:
        revision_reader = getattr(repository, "prediction_revision", None)
        selected_revision = revision_reader(prediction_id, revision) if callable(revision_reader) else None
        if selected_revision is None:
            raise HTTPException(status_code=404, detail="Prediction revision was not found")
        target_snapshot_id = (selected_revision or {}).get("feature_snapshot_id")
        snapshots = [item for item in snapshots if item.get("snapshot_id") == target_snapshot_id]
    if not snapshots:
        raise HTTPException(status_code=404, detail="Feature snapshot was not found")
    snapshot = snapshots[-1]
    registry_reader = getattr(repository, "feature_registry", None)
    definitions = registry_reader(status=None) if callable(registry_reader) else []
    definitions_by_id = {str(item.get("id") or ""): item for item in definitions}
    definitions_by_key = {
        (str(item.get("feature_name") or ""), str(item.get("calculation_version") or "")): item
        for item in definitions
    }
    enriched_features = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in snapshot.get("features") or []:
        definition = definitions_by_id.get(str(item.get("registry_id") or "")) or definitions_by_key.get(
            (str(item.get("feature_name") or ""), str(item.get("calculation_version") or ""))
        ) or {}
        enriched = {
            **item,
            "description": definition.get("description"),
            "formula": definition.get("formula"),
        }
        enriched_features.append(enriched)
        grouped.setdefault(str(item.get("feature_group") or definition.get("feature_group") or "unknown"), []).append(enriched)
    enriched_snapshot = {**snapshot, "features": enriched_features}
    return public_payload(
        {
            "fixture_id": fixture_id,
            "feature_snapshot_id": snapshot.get("snapshot_id"),
            "prediction_cutoff_at": snapshot.get("prediction_cutoff_at"),
            "feature_version": snapshot.get("feature_version"),
            "audit_status": "PASS",
            "groups": grouped,
            "feature_snapshot": enriched_snapshot,
        }
    )


@app.get("/match/{fixture_id}/probability")
def match_probability(
    fixture_id: str,
    feature_snapshot_id: str | None = None,
) -> dict:
    """Return Round 4 model and Round 5 market/final probabilities."""

    snapshot_reader = getattr(repository, "feature_snapshots", None)
    audit_reader = getattr(repository, "leakage_audits", None)
    if not callable(snapshot_reader) or not callable(audit_reader):
        raise HTTPException(status_code=404, detail="Feature snapshot was not found")
    snapshots = [
        item
        for item in snapshot_reader(fixture_id=fixture_id)
        if item.get("feature_version") == "round3-feature-engine-v2"
    ]
    audits = audit_reader()
    # Audits are append-only.  A historical PASS must not override a later
    # FAIL for the same immutable snapshot.
    latest_audit_status: dict[str, str] = {}
    ordered_audits = sorted(
        enumerate(audits),
        key=lambda pair: (
            str(pair[1].get("audited_at") or pair[1].get("created_at") or ""),
            pair[0],
        ),
    )
    for _, audit in ordered_audits:
        snapshot_key = str(audit.get("feature_snapshot_id") or "")
        if snapshot_key:
            latest_audit_status[snapshot_key] = str(audit.get("status") or "").upper()
    pass_ids = {
        snapshot_key for snapshot_key, status in latest_audit_status.items() if status == "PASS"
    }
    snapshots = [item for item in snapshots if str(item.get("snapshot_id") or "") in pass_ids]
    if feature_snapshot_id:
        snapshots = [
            item for item in snapshots
            if str(item.get("snapshot_id") or "") == str(feature_snapshot_id)
        ]
    else:
        snapshots.sort(key=lambda item: str(item.get("prediction_cutoff_at") or ""))
    if not snapshots:
        raise HTTPException(status_code=404, detail="Audit-passed feature snapshot was not found")
    snapshot = snapshots[-1]
    try:
        result = TransparentProbabilityEngine().calculate(
            snapshot,
            match_id=fixture_id,
            feature_snapshot_id=str(snapshot.get("snapshot_id") or ""),
        )
        odds_reader = getattr(repository, "odds_snapshots", None)
        odds_snapshots = odds_reader(fixture_id) if callable(odds_reader) else []
        fixture_reader = getattr(repository, "fixture", None)
        fixture = fixture_reader(fixture_id) if callable(fixture_reader) else None
        result.update(
            Round5ProbabilityEngine().calculate(
                result,
                odds_snapshots,
                kickoff=(fixture or {}).get("kickoff"),
            )
        )
    except (ProbabilityEngineError, MarketPriorError, NoMLNumericPathError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return public_payload(result)


@app.get("/api/ensemble/{fixture_id}")
def fixture_ensemble(fixture_id: str) -> dict:
    """Build one explainable P3 ensemble from current model predictions."""

    predictions = repository.current_predictions_for_fixture(
        fixture_id,
        DEFAULT_PROMPT_CONTRACT.version,
        settings.simulation_competition_id,
    )
    if not predictions:
        raise HTTPException(status_code=404, detail="Prediction was not found")
    rows = repository.fixture_settlements(competition_id=settings.simulation_competition_id)
    champion = model_registry_service.champion("ensemble")
    learned_weights = (champion.payload or {}).get("weights") if champion else None
    return public_payload(
        _ensemble_payload(
            fixture_id,
            predictions,
            settlement_rows=rows,
            learned_weights=learned_weights,
        )
    )


def _ensemble_payload(
    fixture_id: str,
    predictions: list[dict],
    *,
    settlement_rows: list[dict],
    learned_weights: dict | None,
) -> dict:
    base_predictions = {
        str(item.get("model_key") or (item.get("ai") or {}).get("provider") or "deepseek"): item.get("model_probabilities") or item.get("probabilities") or {}
        for item in predictions
    }
    baseline = next(
        (
            (item.get("baseline") or {}).get("probabilities")
            for item in predictions
            if (item.get("baseline") or {}).get("probabilities")
        ),
        None,
    )
    if baseline:
        base_predictions["poisson"] = baseline
    ensemble = weighted_ensemble(
        base_predictions,
        weights=learned_weights,
        profiles=build_performance_profiles(settlement_rows),
        league_key=(predictions[0].get("league_key") or "") if predictions else None,
    )
    directions = {
        model: max(probabilities, key=probabilities.get)
        for model, probabilities in (ensemble.get("base_predictions") or {}).items()
        if probabilities
    }
    agreement = (
        {"status": "insufficient_members", "directions": directions}
        if len(directions) < 2
        else {
            "status": "agree" if len(set(directions.values())) == 1 else "disagree",
            "directions": directions,
        }
    )
    profile_weighted = any(
        scope != "baseline" for scope in (ensemble.get("profile_scopes") or {}).values()
    )
    return {
        "fixture_id": fixture_id,
        "ensemble": ensemble,
        "available_members": sorted((ensemble.get("base_predictions") or {}).keys()),
        "agreement": agreement,
        "weights_source": (
            "model_registry"
            if learned_weights
            else "performance_profiles"
            if profile_weighted
            else "defaults"
        ),
    }


@app.get("/api/ensemble")
def ensemble_summary(
    fixture_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    """Return one requested ensemble or real current fixture summaries."""

    if fixture_id:
        return fixture_ensemble(fixture_id)
    now = datetime.now(UTC)
    fixtures = []
    for fixture in repository.list_fixtures():
        kickoff = parse_timestamp(fixture.get("kickoff"))
        if fixture.get("status") != "scheduled" or kickoff is None or kickoff < now:
            continue
        fixtures.append(fixture)
    fixtures.sort(key=lambda item: str(item.get("kickoff") or ""))
    settlement_rows = repository.fixture_settlements(
        competition_id=settings.simulation_competition_id
    )
    champion = model_registry_service.champion("ensemble")
    learned_weights = (champion.payload or {}).get("weights") if champion else None
    items = []
    for fixture in fixtures:
        current_id = str(fixture.get("id") or "")
        predictions = repository.current_predictions_for_fixture(
            current_id,
            DEFAULT_PROMPT_CONTRACT.version,
            settings.simulation_competition_id,
        )
        if not predictions:
            continue
        summary = _ensemble_payload(
            current_id,
            predictions,
            settlement_rows=settlement_rows,
            learned_weights=learned_weights,
        )
        summary.update(
            {
                "kickoff": fixture.get("kickoff"),
                "league_key": fixture.get("league_key"),
                "home_team": fixture.get("home_team"),
                "away_team": fixture.get("away_team"),
                "prediction_created_at": max(
                    (str(item.get("created_at") or "") for item in predictions),
                    default="",
                ),
                "readiness_reasons": (
                    []
                    if summary["ensemble"].get("status") == "ok"
                    else ["no_usable_model_probabilities"]
                ),
            }
        )
        items.append(summary)
    items.sort(key=lambda item: item["prediction_created_at"], reverse=True)
    items = items[:limit]
    return public_payload(
        {
            "items": items,
            "count": len(items),
            "is_simulated": False,
            "empty_reason": None if items else "no_eligible_current_predictions",
        }
    )


@app.get("/api/calibration")
def calibration_state() -> dict:
    """Return the current out-of-sample calibration availability."""

    rows = repository.fixture_settlements(competition_id=settings.simulation_competition_id)
    result = run_backtest(rows)
    return {"calibration": result.get("calibration"), "is_simulated": True}


@app.get("/api/backtest")
def prediction_backtest() -> dict:
    """Return the honest P3 baseline/ensemble backtest and ablation report."""

    rows = repository.fixture_settlements(competition_id=settings.simulation_competition_id)
    return public_payload(run_backtest(rows))


@app.get("/api/backtest/runs")
def historical_backtest_runs(status: str | None = None, limit: int = 100) -> dict:
    """List persisted P4 backtest runs; this endpoint never starts a run."""

    reader = getattr(repository, "backtest_runs", None)
    items = reader(status, limit) if callable(reader) else []
    items = [_public_backtest_run(item) for item in items]
    return serialize_public(
        {
            "items": items,
            "count": len(items),
            "is_simulated": all(item["is_simulated"] for item in items),
        }
    )


@app.get("/api/backtest/runs/{run_id}")
def historical_backtest_run(run_id: str) -> dict:
    """Return one persisted P4 backtest run."""

    reader = getattr(repository, "backtest_run", None)
    item = reader(run_id) if callable(reader) else None
    if item is None:
        raise HTTPException(status_code=404, detail="Backtest run was not found")
    item = _public_backtest_run(item)
    return serialize_public({"item": item, "is_simulated": item["is_simulated"]})


def _public_backtest_run(item: dict) -> dict:
    public = dict(item)
    config = item.get("config") if isinstance(item.get("config"), dict) else {}
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    is_round6 = (
        str(item.get("run_id") or "").startswith("round6:")
        or item.get("code_version") == BACKTEST_VERSION
        or config.get("backtest_version") == BACKTEST_VERSION
        or payload.get("backtest_version") == BACKTEST_VERSION
    )
    public["is_simulated"] = (
        False if is_round6 else bool(item.get("is_simulated", True))
    )
    return public


@app.post("/api/admin/backtest/runs", dependencies=[Depends(require_admin)])
def run_advanced_backtest(payload: dict) -> dict:
    """Run one reproducible P12 backtest and persist its immutable manifest."""

    settlements = repository.fixture_settlements(competition_id=settings.simulation_competition_id)
    source = payload.get("source")
    if source:
        settlements = filter_settlement_rows_by_source(
            settlements,
            source=str(source),
            fixture_reader=getattr(repository, "fixture", None),
        )
    try:
        result = run_backtest_engine(
            settlements,
            mode=str(payload.get("mode") or "rolling"),
            start=payload.get("start"),
            end=payload.get("end"),
            initial_train_days=int(payload.get("initial_train_days") or 180),
            train_days=int(payload.get("train_days") or 180),
            test_days=int(payload.get("test_days") or 30),
            step_days=int(payload.get("step_days") or 30),
            seed=int(payload.get("seed") or 20260913),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    result.pop("_test_probabilities", None)
    audit = audit_research_rows(build_backtest_rows(settlements))
    result["leakage_audit"] = audit
    manifest = result.get("manifest") or {}
    rejection_reasons = []
    insufficient_sample = (
        result.get("status") != "ok"
        or not result.get("window_count")
        or not result.get("sample_size")
    )
    if insufficient_sample:
        rejection_reasons.append("insufficient_evaluation_sample")
    if not audit.get("passed"):
        rejection_reasons.append("leakage_audit_failed")
    if not manifest:
        rejection_reasons.append("manifest_unavailable")
    if rejection_reasons:
        return {
            "run_id": None,
            "status": "insufficient_data" if insufficient_sample else "rejected",
            "reason_codes": rejection_reasons,
            "result": result,
        }
    run_id = f"backtest:{str(manifest['manifest_fingerprint']).removeprefix('manifest:')}"
    existing = next(
        (row for row in repository.backtest_runs(limit=200) if row["run_id"] == run_id),
        None,
    )
    if existing:
        return {"run_id": run_id, "reused": True, "run": existing}
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    run = {
        "run_id": run_id,
        "name": f"p12-{manifest['mode']}",
        "started_at": now,
        "finished_at": now,
        "dataset_version": manifest.get("dataset_fingerprint"),
        "run_config": manifest.get("params") or {},
        "code_version": manifest.get("engine_version"),
        "model_version": manifest.get("model_version"),
        "feature_version": manifest.get("feature_version"),
        "ensemble_version": manifest.get("ensemble_version"),
        "calibration_version": manifest.get("calibration_version"),
        "status": result.get("status") or "completed",
        "payload": result,
    }
    repository.save_backtest_run(run)
    return {"run_id": run_id, "reused": False, "run": run}


def _round6_probability_report(
    *,
    start: str | None,
    end: str | None,
    league: str | None,
    limit: int,
) -> dict:
    offsets = []
    for raw in str(settings.prediction_refresh_offsets_hours).split(","):
        try:
            value = float(raw.strip())
        except (TypeError, ValueError):
            continue
        if value > 0:
            offsets.append(value)
    return TemporalBacktestService(
        repository,
        cutoff_offsets_hours=offsets,
    ).run(
        start_date=start,
        end_date=end,
        league_key=league,
        limit=limit,
    )


@app.get(
    "/api/admin/backtest/probability",
    dependencies=[Depends(require_admin)],
)
def round6_probability_backtest(
    query: Annotated[Round6ProbabilityBacktestQuery, Query()],
) -> dict:
    """Read persisted Round 5 audits through the evaluation-only Round 6 path."""

    return serialize_public(
        _round6_probability_report(**query.model_dump())
    )


def _persist_round6_backtest_run(run: dict) -> dict:
    existing = repository.backtest_run(run["run_id"])
    if existing is not None:
        if existing != run:
            raise HTTPException(
                status_code=409,
                detail="Round 6 run_id exists with different immutable content",
            )
        return {"run_id": run["run_id"], "reused": True, "run": existing}

    try:
        stored = repository.save_backtest_run(run)
    except ValueError as error:
        concurrent = repository.backtest_run(run["run_id"])
        if concurrent is None or concurrent != run:
            raise HTTPException(
                status_code=409,
                detail="Round 6 run_id exists with different immutable content",
            ) from error
        return {"run_id": run["run_id"], "reused": True, "run": concurrent}

    if stored is None:
        return {"run_id": run["run_id"], "reused": False, "run": run}
    if stored != run:
        raise HTTPException(
            status_code=409,
            detail="Round 6 run_id exists with different immutable content",
        )
    return {
        "run_id": run["run_id"],
        "reused": stored is not run,
        "run": stored,
    }


@app.post(
    "/api/admin/backtest/probability",
    dependencies=[Depends(require_admin)],
)
def persist_round6_probability_backtest(
    payload: Round6ProbabilityBacktestRequest,
) -> dict:
    """Explicitly persist one content-addressed Round 6 evaluation report."""

    report = _round6_probability_report(**payload.model_dump())
    if report.get("status") != "ok":
        return {
            "run_id": None,
            "reused": False,
            "status": "insufficient_data",
            "reason": "Round 6 eligibility gates did not pass",
            "report": report,
        }
    run = build_round6_backtest_run(report)
    return _persist_round6_backtest_run(run)


@app.get("/api/historical-snapshots")
def historical_snapshots(
    fixture_id: str | None = None,
    as_of: str | None = None,
    limit: int = 200,
) -> dict:
    """List immutable historical snapshots at or before an optional timestamp."""

    reader = getattr(repository, "historical_snapshots", None)
    items = reader(fixture_id, as_of, limit) if callable(reader) else []
    return serialize_public({"items": items, "count": len(items), "is_simulated": True})


@app.post("/api/admin/research/runs", dependencies=[Depends(require_admin)])
def create_research_run(payload: dict) -> dict:
    """Run one P14 research pipeline and archive an immutable, content-addressed run."""

    try:
        hypothesis = validate_hypothesis(
            statement=str(payload.get("hypothesis") or payload.get("statement") or ""),
            kind=str(payload.get("kind") or "exploratory"),
            selection_rule=payload.get("selection_rule"),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    settlements = repository.fixture_settlements(competition_id=settings.simulation_competition_id)
    source = payload.get("source")
    if source:
        settlements = filter_settlement_rows_by_source(
            settlements,
            source=str(source),
            fixture_reader=getattr(repository, "fixture", None),
        )
    run = run_research(
        settlements,
        hypothesis=hypothesis,
        mode=str(payload.get("mode") or "rolling"),
        train_days=int(payload.get("train_days") or 180),
        test_days=int(payload.get("test_days") or 30),
        step_days=int(payload.get("step_days") or 30),
        seed=int(payload.get("seed") or 20260913),
        minimum_samples=int(payload.get("minimum_samples") or 30),
        job_id=payload.get("job_id"),
        created_by=str(payload.get("created_by") or "admin"),
        repository=repository,
    )
    return run


@app.get("/api/research/runs")
def research_runs(status: str | None = None, limit: int = 100) -> dict:
    """List archived research runs (reports trace back to their source run)."""

    reader = getattr(repository, "research_runs", None)
    items = reader(status, limit) if callable(reader) else []
    return serialize_public({"items": items, "count": len(items), "is_simulated": False})


@app.get("/api/research/runs/{run_id}")
def research_run(run_id: str) -> dict:
    """Return one research run with its full report."""

    reader = getattr(repository, "research_run", None)
    item = reader(run_id) if callable(reader) else None
    if item is None:
        raise HTTPException(status_code=404, detail="Research run was not found")
    return serialize_public({"item": item, "is_simulated": False})


@app.post("/api/admin/model-fitting/run", dependencies=[Depends(require_admin)])
def run_model_fitting(min_matches: int = 30) -> dict:
    """Fit Dixon-Coles rho and league xG baselines; register the artifact."""

    fitted = fit_from_repository(repository, min_matches=min_matches)
    if not fitted.get("fitted_version"):
        raise HTTPException(status_code=400, detail="历史样本不足，无法拟合")
    repository.save_model_registry(fitted_record(fitted))
    return fitted


@app.post("/api/admin/football-data/sync", dependencies=[Depends(require_admin)])
async def sync_football_data_season(division: str, season: int) -> dict:
    """Ingest one Football-Data.co.uk season (results + closing odds)."""

    if division not in {"epl", "laliga"}:
        raise HTTPException(status_code=400, detail="仅支持 epl / laliga")
    csv_text = await fetch_season_csv(division, season)
    if csv_text is None:
        raise HTTPException(status_code=404, detail="该赛季 CSV 尚未发布")
    result = sync_season(repository, csv_text, division, season, chinese_name=to_chinese_team_name)
    repository.save_sync_marker(f"fd:{division}:{season}", int(result.get("matches") or 0))
    return result


@app.post("/api/admin/clubeelo/sync", dependencies=[Depends(require_admin)])
async def sync_clubeelo() -> dict:
    """Refresh ClubElo ratings (free API, no key)."""

    return await refresh_clubeelo_ratings(
        repository,
        clubeelo_provider,
        localize=to_chinese_team_name,
    )


@app.post("/api/admin/discipline/sync", dependencies=[Depends(require_admin)])
async def sync_discipline_endpoint(limit: int = 25) -> dict:
    """Backfill card events onto finished fixtures via API-Football."""

    from .discipline_sync import sync_discipline

    return await sync_discipline(repository, provider, limit=limit, localize=to_chinese_team_name)


@app.post("/api/admin/transfers/sync", dependencies=[Depends(require_admin)])
async def sync_transfers_endpoint(limit: int = 6) -> dict:
    """Refresh transfer records with Dongqiudi first and API-Football fallback."""

    from .transfers_sync import sync_transfers

    return await sync_transfers(
        repository,
        provider,
        dongqiudi_provider=dongqiudi_provider,
        limit=limit,
    )


@app.post("/api/admin/weather/sync", dependencies=[Depends(require_admin)])
async def sync_weather_endpoint(limit: int = 30) -> dict:
    """Refresh kickoff forecasts for upcoming fixtures (Open-Meteo)."""

    return await sync_weather(
        repository,
        WeatherProvider(),
        horizon_days=int(getattr(settings, "weather_horizon_days", 7)),
        limit=limit,
        stale_after_hours=int(getattr(settings, "weather_stale_hours", 6)),
    )


@app.post("/api/admin/player-stats/sync", dependencies=[Depends(require_admin)])
async def sync_player_stats_endpoint(limit: int = 8) -> dict:
    """Refresh season player statistics for the next stale teams (ESPN)."""

    return await sync_player_stats(repository, team_provider, limit=limit)


@app.post("/api/admin/match-stats/sync", dependencies=[Depends(require_admin)])
async def sync_match_stats_endpoint(limit: int = 25) -> dict:
    """Backfill shots/SOT/corners onto finished fixtures via API-Football."""

    return await sync_match_stats(repository, provider, limit=limit, localize=to_chinese_team_name)


@app.post("/api/admin/understat/sync", dependencies=[Depends(require_admin)])
async def sync_understat(league: str, season: int) -> dict:
    """Enrich finished fixtures with Understat per-match xG/xPoints."""

    if league not in UNDERSTAT_LEAGUE_MAP:
        raise HTTPException(status_code=400, detail="仅支持 epl / laliga")
    data = await fetch_understat_league_data(league, season)
    if data is None:
        raise HTTPException(status_code=404, detail="该赛季 Understat 数据不可用")
    return sync_understat_xg(repository, data, league, localize=to_chinese_team_name)


@app.get("/api/admin/model-fitting/active", dependencies=[Depends(require_admin)])
def active_fitted_params() -> dict:
    """Return the fitted parameters currently injected into predictions."""

    return {"active": load_fitted_params(repository)}


@app.get("/api/production/readiness", dependencies=[Depends(require_admin)])
def production_readiness() -> dict:
    """P15 deployment gate: environment contract, migrations, smoke checks."""

    return _production_readiness_payload()


def _production_readiness_payload() -> dict:
    """Build the deployment gate without triggering any durable writes."""

    contract = EnvironmentContract(settings.environment)
    violations = contract.validate(_settings_view(settings))
    migration_status = run_migrations(repository, dry_run=True)
    smoke = run_smoke_checks(repository, settings)
    return {
        "environment": settings.environment,
        "is_production": contract.is_production,
        "config_violations": violations,
        "migration_dry_run": migration_status,
        "smoke": smoke,
        "status": "ready" if not violations and smoke["status"] == "pass" and migration_status["status"] in {"validated", "not_supported"} else "blocked",
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }


@app.get("/api/admin/activation-status", dependencies=[Depends(require_admin)])
def activation_status() -> dict:
    """Compose the read-only activation state for the existing admin surface."""

    now = datetime.now(UTC)
    readiness = _production_readiness_payload()
    backup = mysql_backup_verification_status(settings.mysql_backup_verification_file)
    fixtures = repository.list_fixtures()
    upcoming = [
        item
        for item in fixtures
        if item.get("status") == "scheduled"
        and (kickoff := parse_timestamp(item.get("kickoff"))) is not None
        and kickoff >= now
    ]
    upcoming_ids = {str(item.get("id") or "") for item in upcoming}
    impact_rules = repository.player_impact_rules(status="active")
    covered_fixture_ids = {
        str(item.get("fixture_id") or "")
        for item in impact_rules
        if str(item.get("fixture_id") or "") in upcoming_ids
    }
    coverage_status = (
        "not_applicable"
        if not upcoming_ids
        else "ready"
        if len(covered_fixture_ids) == len(upcoming_ids)
        else "partial"
        if covered_fixture_ids
        else "pending"
    )

    sync_runs = repository.data_sync_runs(limit=300)
    conflicts = repository.fixture_conflicts(limit=200)
    telemetry = provider_reliability(sync_runs, fixture_conflicts=conflicts)

    def operation_source(job_key: str, label: str, *, source_key: str | None = None) -> dict:
        run = repository.last_job_run(job_key)
        key = source_key or job_key
        if run is None:
            return {"key": key, "label": label, "status": "not_run", "last_run_at": None, "error": None}
        status = str(run.get("status") or "unknown")
        return {
            "key": key,
            "label": label,
            "status": "ready" if status == "success" else status,
            "last_run_at": run.get("finished_at") or run.get("started_at"),
            "error": run.get("error_summary"),
            "details": run.get("result") if isinstance(run.get("result"), dict) else None,
        }

    sources = [
        operation_source("clubeelo", "ClubElo"),
        operation_source("transfers_backfill", "转会数据"),
        operation_source("player_stats_backfill", "球员统计"),
        operation_source("player_values_backfill", "球员身价", source_key="player_values"),
        operation_source("lineup", "阵容数据"),
        {
            "key": "prematch_news",
            "label": "赛前新闻",
            "status": "unavailable",
            "reason": "provider_required",
            "last_run_at": None,
            "error": None,
        },
    ]
    ensemble = ensemble_summary(limit=20)
    backtests = repository.backtest_runs(limit=5)
    all_research = repository.research_runs(limit=500)
    research = all_research[:5]
    passing_backtests = [item for item in backtests if item.get("status") in {"ok", "completed", "passed"}]
    passing_research = [item for item in all_research if item.get("status") == "completed"]
    exploratory_research = [
        item
        for item in passing_research
        if item.get("exploratory") is True or (item.get("hypothesis") or {}).get("kind") == "exploratory"
    ]
    confirmatory_research = [
        item
        for item in passing_research
        if item.get("exploratory") is False or (item.get("hypothesis") or {}).get("kind") == "confirmatory"
    ]

    blockers = list(readiness.get("config_violations") or [])
    if readiness.get("status") != "ready" and not blockers:
        blockers.append("production_readiness_failed")
    if readiness.get("is_production") and backup.get("status") != "verified":
        blockers.append("mysql_backup_restore_not_verified")
    attention = []
    if coverage_status in {"pending", "partial"}:
        attention.append("player_impact_coverage_incomplete")
    if not ensemble.get("items"):
        attention.append("ensemble_predictions_unavailable")
    if not passing_backtests:
        attention.append("backtest_run_unavailable")
    if not passing_research:
        attention.append("research_run_unavailable")
    actionable_sources = [item for item in sources if item.get("reason") != "provider_required"]
    if any(item.get("status") in {"failed", "partial", "not_run"} for item in actionable_sources):
        attention.append("provider_operations_need_attention")

    return public_payload(
        {
            "status": "blocked" if blockers else "attention" if attention else "ready",
            "checked_at": now.replace(microsecond=0).isoformat(),
            "blocking_reasons": blockers,
            "attention_reasons": attention,
            "database": {
                "backend": repository.engine.dialect.name,
                "status": "ready" if repository.engine.dialect.name == "mysql" else "test_only",
                "migration": readiness["migration_dry_run"],
                "backup": backup,
                "service_readiness": readiness,
            },
            "player_impact": {
                "status": coverage_status,
                "active_rule_count": len(impact_rules),
                "upcoming_fixture_count": len(upcoming_ids),
                "covered_fixture_count": len(covered_fixture_ids),
            },
            "providers": {"sources": sources, "telemetry": telemetry},
            "ensemble": {
                "status": "ready" if ensemble.get("items") else "pending",
                "count": int(ensemble.get("count") or 0),
                "empty_reason": ensemble.get("empty_reason"),
                "items": ensemble.get("items") or [],
            },
            "evaluation": {
                "status": "ready" if passing_backtests and passing_research else "pending",
                "backtests": {"passing_count": len(passing_backtests), "recent": backtests},
                "research": {
                    "passing_count": len(passing_research),
                    "exploratory_count": len(exploratory_research),
                    "confirmatory_count": len(confirmatory_research),
                    "recent": research,
                },
            },
        }
    )


@app.post("/api/admin/production/migrations/dry-run", dependencies=[Depends(require_admin)])
def migration_dry_run() -> dict:
    """Validate pending additive migrations without committing them."""

    return run_migrations(repository, dry_run=True)


@app.post("/api/admin/production/migrations/apply", dependencies=[Depends(require_admin)])
def migration_apply() -> dict:
    """Apply pending versioned migrations (additive only; backup first)."""

    return run_migrations(repository, dry_run=False)


@app.post("/api/admin/production/backup", dependencies=[Depends(require_admin)])
def production_backup() -> dict:
    """Report the latest server-side MySQL restore verification."""

    return mysql_backup_verification_status(settings.mysql_backup_verification_file)


@app.post("/api/admin/production/smoke", dependencies=[Depends(require_admin)])
def production_smoke() -> dict:
    """Run the automated production smoke checks."""

    return run_smoke_checks(repository, settings)


@app.get("/api/admin/observability", dependencies=[Depends(require_admin)])
def admin_observability() -> dict:
    """P16 observability: SLO catalog, live state, alerts and request metrics."""

    state = observe_system_state(repository, settings, request_metrics=request_metrics)
    return {
        **state,
        "slo_catalog": list(SLO_CATALOG),
        "alerts": evaluate_alerts(state),
        "alert_rules": list(ALERT_RULES),
        "runbook": "docs/RUNBOOKS.md",
    }


@app.get("/api/platform")
def platform() -> dict:
    """P17 platform map: domain boundaries, surfaces and season binding."""

    from .platform_kit import (
        DOMAIN_MAP,
        PLATFORM_VERSION,
        PRODUCT_SURFACES,
        audit_season_binding,
    )

    snapshots = repository.historical_snapshots(limit=200) if callable(getattr(repository, "historical_snapshots", None)) else []
    return {
        "platform_version": PLATFORM_VERSION,
        "domain_map": list(DOMAIN_MAP),
        "surfaces": list(PRODUCT_SURFACES),
        "season_binding_audit": audit_season_binding(snapshots),
        "governance": {
            "adrs": "docs/adr/",
            "point_in_time": "prediction_timestamp < kickoff; captured_at <= prediction_timestamp",
            "extension_rule": "new competition = registry definition + provider + platform kit checks; new semantics require an ADR",
            "release_checklist": "docs/RELEASE_CHECKLIST.md",
        },
    }


@app.get("/api/data-quality")
def historical_data_quality(
    fixture_id: str | None = None,
    as_of: str | None = None,
    league: str | None = None,
) -> dict:
    """Return explicit quality checks for cached fixtures without altering forecasts."""

    code = normalize_league_code(league) if league else None
    if league and code is None:
        raise HTTPException(status_code=400, detail="仅支持 CSL、EPL、LAL")
    fixture_reader = getattr(repository, "fixture", None)
    if fixture_id and callable(fixture_reader):
        fixtures = [fixture_reader(fixture_id)]
    else:
        fixtures = repository.list_fixtures()
    fixtures = [fixture for fixture in fixtures if fixture]
    if code:
        fixtures = [fixture for fixture in fixtures if normalize_league_code(fixture.get("canonical_league") or fixture.get("league_key")) == code]
    items = []
    for fixture in fixtures:
        current_id = str(fixture.get("id") or "")
        odds_reader = getattr(repository, "odds_snapshots", None)
        odds = odds_reader(current_id) if callable(odds_reader) else []
        quality = assess_data_quality(
            fixture,
            evidence=fixture.get("evidence"),
            odds_snapshots=odds,
            result=fixture.get("score"),
            as_of=as_of,
            require_result=False,
            require_odds=False,
        )
        items.append({"fixture_id": current_id, **quality})
    return serialize_public({"items": items, "count": len(items), "is_simulated": True})


@app.get("/api/admin/provider-health", dependencies=[Depends(require_admin)])
def admin_provider_health(limit: int = 300) -> dict:
    """Return per-provider freshness, coverage, error and conflict telemetry."""

    runs = repository.data_sync_runs(limit=limit) if callable(getattr(repository, "data_sync_runs", None)) else []
    conflicts = repository.fixture_conflicts(limit=200) if callable(getattr(repository, "fixture_conflicts", None)) else []
    return {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "competitions": COMPETITION_REGISTRY.as_dict(),
        "providers": provider_reliability(runs, fixture_conflicts=conflicts),
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "sync_run_window": {"limit": limit, "returned": len(runs)},
    }


@app.get("/api/admin/jobs", dependencies=[Depends(require_admin)])
def automation_jobs(job_name: str | None = None, limit: int = 50) -> dict:
    """Return recent durable automation run history."""

    items = repository.job_runs(job_name, limit)
    return {
        "items": items,
        "count": len(items),
        "enabled": settings.automation_enabled,
        "analysis_enabled": settings.automation_analysis_enabled,
    }


@app.post("/api/admin/jobs/{job_name}/run", dependencies=[Depends(require_admin)])
async def run_automation_job(job_name: str, force: bool = False) -> dict:
    """Force one known automation job while preserving normal run history."""

    try:
        return await automation_runner.run_job(job_name, force=force)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/admin/free-llm/probe", dependencies=[Depends(require_admin)])
async def probe_free_llm() -> dict:
    """Probe every free-LLM chain link with a tiny chat request."""

    candidates = deepseek_chain_provider._candidates()
    report = await probe_chain(candidates)
    return {"items": report, "count": len(report)}


@app.get("/api/admin/model-config", dependencies=[Depends(require_admin)])
def admin_model_config() -> dict:
    """Return the editable runtime model and paper-portfolio configuration."""

    return _runtime_config_payload()


@app.put("/api/admin/model-config", dependencies=[Depends(require_admin)])
def update_admin_model_config(payload: RuntimeConfigUpdate) -> dict:
    """Apply model provider and paper-portfolio changes to the current process."""

    global runtime_config_updated_at
    for model_key, patch in payload.models.items():
        _update_model_provider(model_key, patch)
    if payload.portfolio is not None:
        policy_updates = payload.portfolio.model_dump(exclude_none=True)
        for field, value in policy_updates.items():
            setattr(settings, f"portfolio_{field}", value)
        for service in bankroll_service.services.values():
            service.portfolio_config = replace(service.portfolio_config, **policy_updates)
    runtime_config_updated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    return _runtime_config_payload()


@app.post("/api/admin/historical-accumulation", dependencies=[Depends(require_admin)])
async def run_historical_accumulation() -> dict:
    """Append missing historical OOS predictions without touching production tables."""

    return await historical_accumulation_service.run()


@app.post("/api/admin/historical-evaluation", dependencies=[Depends(require_admin)])
def run_historical_evaluation() -> dict:
    """Run P6 explicitly against the isolated historical prediction view."""

    return historical_accumulation_service.run_p6_evaluation()


@app.get("/api/fixtures/{fixture_id}/predictions/latest")
def latest_prediction(fixture_id: str) -> dict:
    """Return the newest prediction compatible with the active prompt contract."""

    fixture = _fixture_or_404(fixture_id)
    result = repository.latest_current(
        fixture_id,
        DEFAULT_PROMPT_CONTRACT.version,
        competition_id=settings.simulation_competition_id,
    )
    if not result:
        raise HTTPException(status_code=404, detail="这场比赛暂无当前版本预测")
    context = demo_context(fixture_id) if fixture["is_demo"] else fixture.get("evidence", unavailable_context())
    apply_player_impact(context)
    if not result.get("decision"):
        result = apply_market_decision(result, context)
    result["execution"] = bankroll_service.execution_for_prediction(result, fixture)
    return public_payload(result)


@app.get("/api/fixtures/{fixture_id}/explanation")
def fixture_explanation(fixture_id: str) -> dict:
    """Return the P13 grounded explanation graph for the current prediction."""

    fixture = _fixture_or_404(fixture_id)
    prediction = repository.latest_current(
        fixture_id,
        DEFAULT_PROMPT_CONTRACT.version,
        competition_id=settings.simulation_competition_id,
    )
    if not prediction:
        raise HTTPException(status_code=404, detail="这场比赛暂无当前版本预测，无法生成解释")
    model_outputs = {
        str(item.get("model_key") or "unknown"): (item.get("probabilities") or item.get("model_probabilities") or {})
        for item in repository.current_predictions_for_fixture(
            fixture_id,
            DEFAULT_PROMPT_CONTRACT.version,
            competition_id=settings.simulation_competition_id,
        )
    }
    evidence = fixture.get("evidence") or unavailable_context()
    feature_snapshot = None
    persisted_reader = getattr(repository, "feature_snapshot", None)
    if prediction.get("feature_snapshot_id") and callable(persisted_reader):
        feature_snapshot = persisted_reader(str(prediction["feature_snapshot_id"]))
    feature_snapshot = feature_snapshot or prediction.get("feature_snapshot")
    if not feature_snapshot:
        feature_snapshot = build_feature_snapshot(
            fixture,
            evidence,
            prediction.get("created_at") or prediction.get("prediction_timestamp"),
        )
    graph = build_explanation_graph(
        prediction,
        feature_snapshot=feature_snapshot,
        evidence=evidence,
        model_outputs=model_outputs,
    )
    return serialize_public(graph)


@app.get("/api/fixtures/{fixture_id}/market")
def fixture_market(fixture_id: str, cutoff: str | None = None) -> dict:
    """Return the P11 market research report: timeline, consensus, divergence, CLV."""

    fixture = _fixture_or_404(fixture_id)
    model_probabilities = None
    latest = repository.latest_current(
        fixture_id,
        DEFAULT_PROMPT_CONTRACT.version,
        competition_id=settings.simulation_competition_id,
    )
    if latest:
        model_probabilities = latest.get("probabilities") or latest.get("model_probabilities")
    report = market_intelligence_service.report(
        fixture_id,
        model_probabilities=model_probabilities,
        cutoff=cutoff,
        kickoff=fixture.get("kickoff"),
    )
    report["persisted_market_snapshots"] = repository.market_snapshots(fixture_id)
    return serialize_public(report)


@app.post("/api/admin/fixtures/{fixture_id}/market-snapshot", dependencies=[Depends(require_admin)])
def capture_market_snapshot(
    fixture_id: str,
    feature_snapshot_id: str | None = None,
) -> dict:
    """Persist idempotent research and Round 5 probability audit snapshots."""

    fixture = _fixture_or_404(fixture_id)
    report = market_intelligence_service.persist_market_snapshots(
        fixture_id,
        kickoff=fixture.get("kickoff"),
    )
    try:
        probability = match_probability(fixture_id, feature_snapshot_id)
    except HTTPException as error:
        report["round5_probability"] = {
            "status": "unavailable",
            "reason": str(error.detail),
        }
        return report
    snapshot_id = persist_round5_market_snapshot(repository, probability)
    report["round5_probability"] = probability
    report["round5_market_snapshot_id"] = snapshot_id
    return report


@app.get(
    "/api/admin/prediction-retention/preview",
    dependencies=[Depends(require_admin)],
)
def preview_prediction_retention() -> dict:
    """Preview prediction rows now protected as permanent audit history."""

    return repository.prediction_retention_preview(DEFAULT_PROMPT_CONTRACT.version)


@app.post(
    "/api/admin/prediction-retention/run",
    dependencies=[Depends(require_admin)],
)
def run_prediction_retention() -> dict:
    """Apply the non-destructive retention policy and return its preview."""

    preview = repository.prediction_retention_preview(DEFAULT_PROMPT_CONTRACT.version)
    result = repository.prune_prediction_history(DEFAULT_PROMPT_CONTRACT.version)
    return {"preview": preview, **result}


@app.post(
    "/api/admin/player-names/resolve",
    dependencies=[Depends(require_admin)],
)
async def resolve_player_names() -> dict:
    """Resolve and cache Chinese display names for current scheduled fixtures."""

    fixture_count = 0
    generated_count = 0
    unresolved_count = 0
    errors: list[str] = []
    for fixture in repository.list_fixtures():
        if fixture.get("status") != "scheduled" or not fixture.get("evidence"):
            continue
        fixture_count += 1
        context = fixture["evidence"]
        await player_name_service.enrich(context, resolve_missing=True)
        state = context.get("player_name") or {}
        generated_count += int(state.get("generated_count") or 0)
        unresolved_count += int(state.get("unresolved_count") or 0)
        if state.get("error"):
            errors.append(f"{fixture['id']}: {state['error']}")
    return {
        "status": "success" if not errors else "partial",
        "fixture_count": fixture_count,
        "generated_count": generated_count,
        "unresolved_count": unresolved_count,
        "errors": errors[:20],
        "source": player_name_provider.source_name,
    }


@app.get(
    "/api/admin/evidence-snapshots/{snapshot_id}",
    dependencies=[Depends(require_admin)],
)
def evidence_snapshot(snapshot_id: str) -> dict:
    """Return the immutable evidence document linked from a prediction."""

    result = repository.evidence_snapshot(snapshot_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Evidence snapshot was not found")
    return public_payload(result)


@app.post("/api/admin/fixtures/{fixture_id}/predictions", dependencies=[Depends(require_admin)])
async def run_prediction(fixture_id: str) -> dict:
    """Create and save a new prediction version for one selected fixture."""

    fixture = _fixture_or_404(fixture_id)
    if fixture["status"] != "scheduled" or _kickoff_started(fixture):
        raise HTTPException(status_code=409, detail="比赛开球后赛前预测已冻结，不能生成或覆盖")
    context = demo_context(fixture_id) if fixture["is_demo"] else fixture.get("evidence")
    if context is None:
        raise HTTPException(status_code=409, detail="请先同步这场比赛的真实赛前数据")
    try:
        results = await prediction_service.create(fixture, context)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    bets = bankroll_service.place_for_predictions(results, fixture, context)
    for item in results:
        item["execution"] = bankroll_service.execution_for_prediction(item, fixture)
    _invalidate_fixture_detail_cache(fixture_id)
    return public_payload({
        "predictions": results,
        "bets": bets,
        "prediction": next((item for item in results if item.get("model_key") == "deepseek"), results[0] if results else None),
    })


@app.post(
    "/api/admin/fixtures/{fixture_id}/settle",
    dependencies=[Depends(require_admin)],
)
def settle_fixture(fixture_id: str) -> dict:
    """Idempotently evaluate predictions and simulated bets for one final fixture."""

    fixture = _fixture_or_404(fixture_id)
    try:
        return settlement_service.settle_fixture(fixture)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/admin/settlements/run", dependencies=[Depends(require_admin)])
def settle_finished_fixtures() -> dict:
    """Settle every cached fixture that has a final score."""

    return settlement_service.settle_finished()


@app.post("/api/admin/fixtures/{fixture_id}/evidence", dependencies=[Depends(require_admin)])
async def sync_fixture_evidence(fixture_id: str) -> dict:
    """Fetch and persist one fixture's current pre-match evidence."""

    fixture = _fixture_or_404(fixture_id)
    if fixture["is_demo"]:
        raise HTTPException(status_code=409, detail="演示比赛不需要同步外部赛前数据")
    try:
        context = await evidence_provider.fetch_public(fixture)
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"赛前数据同步失败：{error}") from error
    context = merge_evidence(fixture.get("evidence"), context)
    updated = repository.save_fixture_evidence(fixture_id, context)
    if updated is None:
        raise HTTPException(status_code=404, detail="未找到比赛")
    _invalidate_fixture_detail_cache(fixture_id)
    return public_payload({"status": "synced", "fixture": updated, "context": context})


@app.post("/api/admin/fixtures/{fixture_id}/dongqiudi-sync", dependencies=[Depends(require_admin)])
async def sync_fixture_dongqiudi(fixture_id: str) -> dict:
    """Force-refresh one fixture's free Dongqiudi odds and analysis."""

    fixture = _fixture_or_404(fixture_id)
    if fixture.get("is_demo"):
        raise HTTPException(status_code=409, detail="演示比赛不需要同步懂球帝数据")
    if not dongqiudi_provider.configured:
        raise HTTPException(status_code=409, detail="懂球帝数据源未配置")
    try:
        result = await dongqiudi_sync.sync_match(fixture_id, phase="manual", force=True)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"懂球帝同步失败：{error}") from error
    updated = repository.fixture(fixture_id)
    _invalidate_fixture_detail_cache(fixture_id)
    return public_payload({"status": "synced", **result, "fixture": updated})


@app.post("/api/admin/sync", dependencies=[Depends(require_admin)])
async def sync_fixtures() -> dict:
    """Synchronize the supported leagues into the local fixture cache."""

    if not schedule_provider.configured:
        raise HTTPException(status_code=409, detail="请先配置免费赛程数据源；当前没有真实赛程缓存")
    try:
        if settings.schedule_provider != "thesportsdb":
            raise RuntimeError(f"不支持的赛程数据源: {settings.schedule_provider}")
        result = await schedule_sync.force_refresh()
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"{settings.schedule_provider} 同步失败：{error}",
        ) from error
    return {"status": "synced", **result, "synced_at": result["last_synced_at"]}


@app.post("/api/admin/dongqiudi/sync", dependencies=[Depends(require_admin)])
async def sync_dongqiudi_schedule() -> dict:
    """Force-refresh the supported Dongqiudi schedule and missing match data."""

    if not dongqiudi_provider.configured:
        raise HTTPException(status_code=409, detail="懂球帝数据源未配置")
    try:
        result = await dongqiudi_sync.sync_schedule(force=False)
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"懂球帝赛程同步失败：{error}") from error
    return {"status": "synced", **result, "synced_at": result["last_synced_at"]}


@app.post("/api/admin/standings/sync", dependencies=[Depends(require_admin)])
async def sync_standings() -> dict:
    """Force-refresh all supported current-season league tables."""

    try:
        result = await league_sync.force_refresh()
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"积分榜同步失败：{error}") from error
    return {"status": "synced", **result, "synced_at": result["last_synced_at"]}
