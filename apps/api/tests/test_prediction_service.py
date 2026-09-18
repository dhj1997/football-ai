from datetime import UTC, datetime, timedelta

from app import prediction_service as prediction_service_module
from app.data import demo_context, demo_fixtures
from app.database import PredictionRepository
from app.dual_prediction_service import DualPredictionService
from app.leakage_audit import FutureDataLeakageError
from app.prediction_service import PredictionService, _data_completeness, _model_input
from app.prompt_contract import DEFAULT_PROMPT_CONTRACT
import pytest


pytestmark = pytest.mark.asyncio


class FakeRepository:
    def __init__(self) -> None:
        self.snapshots: list[dict] = []
        self.feature_snapshots: list[dict] = []
        self.leakage_audits: list[dict] = []
        self.predictions: list[dict] = []
        self.retention_calls: list[dict] = []

    def save_evidence_snapshot(self, snapshot: dict) -> None:
        self.snapshots.append(snapshot)

    def evidence_snapshot(self, snapshot_id: str) -> dict | None:
        return next(
            (snapshot for snapshot in self.snapshots if snapshot["id"] == snapshot_id),
            None,
        )

    def save_feature_snapshot(self, snapshot: dict) -> dict:
        self.feature_snapshots.append(snapshot)
        return snapshot

    def save_leakage_audit(self, audit: dict) -> dict:
        self.leakage_audits.append(audit)
        return audit

    def save(self, prediction: dict) -> None:
        self.predictions.append(prediction)

    def prune_prediction_history(self, prompt_version: str, **filters) -> None:
        self.retention_calls.append({"prompt_version": prompt_version, **filters})

    def league_snapshots(self, league_key: str) -> list[dict]:
        return [
            {
                "source": "espn",
                "season": {"year": 2026, "name": "2026-27"},
                "updated_at": "2026-08-26T00:00:00+00:00",
                "standings": [
                    {"team": {"name": "曼彻斯特城", "original_name": "Manchester City"}, "rank": 1, "points": 3},
                    {"team": {"name": "托特纳姆热刺", "original_name": "Tottenham Hotspur"}, "rank": 2, "points": 3},
                ],
            }
        ]


class ProductionRepository(FakeRepository):
    def __init__(self, *, production_error: Exception | None = None) -> None:
        super().__init__()
        self.production_error = production_error
        self.production_writes: list[dict] = []
        self.revision_writes: list[dict] = []

    def save_prediction_with_production_evidence(
        self,
        prediction: dict,
        revision: dict,
        round5_result: dict,
        *,
        kickoff_at: datetime,
        leakage_audit_id: str,
    ) -> dict:
        self.production_writes.append(
            {
                "prediction": prediction,
                "revision": revision,
                "round5_result": round5_result,
                "kickoff_at": kickoff_at,
                "leakage_audit_id": leakage_audit_id,
            }
        )
        if self.production_error is not None:
            raise self.production_error
        return {
            "revision": {**revision, "revision_number": 1},
            "market_snapshot": {"market_snapshot_id": "round5-production:test"},
        }

    def save_prediction_with_revision(
        self,
        prediction: dict,
        revision: dict,
    ) -> dict:
        self.revision_writes.append({"prediction": prediction, "revision": revision})
        return {**revision, "revision_number": 1}


class HistoricalReplayRepository(ProductionRepository):
    is_historical_replay = True

    @property
    def save_prediction_with_production_evidence(self):
        pytest.fail("historical replay must not resolve the production writer")


