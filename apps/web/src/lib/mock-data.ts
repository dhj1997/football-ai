import { to_chinese_player_name } from "./player-names";
import type {
  BacktestResponse,
  BankrollSummary,
  DateFilter,
  DecisionAudit,
  EvidenceContext,
  Fixture,
  FixtureDetail,
  FixtureLeagueFilter,
  LeagueSnapshot,
  ModelEvaluationResponse,
  Prediction,
  PredictionMetrics,
  RuntimeConfigResponse,
  SimulatedBet,
  StandingsResponse,
  StrategyPerformance,
  TeamDetailResponse,
  TeamSnapshot,
} from "./types";

const LEAGUE_MAP: Record<string, { id: number; name: string; country: string; mark: string }> = {
  epl: { id: 39, name: "英超", country: "英格兰", mark: "PL" },
  laliga: { id: 140, name: "西甲", country: "西班牙", mark: "LL" },
  csl: { id: 169, name: "中超", country: "中国", mark: "CSL" },
};

function getIsoDate(offsetDays = 0, hour = 20, minute = 0): string {
  const now = new Date();
  now.setDate(now.getDate() + offsetDays);
  now.setHours(hour, minute, 0, 0);
  return now.toISOString();
}

function formatDateStr(offsetDays = 0): string {
  const now = new Date();
  now.setDate(now.getDate() + offsetDays);
  return now.toISOString().slice(0, 10);
}

const RAW_FIXTURES: Fixture[] = [
  {
    id: "fix-epl-01",
    provider_id: 1001,
    fixture_date: formatDateStr(0),
    league_key: "epl",
    league: LEAGUE_MAP.epl,
    kickoff: getIsoDate(0, 20, 0),
    status: "scheduled",
    home_team: { name: "阿森纳", code: "ARS" },
    away_team: { name: "曼彻斯特城", code: "MCI" },
    score: null,
    venue: "酋长球场",
    lineup_confirmed: true,
    is_demo: true,
    has_prediction: true,
    evidence_summary: { ready_count: 6, total_count: 6, missing: [], updated_at: getIsoDate(0, 18, 30) },
    odds_summary: { home: 2.35, draw: 3.40, away: 2.85, updated_at: getIsoDate(0, 19, 0) },
  },
  {
    id: "fix-laliga-01",
    provider_id: 1002,
    fixture_date: formatDateStr(0),
    league_key: "laliga",
    league: LEAGUE_MAP.laliga,
    kickoff: getIsoDate(0, 22, 0),
    status: "scheduled",
    home_team: { name: "皇家马德里", code: "RMA" },
    away_team: { name: "皇家社会", code: "RSO" },
    score: null,
    venue: "伯纳乌球场",
    lineup_confirmed: true,
    is_demo: true,
    has_prediction: true,
    evidence_summary: { ready_count: 6, total_count: 6, missing: [], updated_at: getIsoDate(0, 19, 15) },
    odds_summary: { home: 1.48, draw: 4.50, away: 6.20, updated_at: getIsoDate(0, 19, 30) },
  },
  {
    id: "fix-csl-01",
    provider_id: 1003,
    fixture_date: formatDateStr(0),
    league_key: "csl",
    league: LEAGUE_MAP.csl,
    kickoff: getIsoDate(0, 19, 35),
    status: "scheduled",
    home_team: { name: "上海海港", code: "SHP" },
    away_team: { name: "北京国安", code: "BJG" },
    score: null,
    venue: "上汽浦东足球场",
    lineup_confirmed: false,
    is_demo: true,
    has_prediction: true,
    evidence_summary: { ready_count: 5, total_count: 6, missing: ["lineup"], updated_at: getIsoDate(0, 17, 0) },
    odds_summary: { home: 1.75, draw: 3.80, away: 4.10, updated_at: getIsoDate(0, 18, 0) },
  },
  {
    id: "fix-epl-02",
    provider_id: 1004,
    fixture_date: formatDateStr(1),
    league_key: "epl",
    league: LEAGUE_MAP.epl,
    kickoff: getIsoDate(1, 21, 30),
    status: "scheduled",
    home_team: { name: "利物浦", code: "LIV" },
    away_team: { name: "切尔西", code: "CHE" },
    score: null,
    venue: "安菲尔德球场",
    lineup_confirmed: false,
    is_demo: true,
    has_prediction: true,
    evidence_summary: { ready_count: 4, total_count: 6, missing: ["lineup", "odds"], updated_at: getIsoDate(0, 12, 0) },
    odds_summary: { home: 1.95, draw: 3.60, away: 3.50, updated_at: getIsoDate(0, 12, 0) },
  },
  {
    id: "fix-laliga-02",
    provider_id: 1005,
    fixture_date: formatDateStr(1),
    league_key: "laliga",
    league: LEAGUE_MAP.laliga,
    kickoff: getIsoDate(1, 23, 0),
    status: "scheduled",
    home_team: { name: "巴塞罗那", code: "FCB" },
    away_team: { name: "马德里竞技", code: "ATM" },
    score: null,
    venue: "蒙特惠奇奥林匹克体育场",
    lineup_confirmed: false,
    is_demo: true,
    has_prediction: true,
    evidence_summary: { ready_count: 4, total_count: 6, missing: ["lineup"], updated_at: getIsoDate(0, 14, 0) },
    odds_summary: { home: 1.85, draw: 3.75, away: 3.90, updated_at: getIsoDate(0, 14, 0) },
  },
  {
    id: "fix-epl-03",
    provider_id: 1006,
    fixture_date: formatDateStr(-1),
    league_key: "epl",
    league: LEAGUE_MAP.epl,
    kickoff: getIsoDate(-1, 22, 0),
    status: "finished",
    home_team: { name: "托特纳姆热刺", code: "TOT" },
    away_team: { name: "纽卡斯尔联", code: "NEW" },
    score: { home: 2, away: 1 },
    venue: "托特纳姆热刺球场",
    lineup_confirmed: true,
    is_demo: true,
    has_prediction: true,
    evidence_summary: { ready_count: 6, total_count: 6, missing: [], updated_at: getIsoDate(-1, 21, 0) },
    odds_summary: { home: 2.10, draw: 3.50, away: 3.20, updated_at: getIsoDate(-1, 21, 0) },
  },
  {
    id: "fix-csl-02",
    provider_id: 1007,
    fixture_date: formatDateStr(-1),
    league_key: "csl",
    league: LEAGUE_MAP.csl,
    kickoff: getIsoDate(-1, 19, 35),
    status: "finished",
    home_team: { name: "山东泰山", code: "SDT" },
    away_team: { name: "成都蓉城", code: "CDR" },
    score: { home: 1, away: 1 },
    venue: "济南奥体中心体育场",
    lineup_confirmed: true,
    is_demo: true,
    has_prediction: true,
    evidence_summary: { ready_count: 6, total_count: 6, missing: [], updated_at: getIsoDate(-1, 18, 30) },
    odds_summary: { home: 2.20, draw: 3.30, away: 3.00, updated_at: getIsoDate(-1, 18, 30) },
  },
];

