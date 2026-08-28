import json

import httpx
import pytest

from app.chatgpt_provider import ChatGptProvider


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
                "replacement_gap": "替补差距仍需确认首发后判断。",
                "attack_impact": "主队进攻核心保持可用。",
                "defense_impact": "防守证据暂不完整。",
            },
            "bet_recommendation": {
                "status": "no_bet",
                "market": "no_bet",
                "selection": "none",
                "reason": "市场数据缺失，当前不建议下注。",
            },
            "analysis_summary": "主队证据较强，但市场数据缺失。",
            "risk_factors": ["盘口缺失"],
            "missing_evidence": ["赛前赔率"],
        },
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_chatgpt_uses_responses_api_and_validates_output() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        assert request.url.path == "/v1/responses"
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "model": "gpt-5.6-sol",
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": assessment_content()}]}
                ],
                "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
            },
            headers={"x-request-id": "request-gpt-1"},
        )

    provider = ChatGptProvider(
        "test-key",
        "gpt-5.6-sol",
        "https://api.quya.test/v1",
        transport=httpx.MockTransport(handler),
    )
    result = await provider.assess({"odds": None})

    assert captured["model"] == "gpt-5.6-sol"
    assert captured["text"]["format"]["strict"] is True
    assert result["provider"] == "chatgpt"
    assert result["usage"]["total_tokens"] == 30


@pytest.mark.asyncio
async def test_chatgpt_rejects_incomplete_handicap_probabilities() -> None:
    payload = json.loads(assessment_content())
    payload["asian_handicap_forecast"].update(
        {"available": True, "line": -1.5, "home_cover_probability": None, "away_cover_probability": None, "confidence": 0.4}
    )
    provider = ChatGptProvider(
        "test-key",
        "gpt-5.6-sol",
        "https://api.quya.test/v1",
        max_retries=0,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "model": "gpt-5.6-sol",
                    "output_text": json.dumps(payload),
                },
            )
        ),
    )

    with pytest.raises(RuntimeError):
        await provider.assess(
            {"odds": {"asian_handicap": -1.5, "asian_handicap_home_odd": 1.9, "asian_handicap_away_odd": 1.9}}
        )