class FakeDeepSeek:
    model = "deepseek-v4-flash"

    def __init__(self, configured: bool = True) -> None:
        self.configured = configured
        self.model_input: dict | None = None

    async def assess(self, model_input: dict) -> dict:
        self.model_input = model_input
        assert model_input["fixture"]["home_team"]
        return {
            "assessment": {
                "probabilities": {"home": 0.56, "draw": 0.25, "away": 0.19},
                "predicted_outcome": "home",
                "forecast_confidence": 0.65,
                "asian_handicap_forecast": {
                    "available": False,
                    "line": None,
                    "home_cover_probability": None,
                    "away_cover_probability": None,
                    "confidence": 0.0,
                    "reason": "没有可用的亚洲让球盘口。",
                },
                "player_analysis": {
                    "key_available_players": [],
                    "key_absent_players": [],
                    "replacement_gap": "当前没有可靠阵容数据。",
                    "attack_impact": "进攻球员证据不足。",
                    "defense_impact": "防守球员证据不足。",
                },
                "bet_recommendation": {
                    "status": "no_bet",
                    "market": "no_bet",
                    "selection": "none",
                    "reason": "当前没有可校验赔率，不建议下注。",
                },
                "analysis_summary": "主队证据更强，但阵容数据仍不完整。",
                "risk_factors": ["缺少确认首发"],
                "missing_evidence": ["球员阵容"],
            },
            "requested_model": self.model,
            "returned_model": self.model,
            "prompt_version": DEFAULT_PROMPT_CONTRACT.version,
            "evidence_version": "fixture-evidence-v3",
            "request_id": "request-1",
            "usage": {"total_tokens": 30},
        }


def real_fixture_and_context() -> tuple[dict, dict]:
    fixture = demo_fixtures()[0]
    fixture = {**fixture, "id": "api-123", "is_demo": False}
    fixture["kickoff"] = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    context = demo_context(fixture["id"])
    context["source"] = "test"
    context["synced_at"] = "2026-08-26T00:00:00+00:00"
    context["odds"] = None
    return fixture, context


def persistence_prediction() -> dict:
    cutoff = "2026-09-17T08:00:00+00:00"
    return {
        "id": "prediction-production-test",
        "fixture_id": "fixture-production-test",
        "created_at": cutoff,
        "prediction_cutoff_at": cutoff,
        "model_version": "deepseek:test",
        "feature_version": "round3-feature-engine-v2",
        "feature_snapshot_id": "feature:production-test",
        "evidence_snapshot_id": "evidence:production-test",
        "probabilities": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "expected_goals": {"home": 1.4, "away": 0.9},
        "feature_snapshot": {"snapshot_id": "feature:production-test"},
        "leakage_audit": {"audit_id": "leakage:production-test", "status": "PASS"},
    }


async def test_successful_ai_prediction_links_immutable_evidence() -> None:
    fixture, context = real_fixture_and_context()
    context["availability"] = {
        "updated_at": "2026-08-26T00:00:00+00:00",
        "notes": ["Unknown Prospect：Injury"],
        "players": [
            {
                "team": "home",
                "name": "Unknown Prospect",
                "original_name": "Unknown Prospect",
                "reason": "伤病",
            }
        ],
    }
    repository = FakeRepository()
    provider = FakeDeepSeek()
    result = await PredictionService(provider, repository).create(fixture, context)

    assert result["ai"]["status"] == "completed"
    assert result["model_version"] == "deepseek:deepseek-v4-flash"
    assert result["probabilities"] == {"home": 0.56, "draw": 0.25, "away": 0.19}
    assert result["evidence_snapshot_id"] == repository.snapshots[0]["id"]
    assert result["evidence_hash"] == repository.snapshots[0]["content_hash"]
    assert repository.snapshots[0]["payload"]["standings"]["home"]["rank"] == 1
    assert result["evidence_fields"]["standings"] is True
    assert result["ai"]["prompt_version"] == DEFAULT_PROMPT_CONTRACT.version
    assert result["ai"]["evidence_version"] == "fixture-evidence-v3"
    assert result["experiment"] == {
        "model_key": "deepseek",
        "strategy_id": "baseline",
        "strategy_version": "v1",
        "strategy_name": "基准",
        "prompt_version": DEFAULT_PROMPT_CONTRACT.version,
        "decision_policy_version": "football-sim-portfolio-v1",
        "ai_view_version": "football-ai-view-v1",
        "execution_config_version": "deepseek:baseline:v1",
    }
    assert result["model_recommendation"]["status"] == "no_bet"
    assert result["recommendation"]["is_deterministic"] is True
    assert "Unknown Prospect" not in str(provider.model_input)
    public_name = provider.model_input["availability"]["players"][0]["name"]
    assert public_name.startswith("待核验球员")
    assert provider.model_input["availability"]["notes"] == [f"{public_name}：伤病"]
    assert repository.predictions == [result]
    assert repository.retention_calls == []


