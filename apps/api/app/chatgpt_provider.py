"""Strict Responses API client using the shared forecast contract."""

import asyncio
import json
from typing import Any

import httpx

from .deepseek_provider import _bounded_error, _retryable
from .prompt_contract import DEFAULT_PROMPT_CONTRACT, ForecastAssessment, PromptContract, validate_forecast_assessment


PROMPT_VERSION = DEFAULT_PROMPT_CONTRACT.version


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
        contract: PromptContract = DEFAULT_PROMPT_CONTRACT,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.max_tokens = max(500, min(int(max_tokens), 8000))
        self.transport = transport
        self.contract = contract
        self.prompt_version = contract.version

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model and self.base_url)

    async def assess(self, model_input: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("API_CHATGPT_KEY is not configured")
        schema = self.contract.schema()
        payload = {
            "model": self.model,
            "input": self.contract.messages(model_input),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "football_forecast",
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
                    assessment = ForecastAssessment.model_validate(json.loads(_output_text(body)))
                    validate_forecast_assessment(assessment, model_input)
                    return {
                        "assessment": assessment.model_dump(),
                        "provider": self.provider_name,
                        "requested_model": self.model,
                        "returned_model": body.get("model") or self.model,
                        "prompt_version": self.contract.version,
                        "evidence_version": self.contract.evidence_version,
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