export function getMockFixtures(date: DateFilter, league: FixtureLeagueFilter): Fixture[] {
  return RAW_FIXTURES.filter((f) => {
    if (league !== "all" && f.league_key !== league) return false;
    const todayStr = formatDateStr(0);
    const tomStr = formatDateStr(1);
    const yestStr = formatDateStr(-1);

    if (date === "today") return f.fixture_date === todayStr;
    if (date === "tomorrow") return f.fixture_date === tomStr;
    if (date === "yesterday") return f.fixture_date === yestStr;
    if (date === "upcoming") return (f.fixture_date ?? "") >= todayStr;
    if (date === "history") return (f.fixture_date ?? "") < todayStr;
    return true;
  });
}

function createSamplePrediction(fixture: Fixture, modelKey: "deepseek" | "chatgpt"): Prediction {
  const isDeepSeek = modelKey === "deepseek";
  return {
    id: `pred-${modelKey}-${fixture.id}`,
    fixture_id: fixture.id,
    created_at: new Date().toISOString(),
    phase: fixture.lineup_confirmed ? "confirmed_lineup" : "preliminary",
    model_version: isDeepSeek ? "deepseek-v3.2" : "gpt-5.6-sol",
    model_key: modelKey,
    competition_id: fixture.league_key,
    probabilities: isDeepSeek
      ? { home: 0.48, draw: 0.28, away: 0.24 }
      : { home: 0.45, draw: 0.30, away: 0.25 },
    expected_goals: isDeepSeek
      ? { home: 1.62, away: 1.15 }
      : { home: 1.54, away: 1.20 },
    top_scores: [
      { score: "1-0", probability: 0.13 },
      { score: "2-1", probability: 0.11 },
      { score: "1-1", probability: 0.10 },
      { score: "2-0", probability: 0.09 },
      { score: "0-1", probability: 0.08 },
    ],
    asian_handicap: {
      line: -0.5,
      home_settlement: {
        full_win: 0.48,
        half_win: 0,
        push: 0,
        half_loss: 0,
        full_loss: 0.52,
      },
    },
    confidence: "高可信度",
    evidence: {
      recent_form_at: new Date().toISOString(),
      availability_at: new Date().toISOString(),
      lineup_at: fixture.lineup_confirmed ? new Date().toISOString() : null,
      odds_at: new Date().toISOString(),
      is_demo: true,
    },
  };
}

