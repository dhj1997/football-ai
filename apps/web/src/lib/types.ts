export type DateFilter = "today" | "tomorrow" | "history";
export type LeagueFilter = "all" | "epl" | "laliga" | "csl";
export type ModelKey = "deepseek" | "chatgpt";

export interface StandingRow {
  rank: number;
  team: Team;
  played: number;
  wins: number;
  draws: number;
  losses: number;
  goals_for: number;
  goals_against: number;
  goal_difference: number;
  points: number;
  note: string | null;
}

export interface LeagueSnapshot {
  league_key: Exclude<LeagueFilter, "all">;
  league_name: string;
  season: {
    year: number;
    name: string;
    start_date: string | null;
    end_date: string | null;
  };
  standings: StandingRow[];
  team_count: number;
  source: string;
  updated_at: string;
}

export interface Team {
  provider_id?: number;
  name: string;
  original_name?: string;
  code: string;
  logo?: string | null;
}

export interface RecentMatch {
  date: string;
  home: string;
  away: string;
  score: string;
  result: "W" | "D" | "L";
  team_is_home?: boolean;
}

export interface AvailabilityPlayer {
  team: "home" | "away" | "unknown";
  name: string;
  reason: string;
}

export interface LineupPlayer {
  name: string;
  number: number | null;
  position: string;
  starter: boolean;
}

export interface TeamProfile {
  name?: string;
  original_name?: string;
  logo?: string | null;
  country?: string | null;
  founded?: number | null;
  venue?: string | null;
  capacity?: number | null;
  city?: string | null;
  website?: string | null;
}

export interface SquadPlayer {
  id: number | null;
  name: string;
  original_name: string;
  age: number | null;
  number: number | null;
  position: string;
  nationality: string | null;
  photo: string | null;
  market_value: number | null;
  market_value_currency: string | null;
  market_value_source: string | null;
  transfermarkt_id: string | null;
}

export interface Fixture {
  id: string;
  provider_id: number | null;
  league_key: Exclude<LeagueFilter, "all">;
  league: { id: number; name: string; country: string; mark: string };
  kickoff: string;
  status: "scheduled" | "finished" | "postponed" | "cancelled" | "live";
  home_team: Team;
  away_team: Team;
  score: { home: number; away: number } | null;
  venue: string;
  lineup_confirmed: boolean;
  is_demo: boolean;
}

export interface EvidenceContext {
  recent_form: {
    home: Array<RecentMatch | string>;
    away: Array<RecentMatch | string>;
    home_points_per_game: number;
    away_points_per_game: number;
    updated_at: string | null;
  };
  head_to_head: Array<{ date: string; home: string; away: string; score: string }>;
  availability: {
    home_missing: number;
    away_missing: number;
    notes: string[];
    players: AvailabilityPlayer[];
    updated_at: string | null;
  };
  lineup: {
    confirmed: boolean;
    home_strength: number;
    away_strength: number;
    home_formation: string | null;
    away_formation: string | null;
    home_players: LineupPlayer[];
    away_players: LineupPlayer[];
    updated_at: string | null;
  };
  teams: { home: TeamProfile; away: TeamProfile };
  squads: { home: SquadPlayer[]; away: SquadPlayer[] };
  odds: {
    bookmaker: string;
    home: number;
    draw: number;
    away: number;
    asian_handicap: number | null;
    asian_handicap_home_odd?: number | null;
    asian_handicap_away_odd?: number | null;
    updated_at: string;
    is_demo: boolean;
  } | null;
  source?: string | null;
  synced_at?: string | null;
}

export interface Prediction {
  id: string;
  fixture_id: string;
  created_at: string;
  phase: "preliminary" | "confirmed_lineup";
  model_version: string;
  model_key?: ModelKey;
  competition_id?: string;
  probabilities: { home: number; draw: number; away: number };
  expected_goals: { home: number; away: number };
  top_scores: Array<{ score: string; probability: number }>;
  asian_handicap: {
    line: number;
    home_settlement: Record<"full_win" | "half_win" | "push" | "half_loss" | "full_loss", number>;
  } | null;
  confidence: string;
  evidence: {
    recent_form_at: string;
    availability_at: string;
    lineup_at: string | null;
    odds_at: string | null;
    is_demo: boolean;
  };
  baseline?: {
    model_version: string;
    probabilities: { home: number; draw: number; away: number };
  };
  evidence_snapshot_id?: string;
  evidence_hash?: string;
  predicted_outcome?: "home" | "draw" | "away";
  asian_handicap_assessment?: {
    available: boolean;
    line: number | null;
    selection: "home_handicap" | "away_handicap" | "none";
    confidence: number;
    reason: string;
  };
  data_completeness?: number;
  evidence_fields?: Record<string, boolean>;
  recommendation?: {
    market: "1x2" | "asian_handicap" | "no_bet";
    selection: "home" | "draw" | "away" | "home_handicap" | "away_handicap" | "none";
    confidence: number;
    recommended_stake_fraction: number;
    reason: string;
  };
  analysis_summary?: string;
  risk_factors?: string[];
  missing_evidence?: string[];
  ai?: {
    status: "completed" | "failed" | "unconfigured" | "skipped_demo";
    provider: string;
    requested_model: string;
    returned_model: string | null;
    prompt_version: string | null;
    request_id: string | null;
    usage: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number } | null;
    error: string | null;
    provider_failures?: Array<{ provider: string; error: string }>;
  };
}