async def test_unconfigured_ai_saves_explicit_degraded_prediction() -> None:
    fixture, context = real_fixture_and_context()
    repository = FakeRepository()
    result = await PredictionService(FakeDeepSeek(configured=False), repository).create(fixture, context)

    assert result["ai"]["status"] == "unconfigured"
    assert result["ai"]["prompt_version"] == DEFAULT_PROMPT_CONTRACT.version
    assert result["recommendation"]["market"] == "no_bet"
    assert result["experiment"]["strategy_id"] == "baseline"
    assert len(repository.snapshots) == 1
    assert len(repository.predictions) == 1


async def test_current_prediction_builds_round4_and_round5_for_atomic_writer(
    monkeypatch,
) -> None:
    fixture, context = real_fixture_and_context()
    kickoff = datetime.now(UTC) + timedelta(hours=2)
    fixture["kickoff"] = kickoff.isoformat()
    repository = ProductionRepository()
    calls: dict[str, dict] = {}
    odds_history = [
        {"id": "odds-before-cutoff", "captured_at": "2026-09-17T07:00:00+00:00"},
        {"id": "odds-after-cutoff", "captured_at": "2099-09-17T07:00:00+00:00"},
    ]
    odds_reads: list[str] = []

    def odds_snapshots(fixture_id: str) -> list[dict]:
        odds_reads.append(fixture_id)
        return odds_history

    repository.odds_snapshots = odds_snapshots

    def calculate_round4(self, feature_snapshot, *, match_id, feature_snapshot_id):
        calls["round4"] = {
            "feature_snapshot": feature_snapshot,
            "match_id": match_id,
            "feature_snapshot_id": feature_snapshot_id,
        }
        return {"stage": "round4"}

    def calculate_round5(self, round4_result, odds_snapshots, *, kickoff):
        calls["round5"] = {
            "round4_result": round4_result,
            "odds_snapshots": odds_snapshots,
            "kickoff": kickoff,
        }
        return {
            "stage": "round5",
            "model_probability": {"home": 0.41, "draw": 0.34, "away": 0.25},
            "round5_probability_audit": {
                "model_probability": {"home": 0.41, "draw": 0.34, "away": 0.25},
                "probability_model_version": "poisson-dc-v2.0.0",
                "probability_calculation_version": "round4-probability-engine-v1",
            },
        }

    monkeypatch.setattr(
        prediction_service_module.TransparentProbabilityEngine,
        "calculate",
        calculate_round4,
    )
    monkeypatch.setattr(
        prediction_service_module.Round5ProbabilityEngine,
        "calculate",
        calculate_round5,
    )

    result = await PredictionService(FakeDeepSeek(), repository).create(
        fixture,
        context,
    )

    assert calls["round4"] == {
        "feature_snapshot": result["feature_snapshot"],
        "match_id": fixture["id"],
        "feature_snapshot_id": result["feature_snapshot_id"],
    }
    assert calls["round5"] == {
        "round4_result": {"stage": "round4"},
        "odds_snapshots": odds_history,
        "kickoff": kickoff,
    }
    assert odds_reads == [fixture["id"]]
    assert len(repository.production_writes) == 1
    write = repository.production_writes[0]
    assert write["round5_result"] == {
        "stage": "round5",
        "model_probability": {"home": 0.41, "draw": 0.34, "away": 0.25},
        "round5_probability_audit": {
            "model_probability": {"home": 0.41, "draw": 0.34, "away": 0.25},
            "probability_model_version": "poisson-dc-v2.0.0",
            "probability_calculation_version": "round4-probability-engine-v1",
        },
    }
    assert write["revision"]["probabilities"] == {
        "home": 0.41,
        "draw": 0.34,
        "away": 0.25,
    }
    assert write["revision"]["model_probabilities"] == {
        "home": 0.41,
        "draw": 0.34,
        "away": 0.25,
    }
    assert (
        write["revision"]["probability_home"],
        write["revision"]["probability_draw"],
        write["revision"]["probability_away"],
    ) == (0.41, 0.34, 0.25)
    assert write["revision"]["model_version"] == result["model_version"]
    assert write["revision"]["probability_model_version"] == "poisson-dc-v2.0.0"
    assert write["revision"]["probability_calculation_version"] == (
        "round4-probability-engine-v1"
    )
    assert write["prediction"]["probabilities"] == {
        "home": 0.56,
        "draw": 0.25,
        "away": 0.19,
    }
    assert write["kickoff_at"] == kickoff
    assert write["leakage_audit_id"] == result["leakage_audit"]["audit_id"]
    assert repository.revision_writes == []
    assert repository.predictions == []
    assert result["revision_number"] == 1
    assert result["prediction_revision_id"] == f"{result['id']}:1"
    assert result["round5_market_snapshot_id"] == "round5-production:test"


