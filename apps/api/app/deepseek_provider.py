"""Strict DeepSeek JSON client for the shared forecast contract."""

import asyncio
import json
from typing import Any

import httpx

from .prompt_contract import DEFAULT_PROMPT_CONTRACT, ForecastAssessment, PromptContract, validate_forecast_assessment


PROMPT_VERSION = DEFAULT_PROMPT_CONTRACT.version
DeepSeekAssessment = ForecastAssessment


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
        contract: PromptContract = DEFAULT_PROMPT_CONTRACT,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.max_tokens = max(500, min(int(max_tokens), 8000))
        self.transport = transport
        self.provider_name = provider_name
        self.contract = contract
        self.prompt_version = contract.version

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model and self.base_url)

    async def assess(self, model_input: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("API_DEEPSEEK_KEY is not configured")
        payload = {
            "model": self.model,
            "messages": self.contract.messages(model_input),
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
                    assessment = ForecastAssessment.model_validate(json.loads(content))
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


def _safe_usage(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    return {key: int(value[key]) for key in keys if isinstance(value.get(key), int)} or None


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
