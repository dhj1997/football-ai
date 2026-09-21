from app.national_competitions import (
    national_competition_from_api_id,
    normalize_national_competition,
)


def test_national_registry_covers_requested_mens_competitions() -> None:
    assert normalize_national_competition("世界杯") == "world_cup"
    assert normalize_national_competition("国际友谊赛") == "international_friendlies"
    assert normalize_national_competition("亚运男足", area="亚洲") == "asian_games_men"
    assert normalize_national_competition("亚洲杯") == "asian_cup"
    assert national_competition_from_api_id(532).key == "afc_u23_asian_cup"


def test_national_registry_rejects_womens_gold_cup_and_oceania() -> None:
    assert normalize_national_competition("女足世界杯") is None
    assert normalize_national_competition("Gold Cup") is None
    assert normalize_national_competition("OFC Nations Cup") is None
    assert normalize_national_competition("大洋洲杯") is None


def test_u23_is_limited_to_asia() -> None:
    assert normalize_national_competition("亚足联U23亚洲杯", area="亚洲") == "afc_u23_asian_cup"
    assert normalize_national_competition("U23亚洲杯预选赛", area="AFC") == "afc_u23_qualifiers"
    assert normalize_national_competition("U23 World Championship", area="世界") is None
    assert normalize_national_competition("U23 Africa Cup", area="非洲") is None
