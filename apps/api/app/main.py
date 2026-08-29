"""FastAPI entry point for continuous football analysis and simulation."""

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .automation import AutomationRunner
from .config import Settings, get_settings
from .bankroll import BankrollService, DualBankrollService
from .chatgpt_provider import ChatGptProvider
from .data import CHINA_TZ, demo_context, demo_fixtures, unavailable_context
from .database import PredictionRepository
from .deepseek_provider import DeepSeekProvider
from .dual_prediction_service import DualPredictionService
from .evidence_provider import ApiFootballEvidenceProvider
from .evidence_chain import (
    EvidenceProviderChain,
    evidence_needs_enrichment,
    localize_evidence_players,
    merge_evidence,
    should_use_secondary,
)
from .espn_evidence_provider import EspnEvidenceProvider
from .league_provider import EspnLeagueProvider
from .league_sync import LeagueSyncService
from .market_decision import apply_market_decision
from .provider import ApiFootballProvider
from .prediction_service import PredictionService
from .prompt_contract import DEFAULT_PROMPT_CONTRACT
from .player_identity import public_payload
from .player_impact import apply_player_impact
from .player_name_provider import (
    ChatGptPlayerNameProvider,
    DeepSeekPlayerNameProvider,
    FallbackPlayerNameProvider,
    PlayerNameService,
)
from .player_value_provider import NullPlayerValueProvider, PlayerValueService
from .schedule_provider import TheSportsDbProvider
from .schedule_sync import ScheduleSyncService
from .settlement import SettlementService
from .team_provider import EspnTeamProvider
from .team_sync import TeamSyncService


