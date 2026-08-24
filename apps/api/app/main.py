"""FastAPI entry point for browsing fixtures and running manual predictions."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, get_settings
from .data import CHINA_TZ, demo_context, demo_fixtures, unavailable_context
from .database import PredictionRepository
from .prediction import predict
from .provider import ApiFootballProvider
from .schedule_provider import TheSportsDbProvider


app = FastAPI(title="足球赛前分析 API", version="0.1.0")
settings = get_settings()
repository = PredictionRepository(settings.sqlite_path)
repository.initialize()
provider = ApiFootballProvider(settings.api_football_key, settings.api_football_base_url)
schedule_provider = TheSportsDbProvider(settings.thesportsdb_api_key, settings.thesportsdb_base_url)

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
    elif provider.configured:
        mode = "empty"
    else:
        mode = "unconfigured"
    return {
        "status": "ok",
        "provider_configured": provider.configured,
        "schedule_provider": settings.schedule_provider,
        "schedule_provider_configured": schedule_provider.configured,
        "mode": mode,
        "last_synced_at": sync["synced_at"] if sync else None,
    }


@app.get("/api/fixtures")
def fixtures(
    date_filter: Annotated[Literal["today", "tomorrow", "history"], Query(alias="date")] = "today",
    league: Literal["all", "epl", "laliga", "csl"] = "all",
) -> dict:
    """List cached fixtures for one browse view."""

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
    league_key = None if league == "all" else league
    rows = repository.list_fixtures(start_date, end_date, league_key)
    if date_filter == "history":
        rows.reverse()

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
    elif sync:
        mode = "cached"
    elif provider.configured:
        mode = "empty"
    else:
        mode = "unconfigured"
    return {
        "items": rows,
        "mode": mode,
        "provider_configured": provider.configured,
        "last_synced_at": sync["synced_at"] if sync else None,
    }


@app.get("/api/fixtures/{fixture_id}")
def fixture_detail(fixture_id: str) -> dict:
    """Return a fixture, its current evidence, and its latest prediction."""

    fixture = _fixture_or_404(fixture_id)
    context = demo_context(fixture_id) if fixture["is_demo"] else unavailable_context()
    return {"fixture": fixture, "context": context, "prediction": repository.latest(fixture_id)}


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
    if not fixture["is_demo"]:
        raise HTTPException(status_code=409, detail="这场真实比赛尚未同步近期状态、阵容和赛前赔率，不能使用演示证据生成预测")
    result = predict(fixture, demo_context(fixture_id))
    repository.save(result)
    return result


@app.post("/api/admin/sync", dependencies=[Depends(require_admin)])
async def sync_fixtures() -> dict:
    """Synchronize the supported leagues into the local fixture cache."""

    if not schedule_provider.configured:
        raise HTTPException(status_code=409, detail="请先配置免费赛程数据源；当前没有真实赛程缓存")
    today = datetime.now(CHINA_TZ).date()
    start_date = today - timedelta(days=settings.schedule_lookback_days)
    end_date = today + timedelta(days=1)
    try:
        if settings.schedule_provider != "thesportsdb":
            raise RuntimeError(f"不支持的赛程数据源: {settings.schedule_provider}")
        rows = await schedule_provider.fixtures(start_date, end_date)
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"API-Football 同步失败：{error}") from error
    synced_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    repository.replace_fixtures(start_date.isoformat(), end_date.isoformat(), rows, synced_at)
    return {
        "status": "synced",
        "item_count": len(rows),
        "request_count": len(provider.LEAGUE_IDS),
        "from": start_date.isoformat(),
        "to": end_date.isoformat(),
        "synced_at": synced_at,
    }
