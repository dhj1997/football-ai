"""Create immutable baseline and DeepSeek prediction versions."""

import hashlib
import json
import uuid
import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from .prediction import predict
from .elo import compute_elo
from .evidence_chain import localize_evidence_players
from .player_impact import apply_player_impact
from .player_identity import public_payload
from .market_decision import apply_market_decision
from .leakage_audit import FutureDataLeakageError, LeakageAuditService
from .market_prior import Round5ProbabilityEngine
from .probability_engine import ProbabilityEngineError, TransparentProbabilityEngine
from .prompt_contract import DEFAULT_PROMPT_CONTRACT, EVIDENCE_CONTRACT_VERSION
from .prediction_intelligence import (
    FEATURE_VERSION,
    build_feature_snapshot,
    cutoff_safe_fixture,
    cutoff_safe_prediction_inputs,
    model_feature_manifest,
    parse_timestamp,
)
from .historical_validation import build_raw_data_record
from .recent_form import RecentFormService


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
        initial_bankroll: float = 1000.0,
        player_stats_service: Any | None = None,
    ) -> None:
        self.model_provider = model_provider
        self.repository = repository
        self.model_key = model_key or getattr(model_provider, "provider_name", "deepseek")
        self.competition_id = competition_id
        self.player_value_service = player_value_service
        self.player_stats_service = player_stats_service
        self.initial_bankroll = max(0.0, float(initial_bankroll))

    def _elo_ratings(self, prediction_timestamp: Any | None = None) -> dict[str, float]:
        """Elo ratings: ClubElo snapshot (professional, cross-season) overrides
        the locally computed window estimate as a fallback."""

        merged: dict[str, float] = {}
        try:
            fixtures = self.repository.list_fixtures()  # type: ignore[attr-defined]
            merged.update(compute_elo(fixtures, as_of=prediction_timestamp))
        except Exception:
            pass
        try:
            from .clubeelo_provider import stored_ratings

            merged.update(stored_ratings(self.repository, as_of=prediction_timestamp))
        except Exception:
            pass
        return merged

    async def create(
        self,
        fixture: dict[str, Any],
        context: dict[str, Any],
        snapshot_bundle: dict[str, Any] | None = None,
        prepared_context: bool = False,
        prediction_timestamp: Any | None = None,
        persist_production_evidence: bool = True,
    ) -> dict[str, Any]:
        requested_cutoff = parse_timestamp(prediction_timestamp)
        if prediction_timestamp is not None and requested_cutoff is None:
            raise ValueError("prediction_timestamp must be an ISO timestamp")
        preparation_cutoff = requested_cutoff or datetime.now(UTC)
        kickoff = parse_timestamp(fixture.get("kickoff"))
        if kickoff is not None and preparation_cutoff >= kickoff:
            raise ValueError("比赛开球后赛前预测已冻结，不能生成或覆盖")
        if not prepared_context:
            await self.prepare_context(
                fixture,
                context,
                prediction_timestamp=preparation_cutoff,
            )
        # For current predictions the cutoff is the instant after evidence
        # preparation and immediately before snapshot/model construction.
        cutoff = requested_cutoff or datetime.now(UTC)
        if kickoff is not None and cutoff >= kickoff:
            raise ValueError("比赛开球后赛前预测已冻结，不能生成或覆盖")
        safe_fixture = cutoff_safe_fixture(fixture, cutoff)
        bundle = snapshot_bundle or self.prepare_snapshot(
            safe_fixture,
            context,
            prediction_timestamp=cutoff,
        )
        snapshot = bundle["evidence"]
        odds_snapshot = bundle.get("odds")
        standings = bundle["standings"]
        if snapshot_bundle is None:
            self.persist_snapshot_bundle(bundle)
        prediction_id = str(uuid.uuid4())
        input_audit_snapshot = build_feature_snapshot(
            safe_fixture,
            context,
            cutoff,
            standings=standings,
            evidence_snapshot_id=snapshot["id"],
            odds_snapshot_id=odds_snapshot["id"] if odds_snapshot else None,
        )
        feature_snapshot = build_feature_snapshot(
            safe_fixture,
            context,
            cutoff,
            standings=standings,
            evidence_snapshot_id=snapshot["id"],
            odds_snapshot_id=odds_snapshot["id"] if odds_snapshot else None,
            repository=self.repository,
        )
        feature_snapshot["prediction_id"] = prediction_id
        feature_saver = getattr(self.repository, "save_feature_snapshot", None)
        if callable(feature_saver):
            feature_snapshot = feature_saver(feature_snapshot)
        leakage_audit = LeakageAuditService(self.repository).audit_feature_snapshot(
            feature_snapshot,
            prediction_id=prediction_id,
        )
        if leakage_audit["status"] == "FAIL":
            raise FutureDataLeakageError(
                f"Future data leakage detected for prediction {prediction_id}"
            )
        safe_context, safe_standings = cutoff_safe_prediction_inputs(
            context,
            standings,
            input_audit_snapshot,
        )
        apply_player_impact(safe_context)
        quality = _data_completeness(safe_context, safe_standings)
        baseline = predict(safe_fixture, safe_context)
        baseline["id"] = prediction_id
        baseline["created_at"] = cutoff.isoformat()
        model_input = _model_input(safe_fixture, safe_context, safe_standings, quality)
        model_input["feature_snapshot"] = public_payload(model_feature_manifest(feature_snapshot))
        baseline["feature_snapshot"] = feature_snapshot
        balance_reader = getattr(self.repository, "current_balance", None)
        current_balance = (
            balance_reader(self.model_key, self.competition_id)
            if callable(balance_reader)
            else self.initial_bankroll
        )
        model_input["simulation_account"] = {
            "competition_id": self.competition_id,
            "model_key": self.model_key,
            "initial_balance": self.initial_bankroll,
            "current_balance": current_balance,
            "risk_policy": {"backend_owned": True, "max_fixture_fraction": 0.25},
            "real_money_execution": False,
        }
        baseline_summary = {
            "model_version": baseline["model_version"],
            "probabilities": deepcopy(baseline["probabilities"]),
            "expected_goals": baseline["expected_goals"],
            "top_scores": baseline["top_scores"],
            "markets_detail": deepcopy(baseline.get("markets_detail")),
            "asian_handicap": baseline["asian_handicap"],
        }
        baseline["baseline"] = baseline_summary
        baseline["model_probabilities"] = deepcopy(baseline["probabilities"])
        baseline["prediction_timestamp"] = baseline["created_at"]
        baseline["prediction_cutoff_at"] = cutoff.isoformat()
        baseline["fixture_status_at_prediction"] = safe_fixture.get("status")
        baseline["score_at_prediction"] = deepcopy(safe_fixture.get("score"))
        baseline["match_minute_at_prediction"] = safe_fixture.get("minute") or safe_fixture.get("elapsed")
        baseline["evidence_snapshot_id"] = snapshot["id"]
        baseline["evidence_hash"] = snapshot["content_hash"]
        baseline["evidence_version"] = snapshot.get("evidence_version") or EVIDENCE_CONTRACT_VERSION
        baseline["odds_snapshot_id"] = odds_snapshot["id"] if odds_snapshot else None
        baseline["odds_fingerprint"] = context.get("odds_fingerprint")
        baseline["feature_snapshot_id"] = feature_snapshot["snapshot_id"]
        baseline["feature_version"] = feature_snapshot["feature_version"]
        baseline["leakage_audit"] = leakage_audit
        baseline["prompt_version"] = DEFAULT_PROMPT_CONTRACT.version
        baseline["data_completeness"] = quality["score"]
        baseline["evidence_fields"] = quality["fields"]
        baseline["model_key"] = self.model_key
        baseline["competition_id"] = self.competition_id

        if fixture.get("is_demo"):
            return self._save_degraded(
                baseline,
                safe_context,
                "skipped_demo",
                "演示数据不会发送给模型",
                kickoff=kickoff,
                odds_snapshot=odds_snapshot,
                persist_production_evidence=persist_production_evidence,
            )
        if not self.model_provider.configured:
            return self._save_degraded(
                baseline,
                safe_context,
                "unconfigured",
                "未配置对应的 AI 模型密钥",
                kickoff=kickoff,
                odds_snapshot=odds_snapshot,
                persist_production_evidence=persist_production_evidence,
            )
        try:
            response = await self.model_provider.assess(model_input)
        except Exception as error:
            return self._save_degraded(
                baseline,
                safe_context,
                "failed",
                f"模型请求失败：{_bounded_error(error)}",
                kickoff=kickoff,
                odds_snapshot=odds_snapshot,
                persist_production_evidence=persist_production_evidence,
            )

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
        baseline = apply_market_decision(baseline, safe_context)
        self._save_current(
            baseline,
            kickoff=kickoff,
            odds_snapshot=odds_snapshot,
            persist_production_evidence=persist_production_evidence,
        )
        return baseline

    def _save_degraded(
        self,
        prediction: dict[str, Any],
        context: dict[str, Any],
        status: str,
        reason: str,
        *,
        kickoff: datetime | None,
        odds_snapshot: dict[str, Any] | None,
        persist_production_evidence: bool,
    ) -> dict[str, Any]:
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
        self._save_current(
            prediction,
            kickoff=kickoff,
            odds_snapshot=odds_snapshot,
            persist_production_evidence=persist_production_evidence,
        )
        return prediction

    async def prepare_context(
        self,
        fixture: dict[str, Any],
        context: dict[str, Any],
        *,
        prediction_timestamp: Any | None = None,
    ) -> None:
        """Normalize shared evidence before creating any immutable snapshots."""

        localize_evidence_players(context)
        recent_form = RecentFormService(self.repository).context_for_fixture(
            fixture,
            as_of=prediction_timestamp,
        )
        if recent_form is not None:
            context["recent_form"] = recent_form
        if self.player_value_service is not None:
            await self.player_value_service.enrich(context, str(fixture.get("league_key") or ""))
        if self.player_stats_service is not None:
            # 球员赛季统计只增强证据层；失败不阻断预测。
            try:
                league_key = str(fixture.get("league_key") or "")
                await self.player_stats_service.enrich(context, league_key, _fixture_season(fixture, league_key))
            except Exception:
                pass
        apply_player_impact(context)
        context.setdefault("elo", self._elo_ratings(prediction_timestamp))
        try:
            from .team_stats import attach_team_stats

            attach_team_stats(
                self.repository,
                fixture,
                context,
                prediction_timestamp=prediction_timestamp,
            )
        except Exception:
            pass
        try:
            from .weather_sync import attach_weather

            attach_weather(fixture, context)
        except Exception:
            pass
        try:
            from .discipline_sync import attach_discipline

            attach_discipline(self.repository, fixture, context, prediction_timestamp)
        except Exception:
            pass
        try:
            from .transfers_sync import attach_transfers

            attach_transfers(self.repository, fixture, context)
        except Exception:
            pass
        _attach_match_context(fixture, context)

    def prepare_snapshot(
        self,
        fixture: dict[str, Any],
        context: dict[str, Any],
        *,
        prediction_timestamp: Any | None = None,
    ) -> dict[str, Any]:
        standings = _standings_evidence(
            self.repository,
            fixture,
            prediction_timestamp=prediction_timestamp,
        )
        quality = _data_completeness(context, standings)
        return {
            "evidence": _evidence_snapshot(
                fixture,
                context,
                standings,
                captured_at=prediction_timestamp,
            ),
            "odds": _odds_snapshot(
                fixture,
                context,
                captured_at=prediction_timestamp,
            ),
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

    def _save_current(
        self,
        prediction: dict[str, Any],
        *,
        kickoff: datetime | None,
        odds_snapshot: dict[str, Any] | None,
        persist_production_evidence: bool = True,
    ) -> None:
        if (
            kickoff is not None
            and not bool(getattr(self.repository, "is_historical_replay", False))
            and _utc_now() >= kickoff
        ):
            raise ValueError("模型返回时比赛已开球，赛前预测已冻结，不能写入")
        expected_goals = prediction.get("expected_goals") or {}
        revision = {
            "prediction_id": prediction["id"],
            "match_id": prediction["fixture_id"],
            "fixture_id": prediction["fixture_id"],
            "competition_id": self.competition_id,
            "model_key": self.model_key,
            "prediction_cutoff_at": prediction.get("prediction_cutoff_at") or prediction["created_at"],
            "model_version": prediction["model_version"],
            "feature_version": prediction.get("feature_version") or FEATURE_VERSION,
            "feature_snapshot_id": prediction.get("feature_snapshot_id"),
            "evidence_snapshot_id": prediction.get("evidence_snapshot_id"),
            "probability_home": (prediction.get("probabilities") or {}).get("home"),
            "probability_draw": (prediction.get("probabilities") or {}).get("draw"),
            "probability_away": (prediction.get("probabilities") or {}).get("away"),
            "expected_home_goals": expected_goals.get("home"),
            "expected_away_goals": expected_goals.get("away"),
            "uncertainty": prediction.get("uncertainty") or {
                "forecast_confidence": prediction.get("forecast_confidence")
            },
            "data_quality": {
                "score": prediction.get("data_completeness"),
                "fields": prediction.get("evidence_fields") or {},
            },
            "model_agreement": prediction.get("model_agreement"),
            "created_at": prediction["created_at"],
        }
        is_historical_replay = bool(
            getattr(self.repository, "is_historical_replay", False)
        )
        production_saver = None
        if not is_historical_replay and persist_production_evidence:
            production_saver = getattr(
                self.repository,
                "save_prediction_with_production_evidence",
                None,
            )
        production_evidence_reason = None
        stored_market_snapshot = None
        if not is_historical_replay and callable(production_saver):
            if kickoff is None:
                raise ValueError("Production prediction kickoff is required")
            leakage_audit = prediction.get("leakage_audit") or {}
            leakage_audit_id = str(leakage_audit.get("audit_id") or "")
            if not leakage_audit_id:
                raise ValueError("Production prediction leakage audit id is required")
            try:
                round4_result = TransparentProbabilityEngine().calculate(
                    prediction.get("feature_snapshot") or {},
                    match_id=str(prediction["fixture_id"]),
                    feature_snapshot_id=prediction.get("feature_snapshot_id"),
                )
            except ProbabilityEngineError as error:
                if str(error) != "insufficient critical feature evidence for both teams":
                    raise
                production_saver = None
                production_evidence_reason = "insufficient_critical_feature_evidence"
            if callable(production_saver):
                odds_reader = getattr(self.repository, "odds_snapshots", None)
                if callable(odds_reader):
                    round5_odds = list(
                        odds_reader(str(prediction["fixture_id"])) or []
                    )
                else:
                    round5_odds = [odds_snapshot] if odds_snapshot else []
                round5_result = Round5ProbabilityEngine().calculate(
                    round4_result,
                    round5_odds,
                    kickoff=kickoff,
                )
                model_probability = dict(round5_result["model_probability"])
                round5_audit = round5_result["round5_probability_audit"]
                revision.update(
                    {
                        "probabilities": model_probability,
                        "model_probabilities": model_probability,
                        "probability_home": model_probability["home"],
                        "probability_draw": model_probability["draw"],
                        "probability_away": model_probability["away"],
                        "probability_model_version": round5_audit.get(
                            "probability_model_version"
                        ),
                        "probability_calculation_version": round5_audit.get(
                            "probability_calculation_version"
                        ),
                    }
                )
        if not is_historical_replay and callable(production_saver):
            stored = production_saver(
                prediction,
                revision,
                round5_result,
                kickoff_at=kickoff,
                leakage_audit_id=leakage_audit_id,
            )
            stored_revision = (
                stored.get("revision") if isinstance(stored, dict) else None
            )
            stored_market_snapshot = (
                stored.get("market_snapshot") if isinstance(stored, dict) else None
            )
            if not isinstance(stored_revision, dict):
                raise ValueError(
                    "Production evidence writer did not return a prediction revision"
                )
        else:
            atomic_saver = getattr(self.repository, "save_prediction_with_revision", None)
            if callable(atomic_saver):
                stored_revision = atomic_saver(prediction, revision)
            else:
                self.repository.save(prediction)
                revision_saver = getattr(self.repository, "save_prediction_revision", None)
                stored_revision = revision_saver(revision) if callable(revision_saver) else None
        if stored_revision:
            prediction["revision_number"] = stored_revision.get("revision_number")
            if callable(production_saver):
                prediction["prediction_revision_id"] = (
                    f"{prediction['id']}:{stored_revision['revision_number']}"
                )
                if isinstance(stored_market_snapshot, dict):
                    prediction["round5_market_snapshot_id"] = stored_market_snapshot.get(
                        "market_snapshot_id"
                    )
            elif production_evidence_reason:
                prediction["production_evidence_status"] = "unavailable"
                prediction["production_evidence_reason"] = production_evidence_reason


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _evidence_snapshot(
    fixture: dict[str, Any],
    context: dict[str, Any],
    standings: dict[str, Any],
    *,
    captured_at: Any | None = None,
) -> dict[str, Any]:
    captured = parse_timestamp(captured_at) or datetime.now(UTC)
    created_at = captured.isoformat()
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


def _odds_snapshot(
    fixture: dict[str, Any],
    context: dict[str, Any],
    *,
    captured_at: Any | None = None,
) -> dict[str, Any] | None:
    odds = context.get("odds")
    if not isinstance(odds, dict):
        return None
    captured_at = (parse_timestamp(captured_at) or datetime.now(UTC)).isoformat()
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
            "status": fixture.get("status"),
            "score": fixture.get("score"),
            "minute": fixture.get("minute") or fixture.get("elapsed"),
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
                    "yellow_cards": (player.get("statistics") or {}).get("yellow_cards"),
                    "red_cards": (player.get("statistics") or {}).get("red_cards"),
                    "market_value_eur": player.get("market_value_eur"),
                }
                for player in (context.get("squads") or {}).get(side, [])[:35]
            ]
            for side in ("home", "away")
        },
        "player_impact": public_payload(context.get("player_impact")),
        "team_stats": public_payload(context.get("team_stats")),
        "odds": _model_odds(context.get("odds")),
        "standings": standings,
        "data_completeness": quality,
        "evidence_source": context.get("source"),
        "evidence_synced_at": context.get("synced_at"),
    }


