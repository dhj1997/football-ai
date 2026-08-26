"""Strict Responses API client for the optional ChatGPT fallback model."""

import asyncio
import json
from typing import Any

import httpx

from .deepseek_provider import (
    DeepSeekAssessment,
    _bounded_error,
    _normalize_no_bet_assessment,
    _retryable,
    _validate_chinese_output,
    _validate_handicap_assessment,
    _validate_recommendation,
)


PROMPT_VERSION = "chatgpt-football-v2"


class ChatGptProvider:
    """Call an OpenAI-compatible Responses endpoint with strict output validation."""

    provider_name = "chatgpt"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float = 30,
        max_retries: int = 1,
        max_tokens: int = 3000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.max_tokens = max(500, min(int(max_tokens), 8000))
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model and self.base_url)

    async def assess(self, model_input: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("API_CHATGPT_KEY is not configured")

        schema = DeepSeekAssessment.model_json_schema()
        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "You are a pre-match football risk analysis model. Use only the supplied "
                        "evidence and never invent facts. Return the requested structured output. "
                        "Probabilities must total 1. If evidence is insufficient, recommendation.market "
                        "must be no_bet. The independent simulated-account stake fraction may be any "
                        "value from 0 to 1 and does not need to follow a Poisson baseline. Write "
                        "human-facing summary and reasons in Chinese."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"prompt_version": PROMPT_VERSION, "evidence": model_input},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "football_assessment",
                    "strict": True,
                    "schema": schema,
                }
            },
            "reasoning": {"effort": "low"},
            "max_output_tokens": self.max_tokens,
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
                    response = await client.post("/responses", json=payload)
                    if response.status_code == 429 or response.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            f"ChatGPT temporary HTTP {response.status_code}",
                            request=response.request,
                            response=response,
                        )
                    response.raise_for_status()
                    body = response.json()
                    assessment = DeepSeekAssessment.model_validate(
                        _normalize_no_bet_assessment(json.loads(_output_text(body)))
                    )
                    _validate_chinese_output(assessment)
                    _validate_handicap_assessment(assessment, model_input.get("odds"))
                    _validate_recommendation(assessment, model_input.get("odds"))
                    return {
                        "assessment": assessment.model_dump(),
                        "provider": self.provider_name,
                        "requested_model": self.model,
                        "returned_model": body.get("model") or self.model,
                        "prompt_version": PROMPT_VERSION,
                        "usage": _safe_usage(body.get("usage")),
                        "request_id": response.headers.get("x-request-id"),
                    }
                except (httpx.HTTPError, json.JSONDecodeError, ValueError) as error:
                    last_error = error
                    if attempt >= self.max_retries or not _retryable(error):
                        break
                    await asyncio.sleep(0.25 * (attempt + 1))
        raise RuntimeError(_bounded_error(last_error))


def _output_text(body: dict[str, Any]) -> str:
    direct = body.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    for item in body.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    return text
    raise ValueError("ChatGPT returned empty output text")


def _safe_usage(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    mapping = {
        "input_tokens": "prompt_tokens",
        "output_tokens": "completion_tokens",
        "total_tokens": "total_tokens",
    }
    result = {
        target: int(value[source])
        for source, target in mapping.items()
        if isinstance(value.get(source), int)
    }
    return result or None