@pytest.mark.parametrize(
    "field",
    [
        "probability_home",
        "probabilities",
        "model_probabilities",
        "inherited_prediction_probabilities",
    ],
)
async def test_production_writer_rejects_revision_probability_mismatch(
    tmp_path, field: str
) -> None:
    repository = PredictionRepository(str(tmp_path / "probability-mismatch.db"))
    repository.initialize()
    model_probability = {"home": 0.5, "draw": 0.3, "away": 0.2}
    prediction = {
        "id": "prediction-mismatch",
        "fixture_id": "fixture-mismatch",
        "probabilities": model_probability,
    }
    revision = {
        "probability_home": 0.5,
        "probability_draw": 0.3,
        "probability_away": 0.2,
    }
    if field == "inherited_prediction_probabilities":
        prediction["probabilities"] = {"home": 0.51, "draw": 0.29, "away": 0.2}
    elif field == "probability_home":
        revision[field] = 0.51
    else:
        revision[field] = {"home": 0.51, "draw": 0.29, "away": 0.2}

    with pytest.raises(ValueError, match="must match Round 5 model_probability"):
        repository.save_prediction_with_production_evidence(
            prediction,
            revision,
            {"round5_probability_audit": {"model_probability": model_probability}},
            kickoff_at=datetime.now(UTC) + timedelta(hours=1),
            leakage_audit_id="audit-mismatch",
        )

    assert repository.predictions_for_fixture("fixture-mismatch") == []
    assert repository.prediction_revisions(fixture_id="fixture-mismatch") == []
    assert repository.market_snapshots("fixture-mismatch") == []