export function getMockFixtureDetail(id: string): FixtureDetail {
  const fixture = RAW_FIXTURES.find((f) => f.id === id) ?? RAW_FIXTURES[0];
  const nowIso = new Date().toISOString();

  const dsPred = createSamplePrediction(fixture, "deepseek");
  const gptPred = createSamplePrediction(fixture, "chatgpt");

  const betSample: SimulatedBet = {
    id: `bet-${fixture.id}`,
    prediction_id: dsPred.id,
    fixture_id: fixture.id,
    fixture_date: fixture.fixture_date ?? formatDateStr(0),
    placed_at: nowIso,
    market: "1x2",
    selection: "home",
    handicap_line: null,
    odds: 2.35,
    stake: 150,
    status: "placed",
    league_key: fixture.league_key as "epl",
    kickoff: fixture.kickoff,
    home_team: fixture.home_team.name,
    away_team: fixture.away_team.name,
    model_version: dsPred.model_version,
    model_key: "deepseek",
    competition_id: fixture.league_key,
    reason: "模型优势率超过阈值",
    is_simulated: true,
    balance_before: 1000,
    balance_after_placement: 850,
    settled_at: null,
    settlement_result: null,
    return_amount: null,
    net_profit: null,
    balance_after_settlement: null,
  };

  const context: EvidenceContext = {
    recent_form: {
      home: [
        { date: "2026-09-12", home: fixture.home_team.name, away: "西汉姆联", score: "3-0", result: "W" },
        { date: "2026-09-05", home: "布莱顿", away: fixture.home_team.name, score: "1-2", result: "W" },
        { date: "2026-08-29", home: fixture.home_team.name, away: "埃弗顿", score: "1-1", result: "D" },
      ],
      away: [
        { date: "2026-09-13", home: "富勒姆", away: fixture.away_team.name, score: "0-2", result: "W" },
        { date: "2026-09-06", home: fixture.away_team.name, away: "水晶宫", score: "1-1", result: "D" },
        { date: "2026-08-30", home: "狼队", away: fixture.away_team.name, score: "1-3", result: "W" },
      ],
      home_points_per_game: 2.33,
      away_points_per_game: 2.0,
      updated_at: nowIso,
    },
    head_to_head: [
      { date: "2026-03-31", home: fixture.home_team.name, away: fixture.away_team.name, score: "0-0" },
      { date: "2025-10-08", home: fixture.away_team.name, away: fixture.home_team.name, score: "1-0" },
      { date: "2025-04-26", home: fixture.away_team.name, away: fixture.home_team.name, score: "4-1" },
    ],
    availability: {
      home_missing: 1,
      away_missing: 2,
      notes: ["主队主力右边锋肌肉轻度拉伤", "客队中场大将停赛一轮"],
      players: [
        {
          team: "home",
          name: to_chinese_player_name("Bukayo Saka"),
          position: "前锋",
          reason: "肌肉疲劳，出场存疑",
        },
        {
          team: "away",
          name: to_chinese_player_name("Rodri"),
          position: "中场",
          reason: "累积黄牌停赛",
        },
      ],
      updated_at: nowIso,
    },
    lineup: {
      confirmed: fixture.lineup_confirmed,
      home_strength: 0.94,
      away_strength: 0.91,
      home_formation: "4-3-3",
      away_formation: "4-2-3-1",
      home_players: [
        { name: to_chinese_player_name("David Raya"), number: 22, position: "门将", starter: true },
        { name: to_chinese_player_name("William Saliba"), number: 2, position: "后卫", starter: true },
        { name: to_chinese_player_name("Gabriel Magalhães"), number: 6, position: "后卫", starter: true },
        { name: to_chinese_player_name("Declan Rice"), number: 41, position: "中场", starter: true },
        { name: to_chinese_player_name("Martin Ødegaard"), number: 8, position: "中场", starter: true },
        { name: to_chinese_player_name("Kai Havertz"), number: 29, position: "前锋", starter: true },
      ],
      away_players: [
        { name: to_chinese_player_name("Ederson"), number: 31, position: "门将", starter: true },
        { name: to_chinese_player_name("Rúben Dias"), number: 3, position: "后卫", starter: true },
        { name: to_chinese_player_name("Josko Gvardiol"), number: 24, position: "后卫", starter: true },
        { name: to_chinese_player_name("Kevin De Bruyne"), number: 17, position: "中场", starter: true },
        { name: to_chinese_player_name("Phil Foden"), number: 47, position: "中场", starter: true },
        { name: to_chinese_player_name("Erling Haaland"), number: 9, position: "前锋", starter: true },
      ],
      updated_at: nowIso,
    },
    teams: {
      home: {
        name: fixture.home_team.name,
        logo: "",
        founded: 1886,
        venue: fixture.venue,
        capacity: 60704,
      },
      away: {
        name: fixture.away_team.name,
        logo: "",
        founded: 1894,
        venue: "阿提哈德球场",
        capacity: 53400,
      },
    },
    squads: {
      home: [
        { id: 1, name: to_chinese_player_name("Declan Rice"), number: 41, position: "中场", age: 26, nationality: "英格兰", photo: null, market_value: 120000000, market_value_currency: "EUR", market_value_source: "Demo" },
        { id: 2, name: to_chinese_player_name("Martin Ødegaard"), number: 8, position: "中场", age: 26, nationality: "挪威", photo: null, market_value: 110000000, market_value_currency: "EUR", market_value_source: "Demo" },
      ],
      away: [
        { id: 3, name: to_chinese_player_name("Erling Haaland"), number: 9, position: "前锋", age: 25, nationality: "挪威", photo: null, market_value: 200000000, market_value_currency: "EUR", market_value_source: "Demo" },
        { id: 4, name: to_chinese_player_name("Phil Foden"), number: 47, position: "中场", age: 25, nationality: "英格兰", photo: null, market_value: 150000000, market_value_currency: "EUR", market_value_source: "Demo" },
      ],
    },
    odds: {
      bookmaker: "Pinnacle",
      home: fixture.odds_summary?.home ?? 2.10,
      draw: fixture.odds_summary?.draw ?? 3.40,
      away: fixture.odds_summary?.away ?? 3.10,
      asian_handicap: -0.5,
      asian_handicap_home_odd: 1.95,
      asian_handicap_away_odd: 1.88,
      updated_at: nowIso,
      is_demo: true,
    },
    source: "内置离线演练引擎",
    synced_at: nowIso,
  };

  return {
    fixture,
    context,
    prediction: dsPred,
    predictions: {
      deepseek: dsPred,
      chatgpt: gptPred,
    },
    bet: betSample,
    bets: {
      deepseek: betSample,
      chatgpt: null,
    },
    capabilities: {
      evidence_sync: true,
      dongqiudi_sync: true,
      dongqiudi_last_synced_at: nowIso,
      deepseek: true,
      chatgpt: true,
    },
  };
}

