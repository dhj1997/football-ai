"""Player season statistics: ESPN ingestion and squad evidence merge."""

from datetime import UTC, datetime

import pytest

from app.player_stats import PlayerStatsService, sync_player_stats


class StubEspnProvider:
    configured = True

    def __init__(self, teams_by_league, players_by_team) -> None:
        self.teams_by_league = teams_by_league
        self.players_by_team = players_by_team
        self.team_calls: list[str] = []
        self.league_calls: list[str] = []

    async def teams(self, league_key: str) -> list[dict]:
        self.league_calls.append(league_key)
        return self.teams_by_league.get(league_key, [])

    async def team_players(self, league_key: str, team_id: str) -> list[dict]:
        self.team_calls.append(str(team_id))
        return self.players_by_team.get(str(team_id), [])


class StubRepository:
    def __init__(self, existing_rows: list[dict] | None = None, league_teams=None) -> None:
        self.rows: list[dict] = list(existing_rows or [])
        self.league_teams_cache = league_teams

    def league_teams(self, league: str, season: str) -> list[dict] | None:
        return self.league_teams_cache

    def save_league_teams(self, league: str, season: str, teams: list) -> None:
        self.league_teams_cache = teams

    def player_stats_synced_at(self, team_id: str, season: str) -> str | None:
        rows = [row for row in self.rows if str(row.get("team_id")) == str(team_id)]
        return max((row["synced_at"] for row in rows), default=None)

    def save_player_stats(self, rows: list[dict]) -> int:
        self.rows.extend(rows)
        return len(rows)

    def player_stats(self, player_ids: list[str], season: str) -> list[dict]:
        wanted = {str(pid) for pid in player_ids}
        return [row for row in self.rows if str(row.get("player_id")) in wanted and str(row.get("season")) == season]


def _stats_row(player_id: str, team_id: str, season: str = "2026", synced_at: str = "2026-09-19T00:00:00+00:00") -> dict:
    return {
        "id": f"pstats:espn:{player_id}:{season}",
        "league": "epl",
        "season": season,
        "team_id": team_id,
        "player_id": player_id,
        "synced_at": synced_at,
        "source": "espn",
        "statistics": {"appearances": 4, "starts": 4, "minutes": 360, "goals": 2, "assists": 1, "saves": 0},
    }


@pytest.mark.asyncio
async def test_sync_fetches_stale_teams_and_caches_league_teams() -> None:
    repository = StubRepository(
        league_teams=[{"id": "349", "name": "AFC Bournemouth"}, {"id": "359", "name": "Everton"}]
    )
    # 球队 349 当天内同步过：新鲜，跳过
    repository.rows.append({**_stats_row("111", "349")})
    provider = StubEspnProvider(
        teams_by_league={},
        players_by_team={
            "359": [
                {"provider_player_id": "222", "name": "David Raya", "position": "Goalkeeper", "statistics": {"appearances": 4, "saves": 7}},
                {"provider_player_id": "223", "name": "Skipper", "position": "Midfielder", "statistics": {}},
            ]
        },
    )

    result = await sync_player_stats(
        repository,
        provider,
        leagues=("epl",),
        limit=5,
        request_interval_seconds=0,
        now=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
    )

    assert result["teams_fetched"] == 1
    assert result["skipped_fresh"] == 1
    assert result["players_saved"] == 2
    assert provider.team_calls == ["359"]
    saved = {row["player_id"]: row for row in repository.rows if row.get("player_id", "").startswith("2")}
    assert saved["222"]["id"] == "pstats:espn:222:2026"
    assert saved["222"]["statistics"]["saves"] == 7


@pytest.mark.asyncio
async def test_sync_fetches_league_team_list_once() -> None:
    repository = StubRepository(league_teams=None)
    provider = StubEspnProvider(
        teams_by_league={"epl": [{"id": "349", "name": "AFC Bournemouth"}]},
        players_by_team={"349": [{"provider_player_id": "222", "name": "David Raya", "statistics": {"appearances": 4}}]},
    )

    await sync_player_stats(repository, provider, leagues=("epl",), limit=1, request_interval_seconds=0)
    assert provider.league_calls == ["epl"]
    # 第二次运行复用缓存的球队列表，不再请求联赛端点
    provider.team_calls.clear()
    await sync_player_stats(repository, provider, leagues=("epl",), limit=1, request_interval_seconds=0)
    assert provider.league_calls == ["epl"]


@pytest.mark.asyncio
async def test_enrich_attaches_statistics_by_provider_id() -> None:
    repository = StubRepository(
        [
            _stats_row("111", "349"),
            _stats_row("333", "990", season="2025"),
        ]
    )
    service = PlayerStatsService(repository)
    context = {
        # ESPN 源 squad：provider_player_id 与快照同 id 空间
        "squads": {
            "home": [
                {"provider_player_id": "111", "original_name": "David Raya"},
                {"provider_player_id": "999", "original_name": "Unknown Guy"},
            ],
            "away": [{"id": "333", "original_name": "Old Season Player"}],
        }
    }

    report = await service.enrich(context, "epl", "2026")

    assert report["players_attached"] == 1
    assert report["source"] == "espn"
    home = context["squads"]["home"][0]
    assert home["statistics"]["appearances"] == 4
    assert home["statistics_source"] == "espn"
    assert home["statistics_season"] == "2026"
    assert home["statistics_snapshot_id"] == "pstats:espn:111:2026"
    assert home["statistics_synced_at"] == "2026-09-19T00:00:00+00:00"
    # 2025 赛季快照不得串赛季；未匹配的行保持原样
    assert "statistics" not in context["squads"]["away"][0]
    assert "statistics" not in context["squads"]["home"][1]
