from datetime import UTC, datetime

from app.bankroll import BankrollService
from app.database import PredictionRepository


def fixture() -> dict:
    return {
        "id": "fixture-1",
        "fixture_date": "2099-08-27",
        "kickoff": "2099-08-27T12:00:00+00:00",
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
        "decision": {
            "status": "bet",
            "market": "1x2",
            "selection": "home",
            "model_confidence": 0.7,
            "stake_fraction": 0.02,
            "reason": "确定性赔率优势达到执行标准",
            "reason_codes": [],
        },
    }


def context() -> dict:
    return {
        "odds": {
            "home": 2.1,
            "draw": 3.2,
            "away": 3.6,
            "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        }
    }


def league_fixture(fixture_id: str, kickoff: str, status: str = "scheduled") -> dict:
    return {
        **fixture(),
        "id": fixture_id,
        "provider_id": fixture_id,
        "fixture_date": "2099-08-27",
        "kickoff": kickoff,
        "status": status,
        "evidence": context(),
    }


def saved_prediction(prediction_id: str, fixture_id: str, edge: float, created_at: str) -> dict:
    item = prediction(prediction_id)
    item.update(
        {
            "fixture_id": fixture_id,
            "created_at": created_at,
            "phase": "preliminary",
            "model_key": "deepseek",
            "competition_id": "legacy",
        }
    )
    item["probabilities"]["home"] = (1 + edge) / 2
    item["decision"].update(
        {
            "price": 2.0,
            "expected_edge": edge,
            "stake_fraction": min(0.25, 0.10 + max(edge - 0.03, 0)),
        }
    )
    return item


def test_initial_balance_and_duplicate_bet_protection(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "bankroll.db"))
    repository.initialize()
    service = BankrollService(repository)

    first = service.place_for_prediction(prediction(), fixture(), context())
    duplicate = service.place_for_prediction(prediction(), fixture(), context())

    assert first is not None
    assert first["stake"] == 250.0
    assert duplicate["id"] == first["id"]
    assert repository.current_balance() == 750.0
    assert len(repository.bankroll_transactions()) == 2
    assert service.summary()["equity"] == 1000.0
    assert service.summary()["net_profit"] == 0.0
    assert service.summary()["equity_curve"][0]["balance"] == 1000.0


def test_legacy_two_percent_bet_is_refunded_and_resized(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "legacy-size.db"))
    repository.initialize()
    repository.place_bet(
        {
            "id": "legacy-bet",
            "prediction_id": "prediction-1",
            "fixture_id": "fixture-1",
            "fixture_date": fixture()["fixture_date"],
            "placed_at": "2026-08-27T01:00:00+00:00",
            "market": "1x2",
            "selection": "home",
            "handicap_line": None,
            "odds": 2.1,
            "stake": 20.0,
            "league_key": "epl",
            "kickoff": fixture()["kickoff"],
            "home_team": "Home",
            "away_team": "Away",
            "model_version": prediction()["model_version"],
            "model_key": "deepseek",
            "competition_id": "legacy",
            "is_simulated": True,
        }
    )

    resized = BankrollService(repository).place_for_prediction(prediction(), fixture(), context())

    assert resized is not None and resized["id"] != "legacy-bet"
    assert resized["stake"] == 250.0
    assert len(repository.bets()) == 1
    assert repository.current_balance() == 750.0


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
        next_fixture = {**fixture(), "id": f"fixture-{index}", "league_key": f"league-{index}"}
        service.place_for_prediction(prediction(f"prediction-{index}"), next_fixture, context())

    exposure = sum(item["stake"] for item in repository.bets(status="placed"))
    assert exposure == 500.0
    assert all(item["stake"] >= item["balance_before"] * 0.10 for item in repository.bets())
    assert all(item["stake"] <= item["balance_before"] * 0.25 for item in repository.bets())


def test_multiple_prediction_versions_do_not_multiply_fixture_exposure(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "bankroll.db"))
    repository.initialize()
    service = BankrollService(repository)

    first = service.place_for_prediction(prediction("preliminary"), fixture(), context())
    second = service.place_for_prediction(prediction("confirmed"), fixture(), context())

    assert first is not None
    assert second is not None
    assert second["prediction_id"] == "confirmed"
    assert len(repository.bets()) == 1
    assert repository.current_balance() == 750.0


