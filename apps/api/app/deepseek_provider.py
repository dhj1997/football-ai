"""Strict DeepSeek JSON client for auditable pre-match assessments."""

import asyncio
import json
from typing import Annotated, Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator


PROMPT_VERSION = "deepseek-football-v2"


class OutcomeProbabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    home: float = Field(ge=0, le=1)
    draw: float = Field(ge=0, le=1)
    away: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_total(self) -> "OutcomeProbabilities":
        if abs(self.home + self.draw + self.away - 1) > 0.02:
            raise ValueError("1X2 probabilities must sum to 1")
        return self


class ModelRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: Literal["1x2", "asian_handicap", "no_bet"]
    selection: Literal["home", "draw", "away", "home_handicap", "away_handicap", "none"]
    confidence: float = Field(ge=0, le=1)
    recommended_stake_fraction: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def validate_no_bet(self) -> "ModelRecommendation":
        if self.market == "no_bet" and (
            self.selection != "none" or self.recommended_stake_fraction != 0
        ):
            raise ValueError("no_bet must use selection none and zero stake")
        return self


class AsianHandicapAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    line: float | None
    selection: Literal["home_handicap", "away_handicap", "none"]
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def validate_availability(self) -> "AsianHandicapAssessment":
        if not self.available and (self.line is not None or self.selection != "none"):
            raise ValueError("unavailable Asian handicap must use null line and selection none")
        if self.available and (self.line is None or self.selection == "none"):
            raise ValueError("available Asian handicap requires a line and side")
        return self


class DeepSeekAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    probabilities: OutcomeProbabilities
    predicted_outcome: Literal["home", "draw", "away"]
    asian_handicap_assessment: AsianHandicapAssessment
    recommendation: ModelRecommendation
    analysis_summary: str = Field(min_length=1, max_length=600)
    risk_factors: list[Annotated[str, Field(min_length=1, max_length=160)]] = Field(min_length=1, max_length=8)
    missing_evidence: list[Annotated[str, Field(min_length=1, max_length=160)]] = Field(max_length=12)


