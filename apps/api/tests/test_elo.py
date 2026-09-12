from app.elo import compute_elo, expected_goal_shift


def _fixture(home, away, hs, as_, kickoff="2026-01-01T00:00:00+00:00"):
    return {
        "status": "finished",
        "kickoff": kickoff,
        "home_team": {"name": home},
        "away_team": {"name": away},
        "score": {"home": hs, "away": as_},
    }


def test_compute_elo_rewards_wins_and_home_advantage():
    ratings = compute_elo([
        _fixture("甲", "乙", 2, 0, "2026-01-01T00:00:00+00:00"),
        _fixture("乙", "甲", 1, 0, "2026-02-01T00:00:00+00:00"),
    ])
    # 甲先客场实力被低估后赢球，乙主场赢回一场；两者都应有评分
    assert "甲" in ratings and "乙" in ratings
    # 经典 Elo 只看胜负：各赢一个主场后评分应接近（主场优势让主胜得分更少）
    assert abs(ratings["甲"] - ratings["乙"]) < 15
    # 未参赛球队不应出现
    assert "丙" not in ratings


def test_expected_goal_shift_direction_and_bounds():
    strong, weak = expected_goal_shift(1700.0, 1300.0)
    assert strong > 0 and weak < 0
    assert strong <= 0.35 and weak >= -0.35
    # 势均力敌时接近主场优势带来的轻微偏移
    even_h, even_a = expected_goal_shift(1500.0, 1500.0)
    assert 0 < even_h <= 0.1 and -0.1 <= even_a < 0
