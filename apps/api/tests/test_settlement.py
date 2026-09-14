from datetime import UTC, datetime, timedelta

from app.bankroll import BankrollService
from app.database import PredictionRepository
from app.prompt_contract import DEFAULT_PROMPT_CONTRACT
from app.settlement import SettlementService, _bet_return


def prediction() -> dict:
    return {
        "id": "prediction-1",
        "fixture_id": "fixture-1",
        "created_at": "2026-08-26T00:00:00+00:00",
        "phase": "preliminary",
        "model_version": "deepseek:deepseek-v4-flash",
        "probabilities": {"home": 0.6, "draw": 0.25, "away": 0.15},
        "predicted_outcome": "home",
        "data_completeness": 0.75,
        "ai": {
            "status": "completed",
            "provider": "deepseek",
            "prompt_version": DEFAULT_PROMPT_CONTRACT.version,
        },
        "decision": {
            "status": "bet",
            "market": "1x2",
            "selection": "home",
            "model_confidence": 0.7,
            "stake_fraction": 0.02,
            "reason": "测试执行",
            "reason_codes": [],
        },
    }


def fixture(status: str = "scheduled") -> dict:
    return {
        "id": "fixture-1",
        "fixture_date": "2099-08-27",
        "kickoff": "2099-08-27T12:00:00+00:00",
        "status": status,
        "league_key": "epl",
        "home_team": {"name": "Home"},
        "away_team": {"name": "Away"},
        "score": {"home": 2, "away": 0} if status == "finished" else None,
    }


def test_prediction_and_bet_settlement_are_idempotent(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "settlement.db"))
    repository.initialize()
    repository.save(prediction())
    bankroll = BankrollService(repository)
    bankroll.place_for_prediction(
        prediction(),
        fixture(),
        {
            "odds": {
                "home": 2.1,
                "draw": 3.2,
                "away": 3.6,
                "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            }
        },
    )
    service = SettlementService(repository)

    first = service.settle_fixture(fixture("finished"))
    second = service.settle_fixture(fixture("finished"))

    evaluation = first["items"][0]["prediction"]
    assert evaluation["correct"] is True
    assert evaluation["brier_score"] == 0.245
    assert first["items"][0]["bet"]["net_profit"] == 11.0
    assert second["items"][0]["bet"]["net_profit"] == 11.0
    assert repository.current_balance() == 1011.0
    assert len(repository.bankroll_transactions()) == 3
    metrics = service.metrics("epl", "unknown")
    assert metrics["accuracy"] == 1.0
    assert metrics["average_data_completeness"] == 0.75
    assert metrics["asian_handicap_results"]["half_win"] == 0
    assert bankroll.summary()["equity_curve"][-1]["balance"] == 1011.0


def test_asian_half_win_and_half_loss_returns() -> None:
    home_bet = {"market": "asian_handicap", "selection": "home_handicap", "handicap_line": -0.75, "stake": 20, "odds": 2.0}
    away_bet = {"market": "asian_handicap", "selection": "away_handicap", "handicap_line": -0.75, "stake": 20, "odds": 2.0}

    assert _bet_return(home_bet, 1, "home") == ("half_win", 30.0)
    assert _bet_return(away_bet, 1, "home") == ("half_loss", 10.0)


def test_asian_settlement_is_aggregated_in_metrics(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "asian.db"))
    repository.initialize()
    asian_prediction = prediction()
    asian_prediction["decision"] = {
        "status": "bet",
        "market": "asian_handicap",
        "selection": "home_handicap",
        "model_confidence": 0.7,
        "stake_fraction": 0.02,
        "reason": "Test edge",
        "reason_codes": [],
    }
    asian_prediction["asian_handicap"] = {
        "line": -0.75,
        # Plausible cover distribution: a certain cover (1.0) is rejected as a
        # data anomaly by the portfolio plausibility gate.
        "home_settlement": {
            "full_win": 0.5,
            "half_win": 0.2,
            "push": 0.05,
            "half_loss": 0.15,
            "full_loss": 0.1,
        },
    }
    repository.save(asian_prediction)
    BankrollService(repository).place_for_prediction(
        asian_prediction,
        fixture(),
        {
            "odds": {
                "home": 2.1,
                "draw": 3.2,
                "away": 3.6,
                "asian_handicap": -0.75,
                "asian_handicap_home_odd": 2.0,
                "asian_handicap_away_odd": 2.0,
                "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            }
        },
    )
    service = SettlementService(repository)

    service.settle_fixture({**fixture("finished"), "score": {"home": 1, "away": 0}})

    assert service.metrics()["asian_handicap_results"]["half_win"] == 1


def test_metrics_expose_forecast_market_portfolio_layers_and_quality_gate(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "quality.db"))
    repository.initialize()
    item = prediction()
    item["experiment"] = {
        "model_key": "deepseek",
        "strategy_id": "baseline",
        "strategy_version": "v1",
        "strategy_name": "基准",
        "prompt_version": DEFAULT_PROMPT_CONTRACT.version,
        "decision_policy_version": "football-sim-portfolio-v1",
        "ai_view_version": "football-ai-view-v1",
        "execution_config_version": "deepseek:baseline:v1",
    }
    item["market_assessment"] = {
        "markets": [
            {"market": "1x2", "selection": "home", "de_vig_probability": 0.55},
            {"market": "1x2", "selection": "draw", "de_vig_probability": 0.25},
            {"market": "1x2", "selection": "away", "de_vig_probability": 0.20},
        ]
    }
    repository.save(item)

    metrics = SettlementService(repository).settle_fixture(fixture("finished"))
    report = SettlementService(repository).metrics()

    evaluation = metrics["items"][0]["prediction"]
    assert evaluation["log_loss"] == 0.5108
    assert evaluation["rps"] == 0.0913
    assert evaluation["market_probabilities"] == {"home": 0.55, "draw": 0.25, "away": 0.2}
    assert report["average_log_loss"] == 0.5108
    assert report["average_rps"] == 0.0913
    assert report["market_comparison"]["sample_size"] == 1
    assert report["market_comparison"]["brier_improvement"] == 0.06
    assert report["decision_counts"] == {"bet": 1, "no_bet": 0, "insufficient_data": 0, "unknown": 0}
    assert report["quality_gate"]["status"] == "INSUFFICIENT_SAMPLE"
    assert report["quality_gate"]["mode"] == "SHADOW_ONLY"
    assert "MIN_CLV_SAMPLES" in report["quality_gate"]["failures"]
    assert report["experiment"]["execution_config_version"] == "deepseek:baseline:v1"