def test_new_ineligible_prediction_discards_the_old_open_fixture_bet(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "replace-with-no-bet.db"))
    repository.initialize()
    service = BankrollService(repository)
    first = service.place_for_prediction(prediction("preliminary"), fixture(), context())
    no_bet = prediction("current-no-bet")
    no_bet["data_completeness"] = 0.69
    no_bet["decision"].update({"status": "no_bet", "market": "no_bet", "selection": "none", "stake_fraction": 0})

    result = service.place_for_prediction(no_bet, fixture(), context())

    assert first is not None
    assert result is None
    assert repository.bets() == []
    assert repository.current_balance() == 1000.0


def test_low_confidence_warning_does_not_duplicate_the_market_gate(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "low-confidence.db"))
    repository.initialize()
    service = BankrollService(repository)
    item = prediction()
    item["decision"]["model_confidence"] = 0.55
    item["decision"]["warning_codes"] = ["low_confidence"]

    placed = service.place_for_prediction(item, fixture(), context())

    assert placed is not None
    assert placed["stake"] == 250.0


def test_higher_edge_fixture_replaces_the_open_league_day_bet(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "league-day.db"))
    repository.initialize()
    service = BankrollService(repository)
    first_fixture = league_fixture("league-1", "2099-08-27T12:00:00+00:00")
    second_fixture = league_fixture("league-2", "2099-08-27T14:00:00+00:00")
    repository.replace_fixtures("2099-08-27", "2099-08-27", [first_fixture, second_fixture], "2099-08-27T00:00:00+00:00")
    first_prediction = saved_prediction("league-p1", "league-1", 0.08, "2099-08-27T01:00:00+00:00")
    repository.save(first_prediction)

    first_bet = service.place_for_prediction(
        first_prediction,
        first_fixture,
        {"odds": {**context()["odds"], "home": 2.0}},
    )
    second_prediction = saved_prediction("league-p2", "league-2", 0.20, "2099-08-27T02:00:00+00:00")
    repository.save(second_prediction)
    second_bet = service.place_for_prediction(
        second_prediction,
        second_fixture,
        {"odds": {**context()["odds"], "home": 2.0}},
    )

    assert first_bet is not None
    assert second_bet is not None and second_bet["prediction_id"] == "league-p2"
    assert repository.bet_for_prediction("league-p1") is None
    assert len(repository.bets()) == 1
    assert repository.current_balance() == 750.0
    assert service.execution_for_prediction(first_prediction, first_fixture)["reason_codes"] == ["league_daily_limit"]


def test_started_league_day_bet_is_not_replaced(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "started-league-day.db"))
    repository.initialize()
    service = BankrollService(repository)
    first_fixture = league_fixture("started-1", "2099-08-27T12:00:00+00:00")
    second_fixture = league_fixture("started-2", "2099-08-27T14:00:00+00:00")
    repository.replace_fixtures("2099-08-27", "2099-08-27", [first_fixture, second_fixture], "2099-08-27T00:00:00+00:00")
    first_prediction = saved_prediction("started-p1", "started-1", 0.08, "2099-08-27T01:00:00+00:00")
    repository.save(first_prediction)
    first_bet = service.place_for_prediction(
        first_prediction,
        first_fixture,
        {"odds": {**context()["odds"], "home": 2.0}},
    )
    repository.replace_fixtures(
        "2099-08-27",
        "2099-08-27",
        [{**first_fixture, "status": "live"}, second_fixture],
        "2099-08-27T02:00:00+00:00",
    )
    second_prediction = saved_prediction("started-p2", "started-2", 0.20, "2099-08-27T03:00:00+00:00")
    repository.save(second_prediction)

    selected = service.place_for_prediction(
        second_prediction,
        second_fixture,
        {"odds": {**context()["odds"], "home": 2.0}},
    )

    assert first_bet is not None
    assert selected is not None and selected["prediction_id"] == "started-p1"
    assert repository.bet_for_prediction("started-p2") is None
    assert len(repository.bets()) == 1
