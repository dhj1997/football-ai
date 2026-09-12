from app.data import demo_context, demo_fixtures
from app.prediction_service import PredictionService, _data_completeness, _model_input
from app.prompt_contract import DEFAULT_PROMPT_CONTRACT
import pytest


pytestmark = pytest.mark.asyncio


class FakeRepository:
    def __init__(self) -> None:
        self.snapshots: list[dict] = []
        self.predictions: list[dict] = []
        self.retention_calls: list[dict] = []

    def save_evidence_snapshot(self, snapshot: dict) -> None:
        self.snapshots.append(snapshot)

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
    context = demo_context(fixture["id"])
    context["source"] = "test"
    context["synced_at"] = "2026-08-26T00:00:00+00:00"
    context["odds"] = None
    return fixture, context


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
    assert repository.retention_calls == [{
        "prompt_version": DEFAULT_PROMPT_CONTRACT.version,
        "competition_id": "legacy",
        "fixture_id": fixture["id"],
        "model_key": "deepseek",
    }]


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