def test_over_under_settlement_uses_total_goals() -> None:
    over = {"market": "over_under", "handicap_line": 2.5, "stake": 20, "odds": 1.85}
    push_line = {"market": "over_under", "handicap_line": 2.0, "stake": 20, "odds": 1.85}

    assert _bet_return(over, 0, None, total_goals=3) == ("full_win", 37.0)
    assert _bet_return(over, 0, None, total_goals=2) == ("full_loss", 0.0)
    assert _bet_return(push_line, 0, None, total_goals=2) == ("push", 20.0)


def test_score_correction_resettles_existing_evaluation(tmp_path, monkeypatch) -> None:
    """A post-settlement score correction recomputes the evaluation row."""

    from app.settlement import SettlementService
    from app.database import PredictionRepository

    repository = PredictionRepository(str(tmp_path / "correct.db"), "dual-model-v1")
    repository.initialize()
    kickoff = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    repository.replace_fixtures(
        kickoff[:10],
        kickoff[:10],
        [
            {
                "id": "fixture-corr",
                "provider_id": 1,
                "league_key": "epl",
                "fixture_date": kickoff[:10],
                "kickoff": kickoff,
                "status": "finished",
                "home_team": {"name": "A"},
                "away_team": {"name": "B"},
                "score": {"home": 0, "away": 2},
                "is_demo": False,
                "external_ids": {},
            }
        ],
        datetime.now(UTC).isoformat(),
    )
    repository.save(
        {
            "id": "pred-corr",
            "fixture_id": "fixture-corr",
            "created_at": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
            "phase": "preliminary",
            "model_key": "deepseek",
            "model_version": "deepseek:test",
            "competition_id": "dual-model-v1",
            "ai": {
                "status": "completed",
                "prompt_version": DEFAULT_PROMPT_CONTRACT.version,
                "evidence_version": "fixture-evidence-v3",
            },
            "model_probabilities": {"home": 0.2, "draw": 0.3, "away": 0.5},
            "probabilities": {"home": 0.2, "draw": 0.3, "away": 0.5},
        }
    )
    service = SettlementService(repository, "dual-model-v1")

    service.settle_finished()
    first = repository.settlement_for_prediction("pred-corr")
    assert first["actual_outcome"] == "away"
    assert first["correct"] is True

    # 数据源赛后修正比分为 1-1：下一次结算任务用新赛果重算。
    fixture = repository.fixture("fixture-corr")
    fixture["score"] = {"home": 1, "away": 1}
    repository.upsert_fixture(fixture)
    service.settle_finished()

    corrected = repository.settlement_for_prediction("pred-corr")
    assert corrected["actual_outcome"] == "draw"
    assert corrected["correct"] is False
    assert corrected["prior_actual_outcome"] == "away"
    assert corrected["score_corrected_at"]
    # 预测侧冻结字段不随修正改变。
    assert corrected["model_probabilities"] == first["model_probabilities"]