async def test_real_dual_prediction_persists_two_revisions_and_one_round5_evidence(
    tmp_path,
) -> None:
    class FakeChatGPT(FakeDeepSeek):
        provider_name = "chatgpt"
        model = "gpt-test"

    repository = PredictionRepository(str(tmp_path / "dual-production.db"))
    repository.initialize()
    fixture, context = real_fixture_and_context()
    fixture["season_id"] = "dual-production-test"
    fixture["fixture_date"] = datetime.fromisoformat(fixture["kickoff"]).date().isoformat()
    repository.upsert_fixture(fixture)
    history_base = datetime.now(UTC) - timedelta(days=10)
    for index, (home, away, score) in enumerate(
        (
            ("MCI", "history-a", (2, 0)),
            ("history-b", "MCI", (1, 1)),
            ("TOT", "history-c", (3, 1)),
            ("history-d", "TOT", (0, 1)),
        )
    ):
        kickoff = history_base + timedelta(days=index)
        repository.upsert_fixture(
            {
                "id": f"dual-history-{index}",
                "canonical_fixture_id": f"dual-history-{index}",
                "league_key": "epl",
                "season_id": "dual-production-test",
                "fixture_date": kickoff.date().isoformat(),
                "kickoff": kickoff.isoformat(),
                "result_captured_at": (kickoff + timedelta(hours=3)).isoformat(),
                "status": "finished",
                "score": {"home": score[0], "away": score[1]},
                "home_team": {"code": home},
                "away_team": {"code": away},
            }
        )
    services = {
        "deepseek": PredictionService(
            FakeDeepSeek(), repository, model_key="deepseek", competition_id="epl"
        ),
        "chatgpt": PredictionService(
            FakeChatGPT(), repository, model_key="chatgpt", competition_id="epl"
        ),
    }

    results = await DualPredictionService(services, "epl").create(fixture, context)

    assert {item["model_key"] for item in results} == {"deepseek", "chatgpt"}
    revisions = repository.prediction_revisions(fixture_id=fixture["id"])
    assert len(revisions) == 2
    assert {row["model_key"] for row in revisions} == {"deepseek", "chatgpt"}
    snapshots = repository.market_snapshots(fixture["id"])
    assert len(snapshots) == 1
    audit = snapshots[0]["payload"]["audit"]
    primary = next(row for row in revisions if row["model_key"] == "deepseek")
    assert audit["prediction_revision_id"] == (
        f"{primary['prediction_id']}:{primary['revision_number']}"
    )
    assert primary["probabilities"] == audit["model_probability"]
    assert primary["model_probabilities"] == audit["model_probability"]
    assert primary["probability_model_version"] == audit["probability_model_version"]
    assert primary["probability_calculation_version"] == (
        audit["probability_calculation_version"]
    )
    assert primary["model_version"] == "deepseek:deepseek-v4-flash"
    predictions = repository.predictions_for_fixture(fixture["id"])
    assert len(predictions) == 2
    assert next(row for row in predictions if row["model_key"] == "deepseek")[
        "probabilities"
    ] == {"home": 0.56, "draw": 0.25, "away": 0.19}
    assert primary["probabilities"] != {"home": 0.56, "draw": 0.25, "away": 0.19}


async def test_historical_replay_keeps_revision_write_barrier(monkeypatch) -> None:
    repository = HistoricalReplayRepository()
    prediction = persistence_prediction()

    def unexpected_calculation(*args, **kwargs):
        pytest.fail("historical replay must not build production probability evidence")

    monkeypatch.setattr(
        prediction_service_module.TransparentProbabilityEngine,
        "calculate",
        unexpected_calculation,
    )
    PredictionService(FakeDeepSeek(), repository)._save_current(
        prediction,
        kickoff=datetime(2026, 9, 17, 10, tzinfo=UTC),
        odds_snapshot=None,
    )

    assert repository.production_writes == []
    assert len(repository.revision_writes) == 1
    assert prediction["revision_number"] == 1


