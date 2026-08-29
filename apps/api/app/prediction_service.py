"""Create immutable baseline and DeepSeek prediction versions."""

import hashlib
import json
import uuid
import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from .prediction import predict
from .evidence_chain import localize_evidence_players
from .player_impact import apply_player_impact
from .player_identity import public_payload
from .market_decision import apply_market_decision
from .prompt_contract import DEFAULT_PROMPT_CONTRACT, EVIDENCE_CONTRACT_VERSION
from .prediction_intelligence import build_feature_snapshot, parse_timestamp
from .historical_validation import build_raw_data_record


STRATEGY_ID = "baseline"
STRATEGY_VERSION = "v1"
DECISION_POLICY_VERSION = "football-sim-portfolio-v1"
AI_VIEW_VERSION = "football-ai-view-v1"


class PredictionService:
    def __init__(
        self,
        model_provider: Any,
        repository: Any,
        model_key: str | None = None,
        competition_id: str = "legacy",
        player_value_service: Any | None = None,
    ) -> None:
        self.model_provider = model_provider
        self.repository = repository
        self.model_key = model_key or getattr(model_provider, "provider_name", "deepseek")
        self.competition_id = competition_id
        self.player_value_service = player_value_service

    async def create(
        self,
        fixture: dict[str, Any],
        context: dict[str, Any],
        snapshot_bundle: dict[str, Any] | None = None,
        prepared_context: bool = False,
        prediction_timestamp: Any | None = None,
    ) -> dict[str, Any]:
        if not prepared_context:
            await self.prepare_context(fixture, context)
        baseline = predict(fixture, context)
        historical_at = parse_timestamp(prediction_timestamp)
        if historical_at:
            baseline["created_at"] = historical_at.isoformat()
        bundle = snapshot_bundle or self.prepare_snapshot(fixture, context)
        snapshot = bundle["evidence"]
        odds_snapshot = bundle.get("odds")
        standings = bundle["standings"]
        quality = bundle["quality"]
        if snapshot_bundle is None:
            self.persist_snapshot_bundle(bundle)
        model_input = _model_input(fixture, context, standings, quality)
        feature_snapshot = build_feature_snapshot(
            fixture,
            context,
            baseline["created_at"],
            standings=standings,
        )
        model_input["feature_snapshot"] = feature_snapshot
        baseline["feature_snapshot"] = feature_snapshot
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
            "risk_policy": {"backend_owned": True, "max_fixture_fraction": 0.25},
            "real_money_execution": False,
        }
        baseline_summary = {
            "model_version": baseline["model_version"],
            "probabilities": deepcopy(baseline["probabilities"]),
            "expected_goals": baseline["expected_goals"],
            "top_scores": baseline["top_scores"],
            "asian_handicap": baseline["asian_handicap"],
        }
        baseline["baseline"] = baseline_summary
        baseline["model_probabilities"] = deepcopy(baseline["probabilities"])
        baseline["prediction_timestamp"] = baseline["created_at"]
        baseline["evidence_snapshot_id"] = snapshot["id"]
        baseline["evidence_hash"] = snapshot["content_hash"]
        baseline["evidence_version"] = snapshot.get("evidence_version") or EVIDENCE_CONTRACT_VERSION
        baseline["odds_snapshot_id"] = odds_snapshot["id"] if odds_snapshot else None
        baseline["prompt_version"] = DEFAULT_PROMPT_CONTRACT.version
        baseline["data_completeness"] = quality["score"]
        baseline["evidence_fields"] = quality["fields"]
        baseline["model_key"] = self.model_key
        baseline["competition_id"] = self.competition_id

        if fixture.get("is_demo"):
            return self._save_degraded(baseline, context, "skipped_demo", "演示数据不会发送给模型")
        if not self.model_provider.configured:
            return self._save_degraded(baseline, context, "unconfigured", "未配置对应的 AI 模型密钥")
        try:
            response = await self.model_provider.assess(model_input)
        except Exception as error:
            return self._save_degraded(baseline, context, "failed", f"模型请求失败：{_bounded_error(error)}")

        assessment = response["assessment"]
        probabilities = assessment["probabilities"]
        total = sum(probabilities.values())
        baseline["probabilities"] = {
            key: round(value / total, 4) for key, value in probabilities.items()
        }
        baseline["model_probabilities"] = deepcopy(baseline["probabilities"])
        provider_name = response.get("provider") or getattr(
            self.model_provider, "provider_name", "deepseek"
        )
        baseline["model_version"] = f"{provider_name}:{response['returned_model']}"
        baseline["forecast_confidence"] = float(assessment["forecast_confidence"])
        baseline["confidence"] = _confidence_label(baseline["forecast_confidence"])
        baseline["predicted_outcome"] = assessment["predicted_outcome"]
        baseline["asian_handicap_forecast"] = assessment["asian_handicap_forecast"]
        baseline["player_analysis"] = assessment["player_analysis"]
        baseline["model_recommendation"] = assessment["bet_recommendation"]
        baseline["analysis_summary"] = assessment["analysis_summary"]
        baseline["risk_factors"] = assessment["risk_factors"]
        baseline["missing_evidence"] = assessment["missing_evidence"]
        baseline["ai"] = {
            "status": "completed",
            "provider": provider_name,
            "requested_model": response["requested_model"],
            "returned_model": response["returned_model"],
            "prompt_version": response["prompt_version"],
            "evidence_version": response.get("evidence_version"),
            "request_id": response["request_id"],
            "usage": response["usage"],
            "error": None,
            "provider_failures": response.get("provider_failures") or [],
        }
        _attach_experiment_metadata(baseline, self.model_key)
        baseline = apply_market_decision(baseline, context)
        self._save_current(baseline)
        return baseline

    def _save_degraded(self, prediction: dict[str, Any], context: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
        prediction["predicted_outcome"] = max(
            prediction["probabilities"], key=prediction["probabilities"].get
        )
        prediction["asian_handicap_forecast"] = {
            "available": False,
            "line": None,
            "home_cover_probability": None,
            "away_cover_probability": None,
            "confidence": 0.0,
            "reason": reason,
        }
        prediction["player_analysis"] = {
            "key_available_players": [],
            "key_absent_players": [],
            "replacement_gap": reason,
            "attack_impact": reason,
            "defense_impact": reason,
        }
        prediction["model_recommendation"] = {
            "status": "no_bet",
            "market": "no_bet",
            "selection": "none",
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
            "prompt_version": DEFAULT_PROMPT_CONTRACT.version,
            "request_id": None,
            "usage": None,
            "error": reason,
            "provider_failures": [],
        }
        prediction["forecast_confidence"] = 0.0
        prediction["model_probabilities"] = deepcopy(prediction.get("probabilities") or {})
        prediction["prompt_version"] = DEFAULT_PROMPT_CONTRACT.version
        _attach_experiment_metadata(prediction, self.model_key)
        prediction = apply_market_decision(prediction, context)
        prediction["model_key"] = self.model_key
        prediction["competition_id"] = self.competition_id
        self._save_current(prediction)
        return prediction

    async def prepare_context(self, fixture: dict[str, Any], context: dict[str, Any]) -> None:
        """Normalize shared evidence before creating any immutable snapshots."""

        localize_evidence_players(context)
        if self.player_value_service is not None:
            await self.player_value_service.enrich(context, str(fixture.get("league_key") or ""))
        apply_player_impact(context)

    def prepare_snapshot(self, fixture: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        standings = _standings_evidence(self.repository, fixture)
        quality = _data_completeness(context, standings)
        return {
            "evidence": _evidence_snapshot(fixture, context, standings),
            "odds": _odds_snapshot(fixture, context),
            "standings": standings,
            "quality": quality,
        }

    def persist_snapshot_bundle(self, bundle: dict[str, Any]) -> None:
        self.repository.save_evidence_snapshot(bundle["evidence"])
        odds = bundle.get("odds")
        saver = getattr(self.repository, "save_odds_snapshot", None)
        if odds and callable(saver):
            saver(odds)
        raw_saver = getattr(self.repository, "save_raw_data_record", None)
        if not callable(raw_saver):
            return
        for entity_type, source, source_id, payload, captured_at in (
            (
                "evidence",
                (bundle["evidence"].get("payload") or {}).get("context", {}).get("source") or "evidence",
                bundle["evidence"].get("id"),
                bundle["evidence"].get("payload") or {},
                bundle["evidence"].get("captured_at") or bundle["evidence"].get("created_at"),
            ),
            (
                "odds",
                odds.get("source") or "odds",
                odds.get("snapshot_id") or odds.get("id"),
                odds,
                odds.get("captured_at"),
            ) if odds else (None, None, None, None, None),
        ):
            if not entity_type or not source_id or not captured_at:
                continue
            try:
                raw_saver(
                    build_raw_data_record(
                        entity_type,
                        str(source),
                        source_id,
                        payload if isinstance(payload, dict) else {},
                        captured_at,
                    )
                )
            except Exception:
                # Raw provenance is additive; preserve the existing prediction path on failure.
                continue

    def _save_current(self, prediction: dict[str, Any]) -> None:
        self.repository.save(prediction)
        prune = getattr(self.repository, "prune_prediction_history", None)
        if callable(prune):
            prune(
                DEFAULT_PROMPT_CONTRACT.version,
                competition_id=self.competition_id,
                fixture_id=prediction["fixture_id"],
                model_key=self.model_key,
            )


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
        "captured_at": created_at,
        "evidence_version": EVIDENCE_CONTRACT_VERSION,
        "hash_algorithm": "sha256",
        "source_synced_at": context.get("synced_at"),
        "content_hash": hashlib.sha256(encoded).hexdigest(),
        "payload": deepcopy(payload),
    }


def _odds_snapshot(fixture: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
    odds = context.get("odds")
    if not isinstance(odds, dict):
        return None
    captured_at = datetime.now(UTC).isoformat()
    source_updated_at = str(odds.get("updated_at")) if odds.get("updated_at") else None
    source = odds.get("source") or context.get("source") or "unknown"
    bookmaker = odds.get("bookmaker")
    quotes: list[dict[str, Any]] = []
    for selection in ("home", "draw", "away"):
        if odds.get(selection) is not None:
            quotes.append(
                {
                    "market": "1x2",
                    "selection": selection,
                    "line": None,
                    "price": odds.get(selection),
                    "bookmaker": bookmaker,
                    "source": source,
                    "captured_at": captured_at,
                    "source_updated_at": source_updated_at,
                }
            )
    line = odds.get("asian_handicap")
    for selection, key in (("home_handicap", "asian_handicap_home_odd"), ("away_handicap", "asian_handicap_away_odd")):
        if line is not None and odds.get(key) is not None:
            quotes.append(
                {
                    "market": "asian_handicap",
                    "selection": selection,
                    "line": line,
                    "price": odds.get(key),
                    "bookmaker": bookmaker,
                    "source": source,
                    "captured_at": captured_at,
                    "source_updated_at": source_updated_at,
                }
            )
    return {
        "id": str(uuid.uuid4()),
        "fixture_id": fixture["id"],
        "captured_at": captured_at,
        "source_updated_at": source_updated_at,
        "source": source,
        "bookmaker": bookmaker,
        "quotes": quotes,
        "payload": deepcopy(odds),
    }


def _attach_experiment_metadata(prediction: dict[str, Any], model_key: str) -> None:
    """Identify the model/policy combination as a reproducible experiment."""

    ai = prediction.get("ai") or {}
    prediction["experiment"] = {
        "model_key": model_key,
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "strategy_name": "基准",
        "prompt_version": ai.get("prompt_version") or DEFAULT_PROMPT_CONTRACT.version,
        "decision_policy_version": DECISION_POLICY_VERSION,
        "ai_view_version": AI_VIEW_VERSION,
        "execution_config_version": f"{model_key}:{STRATEGY_ID}:{STRATEGY_VERSION}",
    }


def _model_input(
    fixture: dict[str, Any],
    context: dict[str, Any],
    standings: dict[str, Any],
    quality: dict[str, Any],
) -> dict[str, Any]:
    return {
        "evidence_version": EVIDENCE_CONTRACT_VERSION,
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
        "availability": _model_availability(context.get("availability")),
        "lineup": public_payload(context.get("lineup")),
        "teams": public_payload(context.get("teams")),
        "squads": {
            side: [
                {
                    "canonical_player_id": player.get("canonical_player_id"),
                    "provider_player_id": player.get("provider_player_id"),
                    "name": player.get("name"),
                    "position": player.get("position"),
                    "age": player.get("age"),
                    "player_role": player.get("player_role"),
                    "expected_start_probability": player.get("expected_start_probability"),
                    "expected_minutes": player.get("expected_minutes"),
                    "appearances": player.get("appearances"),
                    "starts": player.get("starts"),
                    "minutes": player.get("minutes"),
                    "goals_per90": player.get("goals_per90"),
                    "assists_per90": player.get("assists_per90"),
                    "attack_contribution": player.get("attack_contribution"),
                    "defense_contribution": player.get("defense_contribution"),
                    "replacement_contribution": player.get("replacement_contribution"),
                    "absence_impact": player.get("absence_impact"),
                    "market_value_eur": player.get("market_value_eur"),
                }
                for player in (context.get("squads") or {}).get(side, [])[:35]
            ]
            for side in ("home", "away")
        },
        "player_impact": public_payload(context.get("player_impact")),
        "odds": context.get("odds"),
        "standings": standings,
        "data_completeness": quality,
        "evidence_source": context.get("source"),
        "evidence_synced_at": context.get("synced_at"),
    }


def _model_availability(value: Any) -> dict[str, Any]:
    availability = public_payload(value or {})
    availability["notes"] = [
        f"{player.get('name') or '待核验球员'}：{player.get('reason') or '原因待核验'}"
        for player in availability.get("players") or []
    ]
    return availability


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
