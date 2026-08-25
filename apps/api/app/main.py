"""FastAPI entry point for browsing fixtures and running manual predictions."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, get_settings
from .data import CHINA_TZ, demo_context, demo_fixtures, unavailable_context
from .database import PredictionRepository
from .prediction import predict
from .evidence_provider import ApiFootballEvidenceProvider
from .provider import ApiFootballProvider
from .schedule_provider import TheSportsDbProvider
from .schedule_sync import ScheduleSyncService


app = FastAPI(title="足球赛前分析 API", version="0.1.0")
settings = get_settings()
repository = PredictionRepository(settings.database_url)
repository.initialize()
provider = ApiFootballProvider(settings.api_football_key, settings.api_football_base_url)
evidence_provider = ApiFootballEvidenceProvider(
    settings.api_football_key,
    settings.api_football_base_url,
    settings.thesportsdb_api_key,
    settings.thesportsdb_base_url,
)
schedule_provider = TheSportsDbProvider(settings.thesportsdb_api_key, settings.thesportsdb_base_url)
schedule_sync = ScheduleSyncService(
    schedule_provider,
    repository,
    settings.schedule_lookback_days,
    settings.schedule_cache_ttl_minutes,
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
    return {
        "status": "ok",
        "provider_configured": schedule_provider.configured,
        "evidence_provider_configured": evidence_provider.configured,
        "schedule_provider": settings.schedule_provider,
        "schedule_provider_configured": schedule_provider.configured,
        "mode": mode,
        "last_synced_at": sync["synced_at"] if sync else None,
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
    return {
        "items": rows,
        "mode": mode,
        "provider_configured": schedule_provider.configured,
        "evidence_provider_configured": evidence_provider.configured,
        "schedule_provider": settings.schedule_provider,
        "schedule_provider_configured": schedule_provider.configured,
        "sync_status": sync_state["status"],
        "league_counts": league_counts,
        "last_synced_at": sync["synced_at"] if sync else None,
    }


@app.get("/api/fixtures/{fixture_id}")
def fixture_detail(fixture_id: str) -> dict:
    """Return a fixture, its current evidence, and its latest prediction."""

    fixture = _fixture_or_404(fixture_id)
    context = demo_context(fixture_id) if fixture["is_demo"] else fixture.get("evidence", unavailable_context())
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
    return {
        "fixture": fixture,
        "context": context,
        "prediction": repository.latest(fixture_id),
        "capabilities": {"evidence_sync": evidence_provider.configured},
    }


@app.get("/api/fixtures/{fixture_id}/predictions/latest")
def latest_prediction(fixture_id: str) -> dict:
    """Return the newest immutable prediction version."""

    _fixture_or_404(fixture_id)
    result = repository.latest(fixture_id)
    if not result:
        raise HTTPException(status_code=404, detail="这场比赛尚未预测")
    return result


@app.post("/api/admin/fixtures/{fixture_id}/predictions", dependencies=[Depends(require_admin)])
def run_prediction(fixture_id: str) -> dict:
    """Create and save a new prediction version for one selected fixture."""

    fixture = _fixture_or_404(fixture_id)
    if fixture["status"] != "scheduled":
        raise HTTPException(status_code=409, detail="已结束比赛不能重新预测")
    context = demo_context(fixture_id) if fixture["is_demo"] else fixture.get("evidence")
    if context is None:
        raise HTTPException(status_code=409, detail="请先同步这场比赛的真实赛前数据")
    result = predict(fixture, context)
    repository.save(result)
    return result


@app.post("/api/admin/fixtures/{fixture_id}/evidence", dependencies=[Depends(require_admin)])
async def sync_fixture_evidence(fixture_id: str) -> dict:
    """Fetch and persist one fixture's current pre-match evidence."""

    fixture = _fixture_or_404(fixture_id)
    if fixture["is_demo"]:
        raise HTTPException(status_code=409, detail="演示比赛不需要同步外部赛前数据")
    try:
        context = await evidence_provider.fetch(fixture)
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"API-Football 赛前数据同步失败：{error}") from error
    updated = repository.save_fixture_evidence(fixture_id, context)
    if updated is None:
        raise HTTPException(status_code=404, detail="未找到比赛")
    return {"status": "synced", "fixture": updated, "context": context}


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
