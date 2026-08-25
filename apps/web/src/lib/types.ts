export type DateFilter = "today" | "tomorrow" | "history";
export type LeagueFilter = "all" | "epl" | "laliga" | "csl";

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
}

export interface FixtureDetail {
  fixture: Fixture;
  context: EvidenceContext;
  prediction: Prediction | null;
  capabilities: { evidence_sync: boolean };
}
