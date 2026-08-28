"""Cached machine transliteration for unresolved player display names."""

import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .player_identity import link_evidence_players
from .team_names import is_reviewed_player_name


class PlayerNameTranslation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_player_id: str = Field(min_length=1, max_length=255)
    chinese_name: str = Field(min_length=2, max_length=40)


class PlayerNameTranslationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    translations: list[PlayerNameTranslation]


class DeepSeekPlayerNameProvider:
    """Translate unresolved names through the already configured model service."""

    source_name = "deepseek_transliteration"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float = 90,
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

    async def translate(self, players: list[dict[str, str]]) -> dict[str, Any]:
        if not self.configured:
            return {"translations": [], "model": None}
        expected_ids = {item["canonical_player_id"] for item in players}
        messages = [
            {
                "role": "system",
                "content": (
                    "你只负责把足球球员的拉丁字母姓名音译为简体中文人名。不得补充或猜测任何其他事实。"
                    "保留常见足球中文译名风格，名字中不得出现拉丁字母。严格返回JSON对象，格式为"
                    '{"translations":[{"canonical_player_id":"输入ID","chinese_name":"中文名"}]}。'
                    "必须为每个输入ID返回且只返回一条结果。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"players": players}, ensure_ascii=False, separators=(",", ":")),
            },
        ]
        payload = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0,
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
                    response.raise_for_status()
                    body = response.json()
                    choices = body.get("choices") or []
                    content = (((choices[0] if choices else {}).get("message") or {}).get("content"))
                    if not isinstance(content, str) or not content.strip():
                        raise ValueError("球员中文音译服务返回空内容")
                    result = PlayerNameTranslationBatch.model_validate(json.loads(content))
                    translations = [item.model_dump() for item in result.translations]
                    returned_ids = {item["canonical_player_id"] for item in translations}
                    if returned_ids != expected_ids or len(translations) != len(players):
                        raise ValueError("球员中文音译结果与输入ID不一致")
                    _validate_names(translations)
                    return {
                        "translations": translations,
                        "model": body.get("model") or self.model,
                        "source": self.source_name,
                    }
                except (httpx.HTTPError, json.JSONDecodeError, ValueError) as error:
                    last_error = error
                    if attempt >= self.max_retries:
                        break
                    await asyncio.sleep(0.25 * (attempt + 1))
        raise RuntimeError(_bounded_error(last_error))


class ChatGptPlayerNameProvider:
    """Use the configured Responses-compatible model as a transliteration fallback."""

    source_name = "chatgpt_transliteration"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float = 90,
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

    async def translate(self, players: list[dict[str, str]]) -> dict[str, Any]:
        if not self.configured:
            return {"translations": [], "model": None, "source": self.source_name}
        expected_ids = {item["canonical_player_id"] for item in players}
        payload = {
            "model": self.model,
            "input": _translation_messages(players),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "player_name_translations",
                    "strict": True,
                    "schema": PlayerNameTranslationBatch.model_json_schema(),
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
                    response.raise_for_status()
                    body = response.json()
                    translations = _validated_translations(_response_output_text(body), expected_ids, len(players))
                    return {
                        "translations": translations,
                        "model": body.get("model") or self.model,
                        "source": self.source_name,
                    }
                except (httpx.HTTPError, json.JSONDecodeError, ValueError) as error:
                    last_error = error
                    if attempt >= self.max_retries:
                        break
                    await asyncio.sleep(0.25 * (attempt + 1))
        raise RuntimeError(_bounded_error(last_error))


class FallbackPlayerNameProvider:
    """Try configured transliteration providers in order without blocking prediction."""

    source_name = "model_transliteration"
    model = "fallback"

    def __init__(self, providers: list[Any]) -> None:
        self.providers = providers

    @property
    def configured(self) -> bool:
        return any(bool(provider.configured) for provider in self.providers)

    async def translate(self, players: list[dict[str, str]]) -> dict[str, Any]:
        errors: list[str] = []
        for provider in self.providers:
            if not provider.configured:
                continue
            try:
                return await provider.translate(players)
            except Exception as error:
                errors.append(f"{provider.source_name}: {_bounded_error(error)}")
        raise RuntimeError("；".join(errors) or "没有可用的球员中文音译服务")


class PlayerNameService:
    """Apply cached names and resolve only previously unseen players in batches."""

    def __init__(self, provider: DeepSeekPlayerNameProvider, repository: Any, batch_size: int = 40) -> None:
        self.provider = provider
        self.repository = repository
        self.batch_size = max(10, min(int(batch_size), 80))
        self._lock = asyncio.Lock()

    async def enrich(self, context: dict[str, Any], resolve_missing: bool = False) -> dict[str, Any]:
        link_evidence_players(context)
        players = _all_players(context)
        cached = self._cached(players)
        _apply_cached(players, cached)
        generated_count = 0
        error: str | None = None

        if resolve_missing and self.provider.configured:
            async with self._lock:
                cached = self._cached(players)
                _apply_cached(players, cached)
                candidates = _translation_candidates(players, cached)
                for start in range(0, len(candidates), self.batch_size):
                    batch = candidates[start : start + self.batch_size]
                    try:
                        result = await self.provider.translate(
                            [
                                {
                                    "canonical_player_id": item["canonical_player_id"],
                                    "source_name": item["source_name"],
                                }
                                for item in batch
                            ]
                        )
                    except Exception as provider_error:
                        error = _bounded_error(provider_error)
                        break
                    returned = {
                        item["canonical_player_id"]: item["chinese_name"]
                        for item in result["translations"]
                    }
                    created_at = datetime.now(UTC).replace(microsecond=0).isoformat()
                    values = [
                        {
                            "canonical_player_id": item["canonical_player_id"],
                            "provider_player_id": item.get("provider_player_id"),
                            "source_name_hash": _source_hash(item["source_name"]),
                            "chinese_name": returned[item["canonical_player_id"]],
                            "name_source": result.get("source") or self.provider.source_name,
                            "name_status": "machine_translated",
                            "model": result.get("model") or self.provider.model,
                            "created_at": created_at,
                        }
                        for item in batch
                    ]
                    self.repository.save_player_names(values)
                    cached.update({item["canonical_player_id"]: item for item in values})
                    generated_count += len(values)
                _apply_cached(players, cached)

        link_evidence_players(context)
        squad = [
            player
            for side in ("home", "away")
            for player in (context.get("squads") or {}).get(side, []) or []
        ]
        context["player_name"] = {
            "provider_configured": bool(self.provider.configured),
            "source": self.provider.source_name if self.provider.configured else None,
            "resolved_count": sum(1 for item in squad if item.get("name_status") == "resolved"),
            "machine_translated_count": sum(1 for item in squad if item.get("name_status") == "machine_translated"),
            "unresolved_count": sum(1 for item in squad if item.get("name_status") == "unresolved"),
            "generated_count": generated_count,
            "error": error,
        }
        return context

    def _cached(self, players: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        canonical_ids = list(
            dict.fromkeys(
                str(item["canonical_player_id"])
                for item in players
                if item.get("canonical_player_id")
            )
        )
        values = self.repository.player_names(canonical_ids) if canonical_ids else []
        return {item["canonical_player_id"]: item for item in values}


def _all_players(context: dict[str, Any]) -> list[dict[str, Any]]:
    result = [
        player
        for side in ("home", "away")
        for player in (context.get("squads") or {}).get(side, []) or []
    ]
    lineup = context.get("lineup") or {}
    result.extend(lineup.get("home_players") or [])
    result.extend(lineup.get("away_players") or [])
    result.extend((context.get("availability") or {}).get("players") or [])
    return result


def _translation_candidates(
    players: list[dict[str, Any]],
    cached: dict[str, dict[str, Any]],
) -> list[dict[str, str | None]]:
    result: dict[str, dict[str, str | None]] = {}
    for player in players:
        canonical_id = str(player.get("canonical_player_id") or "")
        source_name = str(player.get("original_name") or "").strip()
        if (
            not canonical_id
            or is_reviewed_player_name(source_name)
            or not re.search(r"[A-Za-z]", source_name)
        ):
            continue
        cached_item = cached.get(canonical_id)
        if cached_item and cached_item.get("source_name_hash") == _source_hash(source_name):
            continue
        result.setdefault(
            canonical_id,
            {
                "canonical_player_id": canonical_id,
                "provider_player_id": str(player.get("provider_player_id") or "") or None,
                "source_name": source_name,
            },
        )
    return list(result.values())


def _apply_cached(players: list[dict[str, Any]], cached: dict[str, dict[str, Any]]) -> None:
    for player in players:
        value = cached.get(str(player.get("canonical_player_id") or ""))
        source_name = str(player.get("original_name") or "")
        if not value or value.get("source_name_hash") != _source_hash(source_name):
            player.pop("machine_chinese_name", None)
            player.pop("machine_name_source", None)
            continue
        player["machine_chinese_name"] = value["chinese_name"]
        player["machine_name_source"] = value["name_source"]


def _validate_names(translations: list[dict[str, str]]) -> None:
    names = []
    for item in translations:
        name = item["chinese_name"].strip()
        if not any("\u3400" <= character <= "\u9fff" for character in name):
            raise ValueError("球员中文音译结果缺少汉字")
        if re.search(r"[A-Za-z]", name):
            raise ValueError("球员中文音译结果仍包含拉丁字母")
        if any(marker in name for marker in ("未知", "待核验", "球员")):
            raise ValueError("球员中文音译结果是泛化占位词")
        names.append(name)
    if len(names) >= 5 and len(set(names)) / len(names) < 0.65:
        raise ValueError("球员中文音译结果存在异常重复")


def _translation_messages(players: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你只负责把足球球员的拉丁字母姓名音译为简体中文人名。不得补充或猜测任何其他事实。"
                "保留常见足球中文译名风格，名字中不得出现拉丁字母。严格返回要求的JSON结构，"
                "必须为每个输入ID返回且只返回一条结果。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps({"players": players}, ensure_ascii=False, separators=(",", ":")),
        },
    ]


def _validated_translations(content: str, expected_ids: set[str], expected_count: int) -> list[dict[str, str]]:
    result = PlayerNameTranslationBatch.model_validate(json.loads(content))
    translations = [item.model_dump() for item in result.translations]
    returned_ids = {item["canonical_player_id"] for item in translations}
    if returned_ids != expected_ids or len(translations) != expected_count:
        raise ValueError("球员中文音译结果与输入ID不一致")
    _validate_names(translations)
    return translations


def _response_output_text(body: dict[str, Any]) -> str:
    direct = body.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    for item in body.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "output_text":
                value = content.get("text")
                if isinstance(value, str) and value.strip():
                    return value
    raise ValueError("球员中文音译备用服务返回空内容")


def _source_hash(value: str) -> str:
    normalized = " ".join(value.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _bounded_error(error: Exception | None) -> str:
    if error is None:
        return "球员中文音译失败"
    return (str(error).replace("\n", " ").replace("\r", " ")[:300] or error.__class__.__name__)