async def test_atomic_production_failure_does_not_fallback_to_legacy_writer(
    monkeypatch,
) -> None:
    repository = ProductionRepository(
        production_error=RuntimeError("atomic production write failed")
    )
    prediction = persistence_prediction()
    current_odds = {"id": "current-bundle-odds"}
    round5_odds: list[dict] = []
    monkeypatch.setattr(
        prediction_service_module.TransparentProbabilityEngine,
        "calculate",
        lambda *args, **kwargs: {"stage": "round4"},
    )

    def calculate_round5(self, round4_result, odds_snapshots, *, kickoff):
        round5_odds.extend(odds_snapshots)
        return {
            "stage": "round5",
            "model_probability": {"home": 0.5, "draw": 0.3, "away": 0.2},
            "round5_probability_audit": {"model_probability": {
                "home": 0.5, "draw": 0.3, "away": 0.2,
            }},
        }

    monkeypatch.setattr(
        prediction_service_module.Round5ProbabilityEngine,
        "calculate",
        calculate_round5,
    )

    with pytest.raises(RuntimeError, match="atomic production write failed"):
        PredictionService(FakeDeepSeek(), repository)._save_current(
            prediction,
            kickoff=datetime(2099, 9, 17, 10, tzinfo=UTC),
            odds_snapshot=current_odds,
        )

    assert round5_odds == [current_odds]
    assert len(repository.production_writes) == 1
    assert repository.revision_writes == []
    assert repository.predictions == []


async def test_insufficient_round4_features_keep_revision_without_production_evidence(
    monkeypatch,
) -> None:
    repository = ProductionRepository()
    prediction = persistence_prediction()

    def insufficient(*args, **kwargs):
        raise prediction_service_module.ProbabilityEngineError(
            "insufficient critical feature evidence for both teams"
        )

    monkeypatch.setattr(
        prediction_service_module.TransparentProbabilityEngine,
        "calculate",
        insufficient,
    )

    PredictionService(FakeDeepSeek(), repository)._save_current(
        prediction,
        kickoff=datetime(2099, 9, 17, 10, tzinfo=UTC),
        odds_snapshot=None,
    )

    assert repository.production_writes == []
    assert len(repository.revision_writes) == 1
    assert prediction["production_evidence_status"] == "unavailable"
    assert prediction["production_evidence_reason"] == (
        "insufficient_critical_feature_evidence"
    )


async def test_future_feature_is_rejected() -> None:
    cutoff = "2026-09-15T12:00:00+00:00"
    fixture = {
        "id": "fixture-future-feature",
        "league_key": "epl",
        "kickoff": "2026-09-15T14:00:00+00:00",
        "status": "scheduled",
        "home_team": {"name": "Manchester City"},
        "away_team": {"name": "Tottenham Hotspur"},
        "score": None,
        "is_demo": False,
    }
    context = {
        "source": "test",
        "synced_at": cutoff,
        "recent_form": {"home": [], "away": [], "updated_at": cutoff},
        "teams": {"home": {}, "away": {}},
        "squads": {"home": [], "away": []},
        "availability": {},
        "lineup": {},
        "odds": {
            "home": 2.0,
            "draw": 3.2,
            "away": 3.8,
            "updated_at": "2026-09-15T12:00:01+00:00",
            "source": "future-odds",
        },
    }
    repository = FakeRepository()
    provider = FakeDeepSeek()

    with pytest.raises(FutureDataLeakageError, match="Future data leakage"):
        await PredictionService(provider, repository).create(
            fixture,
            context,
            prepared_context=True,
            prediction_timestamp=cutoff,
        )

    assert repository.predictions == []
    assert provider.model_input is None
    assert repository.feature_snapshots[0]["leakage_detected"] is True
    assert repository.leakage_audits[0]["status"] == "FAIL"
    assert any(
        violation["feature_name"] == "odds"
        for violation in repository.leakage_audits[0]["violations"]
    )


async def test_pre_match_prediction_is_frozen() -> None:
    cutoff = "2026-09-15T12:00:00+00:00"
    fixture = {
        "id": "fixture-frozen-at-kickoff",
        "kickoff": cutoff,
        "status": "live",
    }
    repository = FakeRepository()
    provider = FakeDeepSeek()

    with pytest.raises(ValueError, match="赛前预测已冻结"):
        await PredictionService(provider, repository).create(
            fixture,
            {},
            prediction_timestamp=cutoff,
        )

    assert repository.snapshots == []
    assert repository.feature_snapshots == []
    assert repository.leakage_audits == []
    assert repository.predictions == []
    assert provider.model_input is None