CUP_LEAGUES = {"cfa_cup", "ucl", "acl"}


def _attach_match_context(fixture: dict[str, Any], context: dict[str, Any]) -> None:
    """Competition stage / cup context for rotation and motivation reading."""

    league_key = str(fixture.get("league_key") or "")
    evidence = fixture.get("evidence") if isinstance(fixture.get("evidence"), dict) else {}
    competition = evidence.get("competition") if isinstance(evidence.get("competition"), dict) else {}
    league = fixture.get("league") if isinstance(fixture.get("league"), dict) else {}
    round_text = str(competition.get("round") or "") or None
    name = str(competition.get("name") or league.get("name") or "") or None
    is_cup = league_key in CUP_LEAGUES
    if round_text is None and not is_cup and name is None:
        return
    context["match_context"] = {
        "competition": name,
        "round": round_text,
        "is_cup": is_cup,
        "note": "杯赛或联赛阶段可能影响轮换与战意" if is_cup else None,
        "source": "api-football" if round_text else "fixture",
    }


def _fixture_season(fixture: dict[str, Any], league_key: str) -> str:
    """Season key for player statistics lookups (provider season year)."""

    from datetime import date as _date, datetime as _datetime

    from .competition_registry import season_for

    raw = str(fixture.get("fixture_date") or "")
    try:
        day = _date.fromisoformat(raw[:10])
    except ValueError:
        day = _datetime.now(UTC).date()
    return str(season_for(league_key, day))


