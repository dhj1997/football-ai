export type DateFilter = "today" | "tomorrow" | "history";
export type LeagueFilter = "all" | "epl" | "laliga" | "csl";
export type ModelKey = "deepseek" | "chatgpt";

export interface ModelEvaluationMetric {
  status: string;
  sample_count: number;
  brier: number | null;
  log_loss: number | null;
  rps: number | null;
  ece: number | null;
  clv: number | null;
  confidence: string;
}

export interface ModelEvaluationReport {
  league: string;
  sample_count: number;
  confidence: string;
  models: Record<string, ModelEvaluationMetric>;
}

export interface ModelEvaluationResponse {
  experiment_id: string;
  status: string;
  reports: Record<string, ModelEvaluationReport>;
  leakage_audit: { violations: number; violation_rate: number; passed: boolean };
}

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
  canonical_player_id?: string;
  provider_player_id?: string | null;
  identity_status?: "resolved" | "unresolved";
  name: string;
  name_status?: "resolved" | "machine_translated" | "unresolved";
  name_source?: string | null;
  reason: string;
  position?: string | null;
  player_role?: string | null;
  expected_minutes?: number | null;
  attack_contribution?: number | null;
  defense_contribution?: number | null;
  replacement_contribution?: number | null;
  absence_impact?: number | null;
}

export interface LineupPlayer {
  canonical_player_id?: string;
  provider_player_id?: string | null;
  name: string;
  name_status?: "resolved" | "machine_translated" | "unresolved";
  name_source?: string | null;
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
  id: number | string | null;
  canonical_player_id?: string;
  provider_player_id?: string | null;
  name: string;
  name_status?: "resolved" | "machine_translated" | "unresolved";
  name_source?: string | null;
  original_name?: string;
  age: number | null;
  number: number | null;
  position: string;
  nationality: string | null;
  photo: string | null;
  market_value: number | null;
  market_value_eur?: number | null;
  market_value_currency: string | null;
  market_value_source: string | null;
  market_value_as_of?: string | null;
  market_value_freshness?: "fresh" | "stale" | "missing";
  market_value_status?: "available" | "stale" | "missing";
  player_role?: string;
  expected_start_probability?: number;
  expected_minutes?: number;
  attack_contribution?: number;
  defense_contribution?: number;
  absence_impact?: number;
}

export interface PlayerImpactSummary {
  canonical_player_id: string;
  provider_player_id: string | null;
  name: string;
  name_status?: "resolved" | "machine_translated" | "unresolved";
  name_source?: string | null;
  position: string | null;
  position_group: "goalkeeper" | "defense" | "midfield" | "attack";
  player_role: "明星球员" | "关键主力" | "轮换球员" | "边缘球员";
  expected_start_probability: number;
  expected_minutes: number;
  attack_contribution: number;
  defense_contribution: number;
  market_value_eur: number | null;
  market_value_source: string | null;
  market_value_as_of: string | null;
  replacement_contribution?: number | null;
  absence_impact?: number | null;
  expected_replacement?: PlayerImpactSummary | null;
}

