from app.bankroll import BankrollService
from app.database import PredictionRepository


def fixture() -> dict:
    return {
        "id": "fixture-1",
        "fixture_date": "2026-08-27",
        "kickoff": "2026-08-27T12:00:00+00:00",
        "status": "scheduled",
        "league_key": "epl",
        "home_team": {"name": "Home"},
        "away_team": {"name": "Away"},
    }


def prediction(prediction_id: str = "prediction-1") -> dict:
    return {
        "id": prediction_id,
        "model_version": "deepseek:deepseek-v4-flash",
        "probabilities": {"home": 0.6, "draw": 0.25, "away": 0.15},
        "data_completeness": 0.85,
        "ai": {"status": "completed"},
        "recommendation": {
            "market": "1x2",
            "selection": "home",
            "confidence": 0.7,
            "recommended_stake_fraction": 0.02,
        },
    }


def context() -> dict:
    return {"odds": {"home": 2.1, "draw": 3.2, "away": 3.6}}


def test_initial_balance_and_duplicate_bet_protection(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "bankroll.db"))
    repository.initialize()
    service = BankrollService(repository)

    first = service.place_for_prediction(prediction(), fixture(), context())
    duplicate = service.place_for_prediction(prediction(), fixture(), context())

    assert first is not None
    assert first["stake"] == 20.0
    assert duplicate["id"] == first["id"]
    assert repository.current_balance() == 980.0
    assert len(repository.bankroll_transactions()) == 2
    assert service.summary()["equity"] == 1000.0
    assert service.summary()["net_profit"] == 0.0
    assert service.summary()["equity_curve"][0]["balance"] == 1000.0


def test_missing_price_and_degraded_ai_never_place_a_bet(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "bankroll.db"))
    repository.initialize()
    service = BankrollService(repository)

    assert service.place_for_prediction(prediction(), fixture(), {"odds": None}) is None
    degraded = prediction()
    degraded["ai"] = {"status": "failed"}
    assert service.place_for_prediction(degraded, fixture(), context()) is None
    assert repository.current_balance() == 1000.0


def test_incomplete_evidence_or_no_price_edge_never_places_a_bet(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "bankroll.db"))
    repository.initialize()
    service = BankrollService(repository)
    incomplete = prediction("incomplete")
    incomplete["data_completeness"] = 0.69
    no_edge = prediction("no-edge")
    no_edge["probabilities"]["home"] = 0.4

    assert service.place_for_prediction(incomplete, {**fixture(), "id": "incomplete"}, context()) is None
    assert service.place_for_prediction(no_edge, {**fixture(), "id": "no-edge"}, context()) is None
    assert repository.bets() == []


def test_daily_unsettled_exposure_is_capped(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "bankroll.db"))
    repository.initialize()
    service = BankrollService(repository)

    for index in range(10):
        next_fixture = {**fixture(), "id": f"fixture-{index}"}
        service.place_for_prediction(prediction(f"prediction-{index}"), next_fixture, context())

    exposure = sum(item["stake"] for item in repository.bets(status="placed"))
    assert exposure <= 100.0
    assert all(item["stake"] <= item["balance_before"] * 0.02 for item in repository.bets())


def test_multiple_prediction_versions_do_not_multiply_fixture_exposure(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "bankroll.db"))
    repository.initialize()
    service = BankrollService(repository)

    first = service.place_for_prediction(prediction("preliminary"), fixture(), context())
    second = service.place_for_prediction(prediction("confirmed"), fixture(), context())

    assert first is not None
    assert second is None
    assert len(repository.bets()) == 1