def _model_odds(odds: Any) -> Any:
    """Drop asian-handicap quotes that carry no numeric line.

    Dongqiudi sometimes serves asian odds with only a Chinese label ("受平/半")
    and a null line. Presenting them to the model makes it claim an available
    handicap forecast, which then fails contract validation and kills the
    whole prediction.
    """

    if not isinstance(odds, dict) or odds.get("asian_handicap") is not None:
        return odds
    return {
        key: value
        for key, value in odds.items()
        if not str(key).startswith("asian_handicap")
    }


def _model_availability(value: Any) -> dict[str, Any]:
    availability = public_payload(value or {})
    availability["notes"] = [
        f"{player.get('name') or '待核验球员'}：{player.get('reason') or '原因待核验'}"
        for player in availability.get("players") or []
    ]
    return availability


def _standings_evidence(
    repository: Any,
    fixture: dict[str, Any],
    *,
    prediction_timestamp: Any | None = None,
) -> dict[str, Any]:
    reader = getattr(repository, "league_snapshots", None)
    snapshots = reader(fixture.get("league_key")) if callable(reader) else []
    cutoff = parse_timestamp(prediction_timestamp)
    eligible = [
        item
        for item in snapshots
        if cutoff is None
        or (
            (updated_at := parse_timestamp(item.get("updated_at"))) is not None
            and updated_at <= cutoff
        )
    ]
    snapshot = max(
        eligible,
        key=lambda item: parse_timestamp(item.get("updated_at")) or datetime.min.replace(tzinfo=UTC),
        default={},
    )
    table = snapshot.get("standings") or []
    return {
        "snapshot_id": snapshot.get("snapshot_id") or snapshot.get("id"),
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
    # Lineup state is excluded on purpose: unconfirmed lineups are already
    # surfaced via `phase` and the `lineup_unconfirmed` warning, so counting
    # them here would double-penalize every preliminary prediction.
    fields = {
        "standings": bool(standings.get("home") and standings.get("away")),
        "recent_form": bool(recent.get("home") and recent.get("away")),
        "head_to_head": bool(context.get("head_to_head")),
        "squads": bool(squads.get("home") and squads.get("away")),
        "availability": bool((context.get("availability") or {}).get("updated_at")),
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
