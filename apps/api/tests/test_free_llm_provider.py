"""Free-LLM failover chain: ordering, failover, and kill switch."""

import httpx
import pytest

from app.deepseek_provider import DeepSeekProvider
from app.free_llm_provider import FreeLlmChainProvider, assess_through, probe_chain


def _primary() -> DeepSeekProvider:
    return DeepSeekProvider("amd-key", "DeepSeek-V4-Flash", "https://developer.amd.com.cn/radeon/api/v1")


class StubProvider:
    def __init__(self, label: str, fail: bool = False) -> None:
        self.label = label
        self.fail = fail
        self.calls = 0

    async def assess(self, model_input):
        self.calls += 1
        if self.fail:
            raise RuntimeError("down")
        return {"assessment": {}, "provider": self.label}


def _chain(**kwargs) -> FreeLlmChainProvider:
    defaults = dict(
        quya_base_url="https://api.quya.org/v1",
        quya_model="deepseek-v4-flash",
        quya_api_key="quya-key",
        candidate_timeout_seconds=45.0,
    )
    defaults.update(kwargs)
    return FreeLlmChainProvider(_primary(), **defaults)


def test_candidates_follow_user_priority_order() -> None:
    chain = _chain()
    labels = [label for label, _ in chain._candidates()]
    # 用户指定顺序：AMD V4.1-Flash → 主 provider（AMD V4-Flash）→ 云桥
    assert labels == ["amd-v41", "primary", "quya"]
    first_model = chain._candidates()[0][1].model
    assert first_model == "DeepSeek-V4.1-Flash"
    third = chain._candidates()[2][1]
    assert third.model == "deepseek-v4-flash" and third.base_url == "https://api.quya.org/v1"


def test_candidates_skip_links_without_key() -> None:
    chain = _chain()
    chain.primary.api_key = ""
    # 主 key 缺失时跳过两个 AMD 链路，只剩云桥
    assert [label for label, _ in chain._candidates()] == ["quya"]


def test_chain_delegates_runtime_editable_attributes() -> None:
    chain = _chain()
    chain.primary.model = "Runtime-Model"
    assert chain.model == "Runtime-Model"
    assert chain.configured is True


@pytest.mark.asyncio
async def test_assess_through_falls_over_to_first_working_link() -> None:
    first, second, third = StubProvider("amd-v41", fail=True), StubProvider("primary"), StubProvider("quya")

    result = await assess_through([("amd-v41", first), ("primary", second), ("quya", third)], {})

    assert result["served_by"] == "primary"
    assert first.calls == 1 and second.calls == 1 and third.calls == 0


@pytest.mark.asyncio
async def test_assess_through_raises_combined_errors_when_all_fail() -> None:
    stubs = [StubProvider("amd-v41", fail=True), StubProvider("quya", fail=True)]

    with pytest.raises(RuntimeError) as exc_info:
        await assess_through([("amd-v41", stubs[0]), ("quya", stubs[1])], {})

    message = str(exc_info.value)
    assert "amd-v41" in message and "quya" in message


@pytest.mark.asyncio
async def test_disabled_chain_uses_primary_directly() -> None:
    chain = _chain(enabled=False)
    called = {"count": 0}

    async def fake_assess(model_input):
        called["count"] += 1
        return {"provider": "deepseek"}

    chain.primary.assess = fake_assess
    result = await chain.assess({})
    assert called["count"] == 1 and result["provider"] == "deepseek"
    assert chain._candidates()[0][1].max_retries == 0  # 链内重试关闭，避免挂起候选双倍等待


@pytest.mark.asyncio
async def test_probe_chain_reports_each_link() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "quya" in str(request.url):
            return httpx.Response(502, json={"error": {"message": "upstream"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "正常"}}]})

    provider = DeepSeekProvider(
        "key",
        "DeepSeek-V4-Flash",
        "https://developer.amd.com.cn/radeon/api/v1",
        transport=httpx.MockTransport(handler),
    )
    quya = DeepSeekProvider(
        "key",
        "deepseek-v4-flash",
        "https://api.quya.org/v1",
        transport=httpx.MockTransport(handler),
    )

    transport = httpx.MockTransport(handler)

    report = await probe_chain([("primary", provider), ("quya", quya)], transport=transport)

    assert report[0]["ok"] is True and report[0]["sample"] == "正常"
    assert report[1]["ok"] is False and report[1]["http_status"] == 502