class DeepSeekProvider:
    """Call the OpenAI-compatible DeepSeek chat endpoint with bounded retries."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float = 30,
        max_retries: int = 1,
        max_tokens: int = 3000,
        transport: httpx.AsyncBaseTransport | None = None,
        provider_name: str = "deepseek",
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.max_tokens = max(500, min(int(max_tokens), 8000))
        self.transport = transport
        self.provider_name = provider_name
        self.prompt_version = prompt_version

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model and self.base_url)

    async def assess(self, model_input: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("API_DEEPSEEK_KEY is not configured")

        schema = DeepSeekAssessment.model_json_schema()
        messages = [
            {
                "role": "system",
                "content": (
                    "你是足球赛前风险分析模型。只根据输入证据判断，不补造信息。"
                    "必须返回一个符合给定 JSON Schema 的 JSON 对象，不要 Markdown。"
                    "概率必须合计为 1；证据不足时 recommendation.market 必须为 no_bet。"
                    "模拟账户投入比例可在 0 到 1 之间独立判断，不要以 Poisson 基线作为投资依据。"
                    "analysis_summary、所有 reason、risk_factors 和 missing_evidence 必须使用简体中文，"
                    "球队和球员名称也必须使用输入中提供的中文名称。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"prompt_version": self.prompt_version, "schema": schema, "evidence": model_input},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        ]
        payload = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        last_error: Exception | None = None
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            for attempt in range(self.max_retries + 1):
                try:
                    response = await client.post("/chat/completions", json=payload)
                    if response.status_code == 429 or response.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            f"DeepSeek temporary HTTP {response.status_code}",
                            request=response.request,
                            response=response,
                        )
                    response.raise_for_status()
                    body = response.json()
                    choices = body.get("choices") or []
                    content = (((choices[0] if choices else {}).get("message") or {}).get("content"))
                    if not isinstance(content, str) or not content.strip():
                        raise ValueError("DeepSeek returned empty content")
                    assessment = DeepSeekAssessment.model_validate(
                        _normalize_no_bet_assessment(json.loads(content))
                    )
                    _validate_chinese_output(assessment)
                    _validate_handicap_assessment(assessment, model_input.get("odds"))
                    _validate_recommendation(assessment, model_input.get("odds"))
                    return {
                        "assessment": assessment.model_dump(),
                        "provider": self.provider_name,
                        "requested_model": self.model,
                        "returned_model": body.get("model") or self.model,
                        "prompt_version": self.prompt_version,
                        "usage": _safe_usage(body.get("usage")),
                        "request_id": response.headers.get("x-request-id"),
                    }
                except (httpx.HTTPError, json.JSONDecodeError, ValueError) as error:
                    last_error = error
                    if attempt >= self.max_retries or not _retryable(error):
                        break
                    await asyncio.sleep(0.25 * (attempt + 1))
        raise RuntimeError(_bounded_error(last_error))


def _safe_usage(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    return {key: int(value[key]) for key in keys if isinstance(value.get(key), int)} or None


def _validate_recommendation(assessment: DeepSeekAssessment, odds: Any) -> None:
    recommendation = assessment.recommendation
    if recommendation.market == "no_bet":
        return
    if not isinstance(odds, dict):
        raise ValueError("A betting recommendation requires matching market odds")
    if recommendation.market == "1x2":
        if recommendation.selection not in {"home", "draw", "away"}:
            raise ValueError("1X2 recommendation has an invalid selection")
        if not isinstance(odds.get(recommendation.selection), (int, float)):
            raise ValueError("1X2 recommendation has no matching price")
        return
    if recommendation.selection not in {"home_handicap", "away_handicap"}:
        raise ValueError("Asian handicap recommendation has an invalid selection")
    price_key = (
        "asian_handicap_home_odd"
        if recommendation.selection == "home_handicap"
        else "asian_handicap_away_odd"
    )
    if odds.get("asian_handicap") is None or not isinstance(odds.get(price_key), (int, float)):
        raise ValueError("Asian handicap recommendation has no matching line and price")


def _validate_handicap_assessment(assessment: DeepSeekAssessment, odds: Any) -> None:
    handicap = assessment.asian_handicap_assessment
    line = odds.get("asian_handicap") if isinstance(odds, dict) else None
    if line is None:
        if handicap.available:
            raise ValueError("Asian handicap assessment cannot be available without a market line")
        return
    if not handicap.available:
        return
    if not isinstance(handicap.line, (int, float)):
        raise ValueError("An available Asian handicap assessment requires a line")
    if abs(float(handicap.line) - float(line)) > 1e-8:
        raise ValueError("Asian handicap assessment line does not match the evidence")


def _normalize_no_bet_assessment(value: Any) -> Any:
    """Treat an omitted handicap side as unavailable when the model declines a bet."""

    if not isinstance(value, dict):
        return value
    recommendation = value.get("recommendation")
    handicap = value.get("asian_handicap_assessment")
    if (
        isinstance(recommendation, dict)
        and recommendation.get("market") == "no_bet"
        and isinstance(handicap, dict)
        and handicap.get("selection") == "none"
    ):
        handicap.update({"available": False, "line": None, "confidence": 0.0})
    return value


def _validate_chinese_output(assessment: DeepSeekAssessment) -> None:
    fields = [
        assessment.analysis_summary,
        assessment.recommendation.reason,
        assessment.asian_handicap_assessment.reason,
        *assessment.risk_factors,
        *assessment.missing_evidence,
    ]
    if any(text and not any("\u3400" <= character <= "\u9fff" for character in text) for text in fields):
        raise ValueError("Model user-facing text must be written in Chinese")


def _retryable(error: Exception) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        return status == 429 or status >= 500
    return True


def _bounded_error(error: Exception | None) -> str:
    if error is None:
        return "DeepSeek request failed"
    text = str(error).replace("\n", " ").replace("\r", " ")
    return text[:300] or error.__class__.__name__