@asynccontextmanager
async def lifespan(_: FastAPI):
    task: asyncio.Task | None = None
    if settings.automation_enabled:
        task = asyncio.create_task(automation_runner.run_loop(), name="football-ai-automation")
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
repository = PredictionRepository(
    settings.database_url,
    settings.simulation_competition_id,
    ("deepseek", "chatgpt"),
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
evidence_provider = EvidenceProviderChain(
    api_football_evidence_provider,
    espn_evidence_provider,
    api_football_evidence_provider,
)
schedule_provider = TheSportsDbProvider(settings.thesportsdb_api_key, settings.thesportsdb_base_url)
schedule_sync = ScheduleSyncService(
    schedule_provider,
    repository,
    settings.schedule_lookback_days,
    settings.schedule_cache_ttl_minutes,
)
deepseek_provider = DeepSeekProvider(
    settings.api_deepseek_key,
    settings.deepseek_model,
    settings.deepseek_base_url,
    settings.deepseek_timeout_seconds,
    settings.deepseek_max_retries,
    settings.deepseek_max_tokens,
)
player_value_provider = NullPlayerValueProvider()
player_value_service = PlayerValueService(player_value_provider, repository)
chatgpt_provider = ChatGptProvider(
    settings.api_chatgpt_key,
    settings.chatgpt_model,
    settings.chatgpt_base_url,
    settings.deepseek_timeout_seconds,
    settings.deepseek_max_retries,
    settings.deepseek_max_tokens,
)
player_name_provider = FallbackPlayerNameProvider(
    [
        DeepSeekPlayerNameProvider(
            settings.api_deepseek_key,
            settings.deepseek_model,
            settings.deepseek_base_url,
            settings.deepseek_timeout_seconds,
            settings.deepseek_max_retries,
            settings.deepseek_max_tokens,
        ),
        ChatGptPlayerNameProvider(
            settings.api_chatgpt_key,
            settings.chatgpt_model,
            settings.chatgpt_base_url,
            settings.deepseek_timeout_seconds,
            settings.deepseek_max_retries,
            settings.deepseek_max_tokens,
        ),
    ]
)
player_name_service = PlayerNameService(player_name_provider, repository)
deepseek_prediction_service = PredictionService(
    deepseek_provider,
    repository,
    "deepseek",
    settings.simulation_competition_id,
    player_value_service,
)
chatgpt_prediction_service = PredictionService(
    chatgpt_provider,
    repository,
    "chatgpt",
    settings.simulation_competition_id,
    player_value_service,
)
prediction_service = DualPredictionService(
    {"deepseek": deepseek_prediction_service, "chatgpt": chatgpt_prediction_service},
    settings.simulation_competition_id,
    player_name_service,
)
bankroll_service = DualBankrollService(
    {
        "deepseek": BankrollService(repository).configure("deepseek", settings.simulation_competition_id),
        "chatgpt": BankrollService(repository).configure("chatgpt", settings.simulation_competition_id),
    },
    settings.simulation_competition_id,
)
settlement_service = SettlementService(repository, settings.simulation_competition_id)
league_provider = EspnLeagueProvider(settings.espn_base_url)
league_sync = LeagueSyncService(
    league_provider,
    repository,
    settings.standings_cache_ttl_minutes,
)
team_provider = EspnTeamProvider(settings.espn_base_url)
team_sync = TeamSyncService(team_provider, repository, settings.team_cache_ttl_minutes)
automation_runner = AutomationRunner(
    settings,
    repository,
    schedule_sync,
    league_sync,
    evidence_provider,
    prediction_service,
    bankroll_service,
    settlement_service,
)

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


def _fixture_or_404(fixture_id: str) -> dict:
    fixture = repository.fixture(fixture_id)
    if fixture is None and settings.use_demo_data:
        fixture = next((item for item in demo_fixtures() if item["id"] == fixture_id), None)
    if not fixture:
        raise HTTPException(status_code=404, detail="未找到比赛")
    return fixture


def _kickoff_started(fixture: dict) -> bool:
    try:
        kickoff = datetime.fromisoformat(str(fixture.get("kickoff") or "").replace("Z", "+00:00"))
    except ValueError:
        return True
    kickoff = kickoff.replace(tzinfo=UTC) if kickoff.tzinfo is None else kickoff.astimezone(UTC)
    return kickoff <= datetime.now(UTC)


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
    return {
        "status": "ok",
        "database_backend": repository.engine.dialect.name,
        "provider_configured": schedule_provider.configured,
        "evidence_provider_configured": evidence_provider.configured,
        "evidence_sources": evidence_provider.sources,
        "schedule_provider": settings.schedule_provider,
        "schedule_provider_configured": schedule_provider.configured,
        "mode": mode,
        "last_synced_at": sync["synced_at"] if sync else None,
        "standings_provider_configured": league_provider.configured,
        "deepseek_configured": deepseek_provider.configured,
        "deepseek_model": settings.deepseek_model,
        "chatgpt_configured": chatgpt_provider.configured,
        "chatgpt_model": settings.chatgpt_model,
        "simulated_bankroll_balance": bankroll_service.summary()["accounts"]["deepseek"]["balance"],
        "automation_enabled": settings.automation_enabled,
        "automation_analysis_enabled": settings.automation_analysis_enabled,
        "standings_last_synced_at": max(
            (item.get("updated_at") for item in standings_rows if item.get("updated_at")),
            default=None,
        ),
    }


@app.get("/api/fixtures")
async def fixtures(
    date_filter: Annotated[Literal["today", "tomorrow", "history"], Query(alias="date")] = "today",
    league: Literal["all", "epl", "laliga", "csl"] = "all",
) -> dict:
    """List cached fixtures for one browse view."""

    sync_state = await schedule_sync.ensure_fresh()
    now = datetime.now(CHINA_TZ).date()
    start_date: str | None
    end_date: str | None
    if date_filter == "today":
        start_date = end_date = now.isoformat()
    elif date_filter == "tomorrow":
        start_date = end_date = (now + timedelta(days=1)).isoformat()
    else:
        start_date = None
        end_date = (now - timedelta(days=1)).isoformat()
    all_rows = repository.list_fixtures(start_date, end_date)
    league_key = None if league == "all" else league
    rows = all_rows if league_key is None else [row for row in all_rows if row["league_key"] == league_key]
    if date_filter == "history":
        rows.reverse()

    league_counts = {
        key: sum(1 for row in all_rows if row["league_key"] == key)
        for key in schedule_provider.LEAGUE_IDS
    }

    sync = repository.fixture_sync()
    if not rows and not sync and settings.use_demo_data:
        rows = demo_fixtures(now)
        if date_filter == "today":
            rows = [item for item in rows if datetime.fromisoformat(item["kickoff"]).date() == now]
        elif date_filter == "tomorrow":
            rows = [item for item in rows if datetime.fromisoformat(item["kickoff"]).date() == now + timedelta(days=1)]
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
    return public_payload({
        "items": rows,
        "mode": mode,
        "provider_configured": schedule_provider.configured,
        "evidence_provider_configured": evidence_provider.configured,
        "evidence_sources": evidence_provider.sources,
        "schedule_provider": settings.schedule_provider,
        "schedule_provider_configured": schedule_provider.configured,
        "sync_status": sync_state["status"],
        "league_counts": league_counts,
        "last_synced_at": sync["synced_at"] if sync else None,
    })


@app.get("/api/standings")
async def standings(
    league: Literal["all", "epl", "laliga", "csl"] = "all",
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
    return public_payload({"item": state["item"], "sync_status": state["status"]})


@app.get("/api/fixtures/{fixture_id}")
async def fixture_detail(fixture_id: str) -> dict:
    """Return a fixture, its current evidence, and its latest prediction."""

    fixture = _fixture_or_404(fixture_id)
    evidence_error: str | None = None
    prediction_error: str | None = None
    if (
        not fixture.get("is_demo")
        and fixture.get("status") in {"scheduled", "live"}
        and (not fixture.get("evidence") or evidence_needs_enrichment(fixture.get("evidence")))
        and evidence_provider.configured
    ):
        try:
            existing = fixture.get("evidence") or {}
            fetch_secondary = getattr(evidence_provider, "fetch_secondary", None)
            fetcher = fetch_secondary if should_use_secondary(existing) and callable(fetch_secondary) else evidence_provider.fetch
            context = await fetcher(fixture)
            context = merge_evidence(existing, context)
            updated = repository.save_fixture_evidence(fixture_id, context)
            if updated is not None:
                fixture = updated
        except Exception as error:
            evidence_error = str(error)
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
    await player_value_service.enrich(context, str(fixture.get("league_key") or ""))
    apply_player_impact(context)
    for key, item in list(predictions.items()):
        if item:
            predictions[key] = apply_market_decision(item, context)
    prediction = predictions.get("deepseek") or next((item for item in predictions.values() if item), None)
    model_bets = {}
    for key, item in predictions.items():
        linked_bet = repository.bet_for_prediction(item["id"]) if item else None
        model_bets[key] = linked_bet
        if item:
            item["execution"] = bankroll_service.execution_for_prediction(item, fixture)
    return public_payload({
        "fixture": fixture,
        "context": context,
        "prediction": prediction,
        "predictions": predictions,
        "bet": model_bets.get("deepseek") or next((item for item in model_bets.values() if item), None),
        "bets": model_bets,
        "competition_id": settings.simulation_competition_id,
        "capabilities": {
            "evidence_sync": evidence_provider.configured,
            "evidence_sources": evidence_provider.sources,
            "deepseek": deepseek_provider.configured,
            "chatgpt": chatgpt_provider.configured,
        },
        "evidence_error": evidence_error,
        "prediction_error": prediction_error,
    })


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


@app.get("/api/decisions")
def prediction_decisions(
    league: Literal["all", "epl", "laliga", "csl"] = "all",
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
    items: list[dict] = []
    for row in rows:
        prediction = row.get("prediction") or {}
        fixture = row.get("fixture") or {}
        decision = prediction.get("decision") or {}
        linked_bet = repository.bet_for_prediction(prediction["id"])
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
            }
        elif decision.get("status") in {"bet", "no_bet", "insufficient_data"}:
            execution = bankroll_service.execution_for_prediction(prediction, fixture) if fixture else {
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
                "model_recommendation_status": (prediction.get("model_recommendation") or {}).get("status"),
            }
        )
    return {"items": public_payload(items), "count": len(items), "is_simulated": True}


@app.get("/api/metrics/predictions")
def prediction_metrics(
    league: Literal["all", "epl", "laliga", "csl"] = "all",
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
    league: Literal["all", "epl", "laliga", "csl"] = "all",
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
                "prediction_samples": report.get("sample_size", 0),
                "market_comparison_samples": comparison.get("sample_size", 0),
                "average_brier": report.get("average_brier_score"),
                "average_log_loss": report.get("average_log_loss"),
                "brier_improvement": comparison.get("brier_improvement"),
                "clv_samples": portfolio.get("clv_samples", 0),
                "max_drawdown": portfolio.get("max_drawdown", 0.0),
                "gate_status": gate.get("status", "INSUFFICIENT_SAMPLE"),
                "gate_mode": gate.get("mode", "SHADOW_ONLY"),
            }
        )
    rows.sort(key=lambda item: (-float(item.get("roi") or 0), -float(item.get("realized_pnl") or 0), str(item["model_key"])))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return {"items": rows, "count": len(rows), "ranking": "ROI_THEN_PNL", "is_simulated": True}


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
async def run_automation_job(job_name: str) -> dict:
    """Force one known automation job while preserving normal run history."""

    try:
        return await automation_runner.run_job(job_name)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


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
    result = apply_market_decision(result, context)
    result["execution"] = bankroll_service.execution_for_prediction(result, fixture)
    return public_payload(result)