async def test_model_result_crossing_kickoff_is_not_persisted(monkeypatch) -> None:
    fixture, context = real_fixture_and_context()
    kickoff = datetime.now(UTC) + timedelta(minutes=5)
    fixture["kickoff"] = kickoff.isoformat()
    repository = FakeRepository()
    provider = FakeDeepSeek()
    assess = provider.assess

    async def assess_after_kickoff(model_input: dict) -> dict:
        response = await assess(model_input)
        monkeypatch.setattr(prediction_service_module, "_utc_now", lambda: kickoff)
        return response

    provider.assess = assess_after_kickoff

    with pytest.raises(ValueError, match="模型返回时比赛已开球"):
        await PredictionService(provider, repository).create(fixture, context)

    assert provider.model_input is not None
    assert repository.predictions == []
    assert len(repository.snapshots) == 1
    assert len(repository.feature_snapshots) == 1
    assert repository.leakage_audits[0]["status"] == "PASS"


def test_data_completeness_excludes_lineup_double_penalty() -> None:
    context = {
        "recent_form": {"home": [{"x": 1}], "away": [{"x": 1}]},
        "head_to_head": [{"x": 1}],
        "squads": {"home": [{"x": 1}], "away": [{"x": 1}]},
        "availability": {"updated_at": "2026-09-10T00:00:00+00:00"},
        "odds": {"home": 2.0},
    }
    standings = {"home": {"x": 1}, "away": {"x": 1}}

    quality = _data_completeness(context, standings)

    assert quality["score"] == 1.0
    assert "lineup" not in quality["fields"]
    assert quality["missing"] == []


def test_data_completeness_counts_five_of_six_when_one_field_missing() -> None:
    context = {
        "recent_form": {"home": [{"x": 1}], "away": [{"x": 1}]},
        "head_to_head": [{"x": 1}],
        "squads": {"home": [{"x": 1}], "away": [{"x": 1}]},
        "availability": {"updated_at": "2026-09-10T00:00:00+00:00"},
    }
    standings = {"home": {"x": 1}, "away": {"x": 1}}

    quality = _data_completeness(context, standings)

    assert quality["score"] == pytest.approx(5 / 6, abs=1e-3)
    assert quality["missing"] == ["odds"]


def test_model_input_strips_asian_odds_without_numeric_line() -> None:
    """Dongqiudi sometimes serves asian odds with a label but no numeric line;
    keeping them makes the model claim an unavailable handicap and fail validation."""

    fixture = {"id": "f1", "league_key": "csl"}
    context = {
        "odds": {
            "home": 2.1, "draw": 3.2, "away": 3.6,
            "asian_handicap": None,
            "asian_handicap_home_odd": 0.78,
            "asian_handicap_away_odd": 1.03,
            "updated_at": "2026-09-11T00:00:00+00:00",
        }
    }

    model_input = _model_input(fixture, context, {"home": {}, "away": {}}, {"score": 1.0})

    assert "asian_handicap" not in model_input["odds"]
    assert "asian_handicap_home_odd" not in model_input["odds"]
    assert model_input["odds"]["home"] == 2.1


def test_model_input_keeps_asian_odds_with_numeric_line() -> None:
    fixture = {"id": "f1", "league_key": "epl"}
    context = {
        "odds": {
            "home": 1.9, "draw": 3.4, "away": 4.2,
            "asian_handicap": -0.5,
            "asian_handicap_home_odd": 1.95,
            "asian_handicap_away_odd": 1.9,
        }
    }

    model_input = _model_input(fixture, context, {"home": {}, "away": {}}, {"score": 1.0})

    assert model_input["odds"]["asian_handicap"] == -0.5
    assert model_input["odds"]["asian_handicap_home_odd"] == 1.95