export function getMockStandings(): StandingsResponse {
  const leagues: LeagueSnapshot[] = [
    {
      league_key: "epl",
      league_name: "英超",
      season: { year: 2026, name: "2025-2026", start_date: "2025-08-15", end_date: "2026-05-24" },
      team_count: 20,
      source: "内置数据",
      updated_at: new Date().toISOString(),
      standings: [
        { rank: 1, team: { name: "利物浦", code: "LIV" }, played: 28, wins: 20, draws: 5, losses: 3, goals_for: 62, goals_against: 24, goal_difference: 38, points: 65, note: "欧冠区" },
        { rank: 2, team: { name: "阿森纳", code: "ARS" }, played: 28, wins: 19, draws: 6, losses: 3, goals_for: 58, goals_against: 22, goal_difference: 36, points: 63, note: "欧冠区" },
        { rank: 3, team: { name: "曼彻斯特城", code: "MCI" }, played: 28, wins: 18, draws: 6, losses: 4, goals_for: 65, goals_against: 28, goal_difference: 37, points: 60, note: "欧冠区" },
        { rank: 4, team: { name: "切尔西", code: "CHE" }, played: 28, wins: 15, draws: 6, losses: 7, goals_for: 51, goals_against: 35, goal_difference: 16, points: 51, note: "欧冠区" },
        { rank: 5, team: { name: "托特纳姆热刺", code: "TOT" }, played: 28, wins: 14, draws: 5, losses: 9, goals_for: 52, goals_against: 40, goal_difference: 12, points: 47, note: "欧联区" },
        { rank: 6, team: { name: "纽卡斯尔联", code: "NEW" }, played: 28, wins: 13, draws: 7, losses: 8, goals_for: 48, goals_against: 38, goal_difference: 10, points: 46, note: null },
      ],
    },
    {
      league_key: "laliga",
      league_name: "西甲",
      season: { year: 2026, name: "2025-2026", start_date: "2025-08-15", end_date: "2026-05-24" },
      team_count: 20,
      source: "内置数据",
      updated_at: new Date().toISOString(),
      standings: [
        { rank: 1, team: { name: "皇家马德里", code: "RMA" }, played: 28, wins: 21, draws: 4, losses: 3, goals_for: 64, goals_against: 21, goal_difference: 43, points: 67, note: "欧冠区" },
        { rank: 2, team: { name: "巴塞罗那", code: "FCB" }, played: 28, wins: 20, draws: 4, losses: 4, goals_for: 71, goals_against: 28, goal_difference: 43, points: 64, note: "欧冠区" },
        { rank: 3, team: { name: "马德里竞技", code: "ATM" }, played: 28, wins: 17, draws: 6, losses: 5, goals_for: 46, goals_against: 20, goal_difference: 26, points: 57, note: "欧冠区" },
        { rank: 4, team: { name: "毕尔巴鄂竞技", code: "ATH" }, played: 28, wins: 14, draws: 8, losses: 6, goals_for: 43, goals_against: 26, goal_difference: 17, points: 50, note: "欧冠区" },
        { rank: 5, team: { name: "比利亚雷亚尔", code: "VIL" }, played: 28, wins: 13, draws: 7, losses: 8, goals_for: 48, goals_against: 39, goal_difference: 9, points: 46, note: "欧联区" },
        { rank: 6, team: { name: "皇家社会", code: "RSO" }, played: 28, wins: 12, draws: 6, losses: 10, goals_for: 35, goals_against: 30, goal_difference: 5, points: 42, note: null },
      ],
    },
    {
      league_key: "csl",
      league_name: "中超",
      season: { year: 2026, name: "2026", start_date: "2026-03-01", end_date: "2026-11-05" },
      team_count: 16,
      source: "内置数据",
      updated_at: new Date().toISOString(),
      standings: [
        { rank: 1, team: { name: "上海海港", code: "SHP" }, played: 22, wins: 17, draws: 3, losses: 2, goals_for: 59, goals_against: 18, goal_difference: 41, points: 54, note: "亚冠精英联赛" },
        { rank: 2, team: { name: "上海申花", code: "SHS" }, played: 22, wins: 16, draws: 4, losses: 2, goals_for: 47, goals_against: 14, goal_difference: 33, points: 52, note: "亚冠精英附加赛" },
        { rank: 3, team: { name: "成都蓉城", code: "CDR" }, played: 22, wins: 14, draws: 4, losses: 4, goals_for: 45, goals_against: 22, goal_difference: 23, points: 46, note: "亚冠二级联赛" },
        { rank: 4, team: { name: "北京国安", code: "BJG" }, played: 22, wins: 12, draws: 5, losses: 5, goals_for: 42, goals_against: 27, goal_difference: 15, points: 41, note: null },
        { rank: 5, team: { name: "山东泰山", code: "SDT" }, played: 22, wins: 10, draws: 6, losses: 6, goals_for: 38, goals_against: 31, goal_difference: 7, points: 36, note: null },
      ],
    },
  ];

  return {
    items: leagues,
    sync_status: "fresh",
    source: "内置数据",
    last_synced_at: new Date().toISOString(),
  };
}