@app.get(
    "/api/admin/prediction-retention/preview",
    dependencies=[Depends(require_admin)],
)
def preview_prediction_retention() -> dict:
    """Preview superseded prediction and simulated-ledger cleanup."""

    return repository.prediction_retention_preview(DEFAULT_PROMPT_CONTRACT.version)


@app.post(
    "/api/admin/prediction-retention/run",
    dependencies=[Depends(require_admin)],
)
def run_prediction_retention() -> dict:
    """Delete superseded prediction data after producing an explicit preview."""

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
        raise HTTPException(status_code=409, detail="比赛已开球，不能作废或重新创建赛前模拟单")
    context = demo_context(fixture_id) if fixture["is_demo"] else fixture.get("evidence")
    if context is None:
        raise HTTPException(status_code=409, detail="请先同步这场比赛的真实赛前数据")
    results = await prediction_service.create(fixture, context)
    bets = bankroll_service.place_for_predictions(results, fixture, context)
    for item in results:
        item["execution"] = bankroll_service.execution_for_prediction(item, fixture)
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
        context = await evidence_provider.fetch(fixture)
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"赛前数据同步失败：{error}") from error
    updated = repository.save_fixture_evidence(fixture_id, context)
    if updated is None:
        raise HTTPException(status_code=404, detail="未找到比赛")
    return public_payload({"status": "synced", "fixture": updated, "context": context})


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


@app.post("/api/admin/standings/sync", dependencies=[Depends(require_admin)])
async def sync_standings() -> dict:
    """Force-refresh all supported current-season league tables."""

    try:
        result = await league_sync.force_refresh()
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"积分榜同步失败：{error}") from error
    return {"status": "synced", **result, "synced_at": result["last_synced_at"]}