export interface TeamPlayerImpact {
  data_status: "complete" | "partial" | "insufficient";
  squad_count: number;
  resolved_absence_count: number;
  unresolved_absence_count: number;
  key_available_players: PlayerImpactSummary[];
  key_absent_players: PlayerImpactSummary[];
  expected_replacements: Array<{
    absent_player: PlayerImpactSummary;
    replacement: PlayerImpactSummary | null;
    replacement_contribution: number;
    absence_impact: number;
  }>;
  attack_retention: number;
  defense_retention: number;
  midfield_retention: number;
  goalkeeper_retention: number;
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
  player_identity?: { resolved_count: number; unresolved_count: number };
  player_impact?: {
    home: TeamPlayerImpact;
    away: TeamPlayerImpact;
    lineup_confirmed: boolean;
    method_version: string;
  };
  player_value?: {
    provider_configured: boolean;
    source: string | null;
    redisplay_authorized: boolean;
    coverage: string[];
    available_count: number;
    missing_count: number;
    status: "available" | "unavailable";
    reason: string | null;
  };
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
  forecast_confidence?: number;
  forecast?: {
    predicted_outcome: "home" | "draw" | "away";
    probabilities: { home: number; draw: number; away: number };
    asian_handicap: {
      available?: boolean;
      line: number | null;
      home_cover_probability: number | null;
      away_cover_probability: number | null;
      confidence?: number;
      reason?: string;
    } | null;
  };
  asian_handicap_forecast?: {
    available: boolean;
    line: number | null;
    home_cover_probability: number | null;
    away_cover_probability: number | null;
    confidence: number;
    reason: string;
  };
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
    reason_codes?: string[];
    decision_status?: "bet" | "no_bet" | "insufficient_data";
    is_deterministic?: boolean;
  };
  model_recommendation?: {
    status: "bet" | "no_bet";
    market: "1x2" | "asian_handicap" | "no_bet";
    selection: "home" | "draw" | "away" | "home_handicap" | "away_handicap" | "none";
    reason: string;
  };
  market_assessment?: {
    odds_status: "fresh" | "stale" | "missing";
    odds_updated_at: string | null;
    bookmaker?: string | null;
    markets: Array<{
      market: "1x2" | "asian_handicap";
      selection: "home" | "draw" | "away" | "home_handicap" | "away_handicap";
      bookmaker?: string | null;
      price: number;
      break_even_probability: number;
      de_vig_probability: number;
      model_probability: number;
      expected_edge: number;
      line?: number;
    }>;
  };
  decision?: {
    status: "bet" | "no_bet" | "insufficient_data";
    market: "1x2" | "asian_handicap" | "no_bet";
    selection: "home" | "draw" | "away" | "home_handicap" | "away_handicap" | "none";
    considered_market: "1x2" | "asian_handicap" | null;
    considered_selection: string | null;
    price: number | null;
    expected_edge: number | null;
    model_confidence: number;
    uncertainty: number;
    stake_fraction: number;
    reason_codes: string[];
    reason: string;
    warning_codes?: string[];
    warning?: string | null;
    model_recommendation_status?: "bet" | "no_bet";
    is_deterministic: true;
    real_money_execution: false;
  };
  execution?: {
    status: "bet" | "no_bet" | "insufficient_data";
    reason_codes: string[];
    reason: string;
    bet_id: string | null;
  };
  player_analysis?: {
    key_available_players: string[];
    key_absent_players: string[];
    replacement_gap: string;
    attack_impact: string;
    defense_impact: string;
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
    evidence_version?: string | null;
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

export interface DecisionAudit {
  id: string;
  fixture_id: string;
  fixture_date: string | null;
  kickoff: string | null;
  league_key: Exclude<LeagueFilter, "all"> | null;
  home_team: string | null;
  away_team: string | null;
  created_at: string | null;
  model_key: ModelKey | string | null;
  model_version: string | null;
  strategy_id: string;
  strategy_version: string;
  strategy_name: string;
  evidence_snapshot_id: string | null;
  decision_status: "bet" | "no_bet" | "insufficient_data" | "unknown";
  market: "1x2" | "asian_handicap" | "no_bet";
  selection: string;
  considered_market: "1x2" | "asian_handicap" | "no_bet" | null;
  considered_selection: string | null;
  price: number | null;
  expected_edge: number | null;
  stake_fraction: number;
  reason_codes: string[];
  reason: string;
  execution_status: "bet" | "no_bet" | "insufficient_data" | "unknown";
  execution_reason: string;
  bet_id: string | null;
  model_recommendation_status: "bet" | "no_bet" | null;
}

export interface StrategyPerformance {
  rank: number;
  model_key: ModelKey | string;
  strategy_id: string;
  strategy_version: string;
  strategy_name: string;
  realized_pnl: number;
  roi: number;
  prediction_samples: number;
  market_comparison_samples: number;
  average_brier: number | null;
  average_log_loss: number | null;
  brier_improvement: number | null;
  clv_samples: number;
  max_drawdown: number;
  gate_status: "READY" | "INSUFFICIENT_SAMPLE" | "QUALITY_FAILED";
  gate_mode: "SHADOW_ONLY" | "EXECUTABLE";
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
  log_loss?: number | null;
  rps?: number | null;
  market_probabilities?: { home: number; draw: number; away: number } | null;
  decision?: {
    status?: "bet" | "no_bet" | "insufficient_data";
    market?: string;
    selection?: string;
    price?: number | null;
    expected_edge?: number | null;
    stake_fraction?: number;
    reason_codes?: string[];
    reason?: string;
  } | null;
  experiment?: {
    model_key?: ModelKey | string | null;
    strategy_id?: string | null;
    strategy_version?: string | null;
    strategy_name?: string | null;
    prompt_version?: string | null;
    decision_policy_version?: string | null;
    ai_view_version?: string | null;
    execution_config_version?: string | null;
  } | null;
  data_completeness: number | null;
  score: { home: number; away: number };
}

export interface PredictionMetrics {
  sample_size: number;
  correct_count: number;
  accuracy: number;
  average_brier_score: number | null;
  average_log_loss?: number | null;
  average_rps?: number | null;
  average_data_completeness: number | null;
  market_comparison?: {
    sample_size: number;
    market_brier_score: number | null;
    market_log_loss: number | null;
    brier_improvement: number | null;
    log_loss_improvement: number | null;
  };
  decision_counts?: { bet: number; no_bet: number; insufficient_data: number; unknown: number };
  portfolio?: {
    settled_position_count: number;
    wins: number;
    losses: number;
    settled_staked: number;
    realized_pnl: number;
    roi: number;
    max_drawdown: number;
    clv_samples: number;
    average_clv: number | null;
  };
  quality_gate?: {
    mode: "SHADOW_ONLY" | "EXECUTABLE";
    status: "READY" | "INSUFFICIENT_SAMPLE" | "QUALITY_FAILED";
    failures: string[];
    counts: {
      settled_fixtures: number;
      prediction_samples: number;
      market_comparison_samples: number;
      clv_samples: number;
    };
    policy: Record<string, number>;
  };
  experiment?: PredictionSettlement["experiment"];
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
  original_name?: string;
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
  home: { id: string | null; name: string; original_name?: string; logo: string | null };
  away: { id: string | null; name: string; original_name?: string; logo: string | null };
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
    original_name?: string;
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