export function getMockTeamDetail(leagueKey: string, teamId: string): TeamDetailResponse {
  const decoded = decodeURIComponent(teamId);
  const nowIso = new Date().toISOString();

  const snapshot: TeamSnapshot = {
    league_key: (leagueKey as "epl") || "epl",
    team_id: teamId,
    season: { year: 2026, name: "2025-2026" },
    team: {
      name: decoded,
      abbreviation: decoded.slice(0, 3).toUpperCase(),
      logo: null,
      color: "#DA020E",
      record_summary: "19胜 6平 3负",
      standing_summary: "联赛第 2 名",
    },
    coach: { name: "米克尔·阿尔特塔", nationality: "西班牙" },
    roster_count: 4,
    roster: [
      {
        id: "p-41",
        name: to_chinese_player_name("Declan Rice"),
        number: 41,
        position: "中场",
        position_code: "MF",
        age: 26,
        date_of_birth: "1999-01-14",
        nationality: "英格兰",
        photo: null,
        status: "健康",
        injuries: [],
        statistics: { appearances: 26, substitute_appearances: 0, goals: 5, assists: 7, yellow_cards: 2, red_cards: 0, saves: 0, goals_conceded: 0 },
      },
      {
        id: "p-8",
        name: to_chinese_player_name("Martin Ødegaard"),
        number: 8,
        position: "中场",
        position_code: "MF",
        age: 26,
        date_of_birth: "1998-12-17",
        nationality: "挪威",
        photo: null,
        status: "健康",
        injuries: [],
        statistics: { appearances: 24, substitute_appearances: 1, goals: 7, assists: 9, yellow_cards: 1, red_cards: 0, saves: 0, goals_conceded: 0 },
      },
      {
        id: "p-29",
        name: to_chinese_player_name("Kai Havertz"),
        number: 29,
        position: "前锋",
        position_code: "FW",
        age: 26,
        date_of_birth: "1999-06-11",
        nationality: "德国",
        photo: null,
        status: "健康",
        injuries: [],
        statistics: { appearances: 27, substitute_appearances: 0, goals: 13, assists: 4, yellow_cards: 3, red_cards: 0, saves: 0, goals_conceded: 0 },
      },
      {
        id: "p-7",
        name: to_chinese_player_name("Bukayo Saka"),
        number: 7,
        position: "前锋",
        position_code: "FW",
        age: 24,
        date_of_birth: "2001-09-05",
        nationality: "英格兰",
        photo: null,
        status: "轻伤存疑",
        injuries: [{ type: "肌肉疲劳", status: "恢复中", detail: "轻度肌腱拉伤", date: "2026-09-15" }],
        statistics: { appearances: 25, substitute_appearances: 0, goals: 12, assists: 11, yellow_cards: 2, red_cards: 0, saves: 0, goals_conceded: 0 },
      },
    ],
    matches: [
      {
        id: "m-1",
        date: "2026-09-12",
        status: "finished",
        status_text: "已结束",
        home: { id: "t-1", name: decoded, logo: null },
        away: { id: "t-2", name: "西汉姆联", logo: null },
        home_score: 3,
        away_score: 0,
        result: "W",
        team_is_home: true,
        venue: "主场",
      },
      {
        id: "m-2",
        date: "2026-09-05",
        status: "finished",
        status_text: "已结束",
        home: { id: "t-3", name: "布莱顿", logo: null },
        away: { id: "t-1", name: decoded, logo: null },
        home_score: 1,
        away_score: 2,
        result: "W",
        team_is_home: false,
        venue: "客场",
      },
    ],
    source: "内置数据",
    updated_at: nowIso,
  };

  return {
    item: snapshot,
    sync_status: "fresh",
  };
}

