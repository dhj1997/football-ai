"""Replay one production-shaped request per model without persisting predictions."""

import asyncio
import json
from copy import deepcopy
from time import perf_counter

import httpx

from app.main import chatgpt_provider, deepseek_provider, repository
from app.player_impact import apply_player_impact
from app.prediction_service import _data_completeness, _model_input, _standings_evidence


def model_input(fixture_id: str, model_key: str) -> dict:
    fixture = repository.fixture(fixture_id)
    context = deepcopy(fixture.get("evidence") or {})
    apply_player_impact(context)
    standings = _standings_evidence(repository, fixture)
    quality = _data_completeness(context, standings)
    result = _model_input(fixture, context, standings, quality)
    result["simulation_account"] = {
        "competition_id": "dual-model-v1",
        "model_key": model_key,
        "initial_balance": 1000.0,
        "current_balance": repository.current_balance(model_key, "dual-model-v1"),
        "risk_policy": {"backend_owned": True, "max_fixture_fraction": 0.02},
        "real_money_execution": False,
    }
    return result


async def diagnose_deepseek() -> dict:
    provider = deepseek_provider
    payload = {
        "model": provider.model,
        "messages": provider.contract.messages(model_input("sportsdb-2506169", "deepseek")),
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": provider.max_tokens,
        "stream": False,
    }
    started = perf_counter()
    async with httpx.AsyncClient(
        base_url=provider.base_url,
        headers={"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"},
        timeout=provider.timeout_seconds,
    ) as client:
        response = await client.post("/chat/completions", json=payload)
    result = {
        "provider": "deepseek",
        "status": response.status_code,
        "elapsed_seconds": round(perf_counter() - started, 2),
        "request_id": response.headers.get("x-request-id"),
    }
    try:
        body = response.json()
    except ValueError:
        result["response"] = "non-json"
        return result
    if response.is_success:
        choice = ((body.get("choices") or [{}])[0])
        message = choice.get("message") or {}
        result.update(
            {
                "finish_reason": choice.get("finish_reason"),
                "content_length": len(message.get("content") or ""),
                "reasoning_length": len(message.get("reasoning_content") or ""),
                "usage": body.get("usage"),
            }
        )
    else:
        result["error"] = body.get("error") or str(body)[:500]
    return result


async def diagnose_chatgpt() -> dict:
    provider = chatgpt_provider
    payload = {
        "model": provider.model,
        "input": provider.contract.messages(model_input("sportsdb-2434568", "chatgpt")),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "football_forecast",
                "strict": True,
                "schema": provider.contract.schema(),
            }
        },
        "reasoning": {"effort": "low"},
        "max_output_tokens": provider.max_tokens,
    }
    started = perf_counter()
    async with httpx.AsyncClient(
        base_url=provider.base_url,
        headers={"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"},
        timeout=provider.timeout_seconds,
    ) as client:
        response = await client.post("/responses", json=payload)
    result = {
        "provider": "chatgpt",
        "status": response.status_code,
        "elapsed_seconds": round(perf_counter() - started, 2),
        "request_id": response.headers.get("x-request-id"),
    }
    try:
        body = response.json()
    except ValueError:
        result["response"] = "non-json"
        return result
    if response.is_success:
        direct = body.get("output_text") or ""
        nested = "".join(
            str(content.get("text") or "")
            for item in body.get("output") or []
            if isinstance(item, dict)
            for content in item.get("content") or []
            if isinstance(content, dict) and content.get("type") == "output_text"
        )
        result.update(
            {
                "status_field": body.get("status"),
                "output_text_length": len(direct or nested),
                "usage": body.get("usage"),
            }
        )
    else:
        result["error"] = body.get("error") or str(body)[:500]
    return result


async def main() -> None:
    results = []
    for diagnostic in (diagnose_deepseek, diagnose_chatgpt):
        try:
            results.append(await diagnostic())
        except Exception as error:
            results.append({"provider": diagnostic.__name__, "exception": str(error)[:500]})
    print(json.dumps(results, ensure_ascii=False, separators=(",", ":")))


asyncio.run(main())
