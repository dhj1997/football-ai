from app.national_competitions import (
    national_competition_from_api_id,
    normalize_national_competition,
)
from app.team_names import to_chinese_team_name


def test_national_registry_covers_requested_mens_competitions() -> None:
    assert normalize_national_competition("世界杯") == "world_cup"
    assert normalize_national_competition("国际友谊赛") == "international_friendlies"
    assert normalize_national_competition("亚洲杯") == "asian_cup"


def test_national_registry_rejects_womens_gold_cup_and_oceania() -> None:
    assert normalize_national_competition("女足世界杯") is None
    assert normalize_national_competition("Gold Cup") is None
    assert normalize_national_competition("OFC Nations Cup") is None
    assert normalize_national_competition("大洋洲杯") is None


def test_u23_competitions_are_excluded_from_coverage() -> None:
    # U23 tournaments are out of product scope: never normalized, never synced.
    assert normalize_national_competition("亚足联U23亚洲杯", area="亚洲") is None
    assert normalize_national_competition("U23亚洲杯预选赛", area="AFC") is None
    assert normalize_national_competition("亚运男足", area="亚洲") is None
    assert national_competition_from_api_id(532) is None
    assert national_competition_from_api_id(952) is None
    assert national_competition_from_api_id(803) is None


def test_national_team_names_are_localized_before_public_mapping() -> None:
    assert to_chinese_team_name("China U23") == "中国U23"
    assert to_chinese_team_name("United Arab Emirates U23") == "阿联酋U23"
    assert to_chinese_team_name("New Caledonia") == "新喀里多尼亚"