export function getMockBankroll(): BankrollSummary {
  return {
    initial_balance: 1000,
    balance: 1128.4,
    equity: 1128.4,
    net_profit: 128.4,
    total_staked: 850,
    settled_staked: 700,
    total_returns: 828.4,
    open_exposure: 150,
    roi: 0.1284,
    hit_rate: 0.583,
    bet_count: 8,
    settled_count: 7,
    open_count: 1,
    max_drawdown: 0.068,
    equity_curve: [
      { at: "2026-09-10", balance: 1000 },
      { at: "2026-09-12", balance: 1045 },
      { at: "2026-09-14", balance: 1090 },
      { at: "2026-09-18", balance: 1128.4 },
    ],
    is_simulated: true,
  };
}

export function getMockBets(): { items: SimulatedBet[]; count: number; is_simulated: true } {
  const items: SimulatedBet[] = [
    {
      id: "bet-001",
      prediction_id: "pred-001",
      fixture_id: "fix-epl-03",
      fixture_date: formatDateStr(-1),
      placed_at: getIsoDate(-1, 21, 15),
      market: "1x2",
      selection: "home",
      handicap_line: null,
      odds: 2.10,
      stake: 120,
      status: "settled",
      league_key: "epl",
      kickoff: getIsoDate(-1, 22, 0),
      home_team: "托特纳姆热刺",
      away_team: "纽卡斯尔联",
      model_version: "deepseek-v3.2",
      model_key: "deepseek",
      competition_id: "epl",
      reason: "胜平负模型优势突破门限",
      is_simulated: true,
      balance_before: 1000,
      balance_after_placement: 880,
      settled_at: getIsoDate(-1, 23, 55),
      settlement_result: "full_win",
      return_amount: 252.0,
      net_profit: 132.0,
      balance_after_settlement: 1132.0,
    },
    {
      id: "bet-002",
      prediction_id: "pred-002",
      fixture_id: "fix-csl-02",
      fixture_date: formatDateStr(-1),
      placed_at: getIsoDate(-1, 18, 45),
      market: "asian_handicap",
      selection: "away",
      handicap_line: 0.25,
      odds: 1.90,
      stake: 100,
      status: "settled",
      league_key: "csl",
      kickoff: getIsoDate(-1, 19, 35),
      home_team: "山东泰山",
      away_team: "成都蓉城",
      model_version: "gpt-5.6-sol",
      model_key: "chatgpt",
      competition_id: "csl",
      reason: "受让盘口期望收益明显",
      is_simulated: true,
      balance_before: 1132.0,
      balance_after_placement: 1032.0,
      settled_at: getIsoDate(-1, 21, 30),
      settlement_result: "half_win",
      return_amount: 145.0,
      net_profit: 45.0,
      balance_after_settlement: 1177.0,
    },
  ];
  return { items, count: items.length, is_simulated: true };
}

