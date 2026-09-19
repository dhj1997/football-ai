"""Free-LLM failover chain for the deepseek channel.

Every deepseek prediction call walks an ordered list of free endpoints and
uses the first one that answers: the AMD ``DeepSeek-V4.1-Flash`` alias
first, then the runtime-editable primary provider (AMD ``DeepSeek-V4-Flash``
today), then the 云桥 relay. Candidates get a short per-attempt timeout —
the chain itself is the retry, so inner retries stay off. When every link
fails, the combined errors surface to the existing ChatGPT fallback.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from .deepseek_provider import DeepSeekProvider, _bounded_error


class FreeLlmChainProvider:
    """Ordered free-endpoint failover behind the deepseek channel."""

    def __init__(
        self,
        primary: DeepSeekProvider,
        *,
        quya_base_url: str,
        quya_model: str,
        quya_api_key: str,
        candidate_timeout_seconds: float = 45.0,
        enabled: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.primary = primary
        self.quya_base_url = quya_base_url.rstrip("/")
        self.quya_model = quya_model
        self.quya_api_key = quya_api_key
        self.candidate_timeout_seconds = candidate_timeout_seconds
        self.enabled = enabled
        self.transport = transport

    # 运行时模型配置面板仍以主 provider 为编辑目标；以下属性全部委托主 provider。
    @property
    def model(self) -> str:
        return self.primary.model

    @property
    def base_url(self) -> str:
        return self.primary.base_url

    @property
    def api_key(self) -> str:
        return self.primary.api_key

    @property
    def provider_name(self) -> str:
        return self.primary.provider_name

    @property
    def configured(self) -> bool:
        return self.primary.configured

    def _candidates(self) -> list[tuple[str, DeepSeekProvider]]:
        """Ordered (label, provider) links, rebuilt per call so runtime edits apply."""

        specs: list[tuple[str, str, str, str]] = []
        if self.primary.api_key and self.primary.base_url:
            specs.append(("amd-v41", self.primary.base_url, "DeepSeek-V4.1-Flash", self.primary.api_key))
            specs.append(("primary", self.primary.base_url, self.primary.model, self.primary.api_key))
        if self.quya_api_key and self.quya_base_url:
            specs.append(("quya", self.quya_base_url, self.quya_model, self.quya_api_key))
        return [
            (
                label,
                DeepSeekProvider(
                    api_key,
                    model,
                    base_url,
                    timeout_seconds=self.candidate_timeout_seconds,
                    max_retries=0,
                    max_tokens=self.primary.max_tokens,
                    provider_name=self.primary.provider_name,
                    contract=self.primary.contract,
                    transport=self.transport,
                ),
            )
            for label, base_url, model, api_key in specs
        ]

    async def assess(self, model_input: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return await self.primary.assess(model_input)
        candidates = self._candidates()
        if not candidates:
            raise RuntimeError("free-llm 链没有可用端点：API_DEEPSEEK_KEY 与 QUYA_LLM_KEY 均未配置")
        return await assess_through(candidates, model_input)


async def assess_through(
    candidates: list[tuple[str, DeepSeekProvider]],
    model_input: dict[str, Any],
) -> dict[str, Any]:
    """Try each candidate in order; raise with combined errors when all fail."""

    errors: list[str] = []
    for label, provider in candidates:
        try:
            result = await provider.assess(model_input)
            result["served_by"] = label
            return result
        except Exception as error:  # noqa: BLE001 — 链式容错必须吞掉一切单点错误
            errors.append(f"{label}: {_bounded_error(error)}")
    raise RuntimeError("free-llm 链全部失败: " + " | ".join(errors))


async def probe_chain(
    candidates: list[tuple[str, DeepSeekProvider]],
    *,
    timeout_seconds: float = 30.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    """Probe every link with a tiny chat request; report status and latency."""

    report: list[dict[str, Any]] = []
    for label, provider in candidates:
        started = time.monotonic()
        entry: dict[str, Any] = {
            "label": label,
            "base_url": provider.base_url,
            "model": provider.model,
        }
        try:
            async with httpx.AsyncClient(
                base_url=provider.base_url,
                headers={"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"},
                timeout=timeout_seconds,
                transport=transport,
            ) as client:
                response = await client.post(
                    "/chat/completions",
                    json={
                        "model": provider.model,
                        "messages": [{"role": "user", "content": "只回复两个字：正常"}],
                        # 推理模型会把 token 先花在 reasoning 上，预算太小会得到空正文
                        "max_tokens": 512,
                        "stream": False,
                    },
                )
            latency = round((time.monotonic() - started) * 1000)
            entry["latency_ms"] = latency
            body = response.json() if response.status_code == 200 else {}
            content = (
                (((body.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
                if isinstance(body, dict)
                else ""
            )
            entry["ok"] = response.status_code == 200 and bool(content.strip())
            entry["http_status"] = response.status_code
            entry["sample"] = content.strip()[:40]
            if not entry["ok"]:
                entry["error"] = f"HTTP {response.status_code}"
        except Exception as error:  # noqa: BLE001 — 探测必须报告每一个失败
            entry["ok"] = False
            entry["latency_ms"] = round((time.monotonic() - started) * 1000)
            entry["error"] = _bounded_error(error)
        report.append(entry)
    return report
