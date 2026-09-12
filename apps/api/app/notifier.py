"""Match prediction push notifications via a generic webhook (ServerChan-compatible)."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from .data import CHINA_TZ


def notification_due(fixture: dict[str, Any], now: datetime | None = None) -> bool:
    """True when kickoff is within the next hour and the 1h notice was not sent."""

    reference = now or datetime.now(UTC)
    kickoff = fixture.get("kickoff")
    try:
        kickoff_at = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if kickoff_at.tzinfo is None:
        kickoff_at = kickoff_at.replace(tzinfo=UTC)
    delta = kickoff_at.astimezone(UTC) - reference
    if not timedelta(0) < delta <= timedelta(hours=1):
        return False
    return not ((fixture.get("evidence") or {}).get("automation_refresh") or {}).get("notified_1h_at")


async def send_prediction_notification(webhook_url: str, fixture: dict[str, Any], prediction: dict[str, Any]) -> bool:
    """Push one match's prediction summary; returns True on success."""

    probabilities = (prediction.get("probabilities") or prediction.get("model_probabilities") or {})
    decision = prediction.get("decision") or {}
    home = (fixture.get("home_team") or {}).get("name") or "主队"
    away = (fixture.get("away_team") or {}).get("name") or "客队"
    kickoff_local = datetime.fromisoformat(str(fixture.get("kickoff")).replace("Z", "+00:00")).astimezone(CHINA_TZ)
    pick = {"home": "主胜", "draw": "平局", "away": "客胜"}.get(
        prediction.get("predicted_outcome")
        or (max(probabilities, key=probabilities.get) if probabilities else ""),
        "-",
    )
    lines = [
        f"{home} vs {away}",
        f"开球：{kickoff_local:%m-%d %H:%M}（北京时间）",
        f"综合概率：主胜 {probabilities.get('home', 0):.0%} · 平 {probabilities.get('draw', 0):.0%} · 客胜 {probabilities.get('away', 0):.0%}",
        f"方向：{pick}",
        f"执行：{decision.get('status') or 'no_bet'}"
        + (f" · {decision.get('market')}/{decision.get('selection')}" if decision.get("status") == "bet" else ""),
    ]
    payload = {"title": f"赛前1小时 · {home} vs {away}", "desp": "\n\n".join(lines)}
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(webhook_url, json=payload)
        response.raise_for_status()
    return True


async def notify_due_fixtures(webhook_url: str, fixtures: list[dict[str, Any]], latest_prediction, save_evidence) -> dict[str, int]:
    """Notify every due fixture once; latest_prediction(fixture) -> prediction | None."""

    now = datetime.now(UTC)
    sent = skipped = 0
    for fixture in fixtures:
        if fixture.get("status") != "scheduled" or not notification_due(fixture, now):
            continue
        prediction = latest_prediction(fixture)
        if not prediction:
            skipped += 1
            continue
        try:
            await send_prediction_notification(webhook_url, fixture, prediction)
            sent += 1
        except Exception:
            skipped += 1
            continue
        context = dict(fixture.get("evidence") or {})
        refresh = dict(context.get("automation_refresh") or {})
        refresh["notified_1h_at"] = now.replace(microsecond=0).isoformat()
        context["automation_refresh"] = refresh
        fixture["evidence"] = context
        save_evidence(fixture["id"], context)
    return {"sent": sent, "skipped": skipped}