export function getMockDecisions(): { items: DecisionAudit[]; count: number; is_simulated: true } {
  const items: DecisionAudit[] = [
    {
      id: "audit-01",
      fixture_id: "fix-epl-01",
      fixture_date: formatDateStr(0),
      kickoff: getIsoDate(0, 20, 0),
      league_key: "epl",
      home_team: "阿森纳",
      away_team: "曼彻斯特城",
      created_at: new Date().toISOString(),
      model_key: "deepseek",
      model_version: "deepseek-v3.2",
      strategy_id: "strat-v3",
      strategy_version: "3.2.0",
      strategy_name: "主队价值策略",
      evidence_snapshot_id: "ev-01",
      decision_status: "bet",
      market: "1x2",
      selection: "home",
      considered_market: "1x2",
      considered_selection: "home",
      price: 2.35,
      expected_edge: 0.054,
      stake_fraction: 0.15,
      reason_codes: ["EDGE_POSITIVE", "SAMPLE_CONFIRMED"],
      reason: "胜平负期望持续超越盘口水位",
      execution_status: "bet",
      execution_reason: "满足下注门限",
      bet_id: "bet-001",
      model_recommendation_status: "bet",
    },
    {
      id: "audit-02",
      fixture_id: "fix-csl-01",
      fixture_date: formatDateStr(0),
      kickoff: getIsoDate(0, 19, 35),
      league_key: "csl",
      home_team: "上海海港",
      away_team: "北京国安",
      created_at: new Date().toISOString(),
      model_key: "chatgpt",
      model_version: "gpt-5.6-sol",
      strategy_id: "strat-v3",
      strategy_version: "3.2.0",
      strategy_name: "盘口风控策略",
      evidence_snapshot_id: "ev-02",
      decision_status: "no_bet",
      market: "asian_handicap",
      selection: "home",
      considered_market: "asian_handicap",
      considered_selection: "home",
      price: 1.75,
      expected_edge: 0.015,
      stake_fraction: 0,
      reason_codes: ["EDGE_BELOW_THRESHOLD"],
      reason: "首发名单未公布，优势在容差带内",
      execution_status: "no_bet",
      execution_reason: "低于风控阈值",
      bet_id: null,
      model_recommendation_status: "no_bet",
    },
  ];
  return { items, count: items.length, is_simulated: true };
}

export function getMockStrategyPerformance(): {
  items: StrategyPerformance[];
  count: number;
  ranking: string;
  is_simulated: true;
} {
  return {
    items: [
      {
        rank: 1,
        model_key: "deepseek",
        strategy_id: "deepseek-pinnacle",
        strategy_version: "1.0",
        strategy_name: "DeepSeek 价值发现",
        realized_pnl: 142.8,
        roi: 0.1428,
        prediction_samples: 64,
        market_comparison_samples: 64,
        average_brier: 0.185,
        average_log_loss: 0.542,
        brier_improvement: 0.018,
        clv_samples: 50,
        max_drawdown: 0.068,
        gate_status: "READY",
        gate_mode: "EXECUTABLE",
      },
      {
        rank: 2,
        model_key: "chatgpt",
        strategy_id: "chatgpt-ensemble",
        strategy_version: "1.0",
        strategy_name: "ChatGPT 稳健策略",
        realized_pnl: 114.0,
        roi: 0.1140,
        prediction_samples: 58,
        market_comparison_samples: 58,
        average_brier: 0.198,
        average_log_loss: 0.568,
        brier_improvement: 0.012,
        clv_samples: 45,
        max_drawdown: 0.082,
        gate_status: "READY",
        gate_mode: "EXECUTABLE",
      },
    ],
    count: 2,
    ranking: "DeepSeek 综合指标领跑",
    is_simulated: true,
  };
}

