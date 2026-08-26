"""Create immutable baseline and DeepSeek prediction versions."""

import hashlib
import json
import uuid
import asyncio
from datetime import UTC, datetime
from typing import Any

from .prediction import predict


class PredictionService:
    def __init__(
        self,
        model_provider: Any,
        repository: Any,
        model_key: str | None = None,
        competition_id: str = "legacy",
    ) -> None:
        self.model_provider = model_provider
        self.repository = repository
        self.model_key = model_key or getattr(model_provider, "provider_name", "deepseek")
        self.competition_id = competition_id

    async def create(self, fixture: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        baseline = predict(fixture, context)
        standings = _standings_evidence(self.repository, fixture)
        quality = _data_completeness(context, standings)
        snapshot = _evidence_snapshot(fixture, context, standings)
        self.repository.save_evidence_snapshot(snapshot)
        model_input = _model_input(fixture, context, standings, quality)
        balance_reader = getattr(self.repository, "current_balance", None)
        current_balance = (
            balance_reader(self.model_key, self.competition_id)
            if callable(balance_reader)
            else 1000.0
        )
        model_input["simulation_account"] = {
            "competition_id": self.competition_id,
            "model_key": self.model_key,
            "initial_balance": 1000.0,
            "current_balance": current_balance,
            "stake_fraction_min": 0.0,
            "stake_fraction_max": 1.0,
            "real_money_execution": False,
        }
        baseline_summary = {
            "model_version": baseline["model_version"],
            "probabilities": baseline["probabilities"],
            "expected_goals": baseline["expected_goals"],
            "top_scores": baseline["top_scores"],
            "asian_handicap": baseline["asian_handicap"],
        }
        baseline["baseline"] = baseline_summary
        baseline["evidence_snapshot_id"] = snapshot["id"]
        baseline["evidence_hash"] = snapshot["content_hash"]
        baseline["data_completeness"] = quality["score"]
        baseline["evidence_fields"] = quality["fields"]
        baseline["model_key"] = self.model_key
        baseline["competition_id"] = self.competition_id

        if fixture.get("is_demo"):
            return self._save_degraded(baseline, "skipped_demo", "演示数据不会发送给模型")
        if not self.model_provider.configured:
            return self._save_degraded(baseline, "unconfigured", "未配置对应的 AI 模型密钥")
        try:
            response = await self.model_provider.assess(model_input)
        except Exception as error:
            return self._save_degraded(baseline, "failed", f"模型请求失败：{_bounded_error(error)}")

        assessment = response["assessment"]
        probabilities = assessment["probabilities"]
        total = sum(probabilities.values())
        baseline["probabilities"] = {
            key: round(value / total, 4) for key, value in probabilities.items()
        }
        provider_name = response.get("provider") or getattr(
            self.model_provider, "provider_name", "deepseek"
        )
        baseline["model_version"] = f"{provider_name}:{response['returned_model']}"
        baseline["confidence"] = _confidence_label(assessment["recommendation"]["confidence"])
        baseline["predicted_outcome"] = assessment["predicted_outcome"]
        baseline["asian_handicap_assessment"] = assessment["asian_handicap_assessment"]
        baseline["recommendation"] = assessment["recommendation"]
        baseline["analysis_summary"] = assessment["analysis_summary"]
        baseline["risk_factors"] = assessment["risk_factors"]
        baseline["missing_evidence"] = assessment["missing_evidence"]
        baseline["ai"] = {
            "status": "completed",
            "provider": provider_name,
            "requested_model": response["requested_model"],
            "returned_model": response["returned_model"],
            "prompt_version": response["prompt_version"],
            "request_id": response["request_id"],
            "usage": response["usage"],
            "error": None,
            "provider_failures": response.get("provider_failures") or [],
        }
        self.repository.save(baseline)
        return baseline

    def _save_degraded(self, prediction: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
        prediction["predicted_outcome"] = max(
            prediction["probabilities"], key=prediction["probabilities"].get
        )
        prediction["recommendation"] = {
            "market": "no_bet",
            "selection": "none",
            "confidence": 0.0,
            "recommended_stake_fraction": 0.0,
            "reason": reason,
        }
        prediction["asian_handicap_assessment"] = {
            "available": False,
            "line": None,
            "selection": "none",
            "confidence": 0.0,
            "reason": reason,
        }
        prediction["analysis_summary"] = "AI 模型当前不可用，页面仅展示确定性的基础概率。"
        prediction["risk_factors"] = [reason]
        prediction["missing_evidence"] = []
        prediction["ai"] = {
            "status": status,
            "provider": getattr(self.model_provider, "provider_name", "ai"),
            "requested_model": self.model_provider.model,
            "returned_model": None,
            "prompt_version": None,
            "request_id": None,
            "usage": None,
            "error": reason,
            "provider_failures": [],
        }
        prediction["model_key"] = self.model_key
        prediction["competition_id"] = self.competition_id
        self.repository.save(prediction)
        return prediction


def _evidence_snapshot(
    fixture: dict[str, Any],
    context: dict[str, Any],
    standings: dict[str, Any],
) -> dict[str, Any]:
    created_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    payload = {"fixture": fixture, "context": context, "standings": standings}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return {
        "id": str(uuid.uuid4()),
        "fixture_id": fixture["id"],
        "created_at": created_at,
        "source_synced_at": context.get("synced_at"),
        "content_hash": hashlib.sha256(encoded).hexdigest(),
        "payload": payload,
    }


def _model_input(
    fixture: dict[str, Any],
    context: dict[str, Any],
    standings: dict[str, Any],
    quality: dict[str, Any],
) -> dict[str, Any]:
    return {
        "fixture": {
            "id": fixture["id"],
            "league": fixture.get("league"),
            "kickoff": fixture.get("kickoff"),
            "home_team": fixture.get("home_team"),
            "away_team": fixture.get("away_team"),
            "venue": fixture.get("venue"),
        },
        "recent_form": context.get("recent_form"),
        "head_to_head": (context.get("head_to_head") or [])[:8],
        "availability": context.get("availability"),
        "lineup": context.get("lineup"),
        "teams": context.get("teams"),
        "squads": {
            side: [
                {
                    "name": player.get("name"),
                    "position": player.get("position"),
                    "age": player.get("age"),
                }
                for player in (context.get("squads") or {}).get(side, [])[:35]
            ]
            for side in ("home", "away")
        },
        "odds": context.get("odds"),
        "standings": standings,
        "data_completeness": quality,
        "evidence_source": context.get("source"),
        "evidence_synced_at": context.get("synced_at"),
    }


def _standings_evidence(repository: Any, fixture: dict[str, Any]) -> dict[str, Any]:
    reader = getattr(repository, "league_snapshots", None)
    snapshots = reader(fixture.get("league_key")) if callable(reader) else []
    snapshot = snapshots[0] if snapshots else {}
    table = snapshot.get("standings") or []
    return {
        "source": snapshot.get("source"),
        "season": snapshot.get("season"),
        "updated_at": snapshot.get("updated_at"),
        "home": _find_standing(table, fixture.get("home_team") or {}),
        "away": _find_standing(table, fixture.get("away_team") or {}),
    }


def _find_standing(table: list[dict[str, Any]], fixture_team: dict[str, Any]) -> dict[str, Any] | None:
    names = {
        _canonical_name(value)
        for value in (fixture_team.get("name"), fixture_team.get("original_name"))
        if value
    }
    for row in table:
        team = row.get("team") or {}
        candidates = {
            _canonical_name(value)
            for value in (team.get("name"), team.get("original_name"))
            if value
        }
        if names & candidates:
            return {
                key: row.get(key)
                for key in (
                    "rank",
                    "played",
                    "wins",
                    "draws",
                    "losses",
                    "goals_for",
                    "goals_against",
                    "goal_difference",
                    "points",
                )
            }
    return None


def _canonical_name(value: Any) -> str:
    return "".join(character.casefold() for character in str(value) if character.isalnum())


def _data_completeness(context: dict[str, Any], standings: dict[str, Any]) -> dict[str, Any]:
    recent = context.get("recent_form") or {}
    squads = context.get("squads") or {}
    fields = {
        "standings": bool(standings.get("home") and standings.get("away")),
        "recent_form": bool(recent.get("home") and recent.get("away")),
        "head_to_head": bool(context.get("head_to_head")),
        "squads": bool(squads.get("home") and squads.get("away")),
        "availability": bool((context.get("availability") or {}).get("updated_at")),
        "lineup": bool((context.get("lineup") or {}).get("confirmed")),
        "odds": bool(context.get("odds")),
    }
    return {
        "score": round(sum(fields.values()) / len(fields), 4),
        "fields": fields,
        "missing": [key for key, available in fields.items() if not available],
    }


def _confidence_label(value: float) -> str:
    return "较高" if value >= 0.72 else "中等" if value >= 0.5 else "有限"


def _bounded_error(error: Exception) -> str:
    return (str(error).replace("\n", " ").replace("\r", " ")[:300] or error.__class__.__name__)
