import json

import httpx
import pytest

from app.chatgpt_provider import ChatGptProvider
from app.deepseek_provider import DeepSeekProvider
from app.prompt_contract import (
    DEFAULT_PROMPT_CONTRACT,
    EVIDENCE_CONTRACT_VERSION,
    PROMPT_CONTRACT_VERSION,
    ForecastAssessment,
    validate_forecast_assessment,
)


def forecast_content() -> str:
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
                "confidence": 0,
                "reason": "没有可用的亚洲让球盘口。",
            },
            "player_analysis": {
                "key_available_players": ["主队核心前锋"],
                "key_absent_players": [],
                "replacement_gap": "替补差距仍不明确。",
                "attack_impact": "进攻核心保持可用。",
                "defense_impact": "防守证据仍不完整。",
            },
            "bet_recommendation": {
                "status": "no_bet",
                "market": "no_bet",
                "selection": "none",
                "reason": "当前缺少可校验赔率，不建议下注。",
            },
            "analysis_summary": "主队进攻证据较强，但首发仍有不确定性。",
            "risk_factors": ["首发尚未确认"],
            "missing_evidence": ["确认首发名单"],
        },
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_both_models_receive_identical_contract_schema_and_evidence() -> None:
    captured: dict[str, dict] = {}

    def deepseek_handler(request: httpx.Request) -> httpx.Response:
        captured["deepseek"] = json.loads(request.content)
        return httpx.Response(200, json={"model": "deepseek-test", "choices": [{"message": {"content": forecast_content()}}]})

    def chatgpt_handler(request: httpx.Request) -> httpx.Response:
        captured["chatgpt"] = json.loads(request.content)
        return httpx.Response(200, json={"model": "gpt-test", "output_text": forecast_content()})

    evidence = {
        "evidence_version": EVIDENCE_CONTRACT_VERSION,
        "odds": None,
        "player_impact": {"home": {"attack_retention": 1}, "away": {"attack_retention": 1}},
    }
    deepseek = DeepSeekProvider("key", "deepseek-test", "https://deepseek.test", transport=httpx.MockTransport(deepseek_handler))
    chatgpt = ChatGptProvider("key", "gpt-test", "https://gpt.test", transport=httpx.MockTransport(chatgpt_handler))

    deep_result, gpt_result = await deepseek.assess(evidence), await chatgpt.assess(evidence)
    deep_messages = captured["deepseek"]["messages"]
    gpt_messages = captured["chatgpt"]["input"]
    user_payload = json.loads(deep_messages[1]["content"])

    assert deep_messages == gpt_messages
    assert user_payload["evidence"] == evidence
    assert user_payload["prompt_contract_version"] == PROMPT_CONTRACT_VERSION
    assert user_payload["evidence_version"] == EVIDENCE_CONTRACT_VERSION
    assert user_payload["json_schema"] == captured["chatgpt"]["text"]["format"]["schema"]
    assert "bet_recommendation" in json.dumps(user_payload["json_schema"])
    assert "stake" not in json.dumps(user_payload["json_schema"])
    assert deep_result["prompt_version"] == gpt_result["prompt_version"] == PROMPT_CONTRACT_VERSION
    assert deep_result["evidence_version"] == gpt_result["evidence_version"] == EVIDENCE_CONTRACT_VERSION


def test_asian_handicap_cover_probabilities_are_normalized() -> None:
    payload = json.loads(forecast_content())
    payload["asian_handicap_forecast"] = {
        "available": True,
        "line": -1.0,
        "home_cover_probability": 0.62,
        "away_cover_probability": 0.31,
        "confidence": 0.7,
        "reason": "主队覆盖概率更高，但仍需后端校验。",
    }

    result = ForecastAssessment.model_validate(payload)

    assert result.asian_handicap_forecast.home_cover_probability == pytest.approx(2 / 3)
    assert result.asian_handicap_forecast.away_cover_probability == pytest.approx(1 / 3)


def test_strict_schema_requires_every_declared_field() -> None:
    schema = DEFAULT_PROMPT_CONTRACT.schema()

    for definition in schema.get("$defs", {}).values():
        properties = definition.get("properties")
        if properties:
            assert set(definition.get("required", [])) == set(properties)


def test_player_analysis_rejects_supplier_latin_names() -> None:
    payload = json.loads(forecast_content())
    payload["player_analysis"]["key_available_players"] = ["Kylian Mbappe（主队核心）"]
    assessment = ForecastAssessment.model_validate(payload)

    with pytest.raises(ValueError, match="supplier Latin names"):
        validate_forecast_assessment(assessment, {"odds": None})
