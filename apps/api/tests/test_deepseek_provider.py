import json

import httpx
import pytest

from app.deepseek_provider import DeepSeekProvider


def assessment_content() -> str:
    return json.dumps(
        {
            "probabilities": {"home": 0.5, "draw": 0.28, "away": 0.22},
            "predicted_outcome": "home",
            "forecast_confidence": 0.66,
            "asian_handicap_forecast": {
                "available": False,
                "line": None,
                "home_cover_probability": None,
                "away_cover_probability": None,
                "confidence": 0.0,
                "reason": "没有可用的亚洲盘盘口。",
            },
            "player_analysis": {
                "key_available_players": ["主队核心前锋"],
                "key_absent_players": [],
                "replacement_gap": "缺少确认首发，替补差距仍不明确。",
                "attack_impact": "主队进攻核心保持可用。",
                "defense_impact": "防守证据暂不完整。",
            },
            "bet_recommendation": {
                "status": "no_bet",
                "market": "no_bet",
                "selection": "none",
                "reason": "首发未确认但不是唯一条件，当前赔率证据仍不足。",
            },
            "analysis_summary": "主队状态更强，但首发阵容仍存在明显不确定性。",
            "risk_factors": ["首发阵容尚未确认"],
            "missing_evidence": ["确认首发名单"],
        }
    , ensure_ascii=False)


def response(content: str, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "model": "deepseek-v4-flash",
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        },
        headers={"x-request-id": "request-1"},
    )


@pytest.mark.asyncio
async def test_deepseek_json_is_strictly_validated() -> None:
    provider = DeepSeekProvider(
        "test-key",
        "deepseek-v4-flash",
        "https://api.deepseek.test",
        transport=httpx.MockTransport(lambda request: response(assessment_content())),
    )

    result = await provider.assess({"odds": None})

    assert result["assessment"]["probabilities"]["home"] == 0.5
    assert result["assessment"]["asian_handicap_forecast"]["available"] is False
    assert result["returned_model"] == "deepseek-v4-flash"
    assert result["usage"]["total_tokens"] == 30


@pytest.mark.asyncio
async def test_invalid_json_is_retried_once() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response("{}" if calls == 1 else assessment_content())

    provider = DeepSeekProvider(
        "test-key",
        "deepseek-v4-flash",
        "https://api.deepseek.test",
        max_retries=1,
        transport=httpx.MockTransport(handler),
    )

    await provider.assess({"odds": None})

    assert calls == 2


@pytest.mark.asyncio
async def test_english_user_facing_output_is_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            payload = json.loads(assessment_content())
            payload["analysis_summary"] = "The home side is stronger."
            return response(json.dumps(payload, ensure_ascii=False))
        return response(assessment_content())

    provider = DeepSeekProvider(
        "test-key",
        "deepseek-v4-flash",
        "https://api.deepseek.test",
        max_retries=1,
        transport=httpx.MockTransport(handler),
    )

    result = await provider.assess({"odds": None})

    assert calls == 2
    assert "主队" in result["assessment"]["analysis_summary"]


@pytest.mark.asyncio
async def test_permanent_http_error_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"error": {"message": "unauthorized"}})

    provider = DeepSeekProvider(
        "test-key",
        "deepseek-v4-flash",
        "https://api.deepseek.test",
        max_retries=2,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError):
        await provider.assess({"odds": None})

    assert calls == 1


@pytest.mark.asyncio
async def test_schema_rejects_any_model_execution_field() -> None:
    payload = json.loads(assessment_content())
    payload["recommended_stake_fraction"] = 0.5
    provider = DeepSeekProvider(
        "test-key",
        "deepseek-v4-flash",
        "https://api.deepseek.test",
        max_retries=0,
        transport=httpx.MockTransport(
            lambda request: response(json.dumps(payload, ensure_ascii=False))
        ),
    )

    with pytest.raises(RuntimeError):
        await provider.assess({"odds": None})


@pytest.mark.asyncio
async def test_model_output_has_bet_opinion_but_no_stake() -> None:
    provider = DeepSeekProvider(
        "test-key",
        "deepseek-v4-flash",
        "https://api.deepseek.test",
        transport=httpx.MockTransport(
            lambda request: response(assessment_content())
        ),
    )

    result = await provider.assess({"odds": {"home": 2.1, "draw": 3.2, "away": 3.6}})

    assert result["assessment"]["bet_recommendation"]["status"] == "no_bet"
    assert "stake" not in json.dumps(result["assessment"], ensure_ascii=False)