export function getMockBacktest(): BacktestResponse {
  const windowSample = {
    window_id: "w-2026-q1",
    test_start: "2026-01-01",
    test_end: "2026-03-31",
    train_samples: 320,
    eligible_samples: 120,
    forecast_metrics: {
      baseline: { samples: 120, brier: 0.188, log_loss: 0.542, rps: 0.171 },
      p3_ensemble: { samples: 120, brier: 0.182 },
    },
    betting_metrics: { bets: 48, roi: 0.134, pnl: 284.5 },
  };

  return {
    global: {
      status: "completed",
      windows: [windowSample],
      runs: 1,
      total_fixtures: 480,
      eligible_fixtures: 452,
      leakage_check: { passed: true },
    },
    EPL: {
      status: "completed",
      windows: [windowSample],
      runs: 1,
      total_fixtures: 180,
      eligible_fixtures: 175,
      leakage_check: { passed: true },
    },
    LAL: {
      status: "completed",
      windows: [windowSample],
      runs: 1,
      total_fixtures: 175,
      eligible_fixtures: 170,
      leakage_check: { passed: true },
    },
    CSL: {
      status: "completed",
      windows: [windowSample],
      runs: 1,
      total_fixtures: 97,
      eligible_fixtures: 92,
      leakage_check: { passed: true },
    },
  };
}

export function getMockMetrics(): PredictionMetrics {
  return {
    sample_size: 122,
    correct_count: 72,
    accuracy: 0.59,
    average_brier_score: 0.188,
    average_log_loss: 0.545,
    average_rps: 0.171,
    average_data_completeness: 0.96,
    market_comparison: {
      sample_size: 122,
      market_brier_score: 0.201,
      market_log_loss: 0.582,
      brier_improvement: 0.013,
      log_loss_improvement: 0.037,
    },
    asian_handicap_results: {
      full_win: 45,
      half_win: 12,
      push: 10,
      half_loss: 15,
      full_loss: 40,
    },
    filters: {
      league: null,
      date_from: null,
      date_to: null,
    },
    items: [],
  };
}


export function getMockModelEvaluation(): ModelEvaluationResponse {
  return {
    experiment_id: "exp-baseline-2026-09",
    status: "completed",
    reports: {
      epl: {
        league: "英超",
        sample_count: 180,
        confidence: "高",
        models: {
          deepseek: { status: "active", sample_count: 90, brier: 0.182, log_loss: 0.538, rps: 0.168, ece: 0.042, clv: 0.038, confidence: "高" },
          chatgpt: { status: "active", sample_count: 90, brier: 0.194, log_loss: 0.561, rps: 0.178, ece: 0.051, clv: 0.029, confidence: "高" },
        },
      },
      laliga: {
        league: "西甲",
        sample_count: 175,
        confidence: "高",
        models: {
          deepseek: { status: "active", sample_count: 88, brier: 0.187, log_loss: 0.545, rps: 0.172, ece: 0.046, clv: 0.035, confidence: "高" },
          chatgpt: { status: "active", sample_count: 87, brier: 0.201, log_loss: 0.572, rps: 0.183, ece: 0.055, clv: 0.026, confidence: "高" },
        },
      },
    },
    leakage_audit: {
      violations: 0,
      violation_rate: 0,
      passed: true,
    },
  };
}

export function getMockRuntimeConfig(): RuntimeConfigResponse {
  return {
    models: {
      deepseek: {
        key: "deepseek",
        label: "DeepSeek",
        model: "deepseek-chat",
        base_url: "https://api.deepseek.com",
        api_key_configured: true,
        api_key_hint: "sk-...e4f",
        provider_ready: true,
        enabled: true,
        execution_mode: "shadow",
      },
      chatgpt: {
        key: "chatgpt",
        label: "ChatGPT",
        model: "gpt-4o",
        base_url: "https://api.openai.com/v1",
        api_key_configured: true,
        api_key_hint: "sk-...9ab",
        provider_ready: true,
        enabled: true,
        execution_mode: "active",
      },
    },
    portfolio: {
      min_edge: 0.03,
      min_ev: 0.05,
      stake_fraction: 0.15,
      max_total_exposure: 0.5,
      max_drawdown: 0.2,
    },
    simulation_competition_id: "epl",
    updated_at: new Date().toISOString(),
    is_runtime: true,
  };
}