export interface SimulatedBet {
  id: string;
  prediction_id: string;
  fixture_id: string;
  fixture_date: string;
  placed_at: string;
  market: "1x2" | "asian_handicap";
  selection: string;
  handicap_line: number | null;
  odds: number;
  stake: number;
  status: "placed" | "settled";
  league_key: Exclude<LeagueFilter, "all">;
  kickoff: string;
  home_team: string;
  away_team: string;
  model_version: string;
  model_key?: ModelKey;
  competition_id?: string;
  reason: string | null;
  is_simulated: true;
  balance_before: number;
  balance_after_placement: number;
  settled_at: string | null;
  settlement_result: "full_win" | "half_win" | "push" | "half_loss" | "full_loss" | null;
  return_amount: number | null;
  net_profit: number | null;
  balance_after_settlement: number | null;
}

export interface FixtureDetail {
  fixture: Fixture;
  context: EvidenceContext;
  prediction: Prediction | null;
  predictions: Partial<Record<ModelKey, Prediction | null>>;
  bet: SimulatedBet | null;
  bets: Partial<Record<ModelKey, SimulatedBet | null>>;
  competition_id?: string;
  capabilities: { evidence_sync: boolean; deepseek?: boolean; chatgpt?: boolean };
  evidence_error?: string | null;
  prediction_error?: string | null;
}

export interface BankrollSummary {
  initial_balance: number;
  balance: number;
  equity: number;
  net_profit: number;
  total_staked: number;
  settled_staked: number;
  total_returns: number;
  open_exposure: number;
  roi: number;
  hit_rate: number;
  bet_count: number;
  settled_count: number;
  open_count: number;
  max_drawdown: number;
  equity_curve: Array<{ at: string | null; balance: number; bet_id?: string }>;
  is_simulated: true;
  model_key?: ModelKey;
  competition_id?: string;
  accounts?: Record<ModelKey, BankrollSummary>;
}

export interface PredictionSettlement {
  id: string;
  prediction_id: string;
  fixture_id: string;
  fixture_date: string;
  league_key: Exclude<LeagueFilter, "all">;
  season: string;
  model_version: string;
  model_key?: ModelKey;
  competition_id?: string;
  actual_outcome: "home" | "draw" | "away";
  predicted_outcome: "home" | "draw" | "away";
  correct: boolean;
  brier_score: number;
  data_completeness: number | null;
  score: { home: number; away: number };
}

export interface PredictionMetrics {
  sample_size: number;
  correct_count: number;
  accuracy: number;
  average_brier_score: number | null;
  average_data_completeness: number | null;
  asian_handicap_results: Record<"full_win" | "half_win" | "push" | "half_loss" | "full_loss", number>;
  filters: Record<string, string | null>;
  items: PredictionSettlement[];
}

export interface JobRun {
  id: string;
  job_name: "fixtures" | "standings" | "analysis" | "settlement";
  started_at: string;
  finished_at: string | null;
  status: "running" | "success" | "partial" | "failed";
  item_count: number;
  error_summary: string | null;
  result: Record<string, unknown> | null;
}

export interface StandingsResponse {
  items: LeagueSnapshot[];
  sync_status: "fresh" | "updated" | "stale" | "failed" | "unconfigured";
  source: string;
  last_synced_at: string | null;
}

export interface TeamPlayer {
  id: string | null;
  name: string;
  original_name: string;
  number: number | null;
  position: string;
  position_code: string | null;
  age: number | null;
  date_of_birth: string | null;
  nationality: string | null;
  photo: string | null;
  status: string | null;
  injuries: Array<{ type: string | null; status: string | null; detail: string | null; date: string | null }>;
  statistics: {
    appearances: number;
    substitute_appearances: number;
    goals: number;
    assists: number;
    yellow_cards: number;
    red_cards: number;
    saves: number;
    goals_conceded: number;
  };
}

export interface TeamSeasonMatch {
  id: string;
  date: string;
  status: "scheduled" | "live" | "finished";
  status_text: string | null;
  home: { id: string | null; name: string; original_name: string; logo: string | null };
  away: { id: string | null; name: string; original_name: string; logo: string | null };
  home_score: number | null;
  away_score: number | null;
  result: "W" | "D" | "L" | null;
  team_is_home: boolean;
  venue: string | null;
}

export interface TeamSnapshot {
  league_key: Exclude<LeagueFilter, "all">;
  team_id: string;
  season: { year: number; name: string };
  team: {
    name: string;
    original_name: string;
    abbreviation: string | null;
    logo: string | null;
    color: string | null;
    record_summary: string | null;
    standing_summary: string | null;
  };
  coach: { name: string; nationality: string | null } | null;
  roster: TeamPlayer[];
  roster_count: number;
  matches: TeamSeasonMatch[];
  source: string;
  updated_at: string;
}

export interface TeamDetailResponse {
  item: TeamSnapshot;
  sync_status: "fresh" | "updated" | "stale" | "failed" | "unconfigured";
}
