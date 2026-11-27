// Shapes returned by the Python API (fpl_agent/api.py). Numbers may be null when unknown.

export type Pos = "GK" | "DEF" | "MID" | "FWD";

export interface PlayerCard {
  id: number;
  name: string;
  full_name: string;
  team: string;
  pos: Pos;
  price: number | null;
  selling_price: number | null;
  owned: boolean;
  fixture: string;
  games_next: number;
  xmins: number | null;
  xg90: number | null;
  xa90: number | null;
  dc_rate: number | null;
  cs_next: number | null;
  xpts_next: number | null;
  xpts_horizon: number | null;
  xpts_by_gw: Record<string, number | null>;
  p_return_next: number | null;
  returns: string | null;
  news: string;
  chance_next: number | null;
  selected_by: number | null;
  league_eo: number | null;
  rival_owns: boolean;
}

export interface Move {
  out: number;
  in: number;
  position: Pos;
  sell_price: number | null;
  buy_price: number | null;
  gain_next: number | null;
  gain_horizon: number | null;
  alternatives: { id: number; price: number | null; delta: number | null }[];
}

export interface Standing {
  entry: number;
  team_name: string;
  manager_name: string;
  rank: number;
  total: number;
  gw_points: number;
  gap: number; // your total − theirs
  captain: number | null;
  active_chip: string | null;
  chips_now: string[];
  is_me: boolean;
}

export interface Rival {
  entry: number;
  team_name: string;
  manager_name: string;
  rank: number;
  gap: number; // your total − theirs (negative = you trail)
  edge_per_gw: number | null;
  weekly_sd: number | null;
  p_ahead: number | null;
  remaining: number;
  suggested_chase: number | null; // optimiser chase setting that best serves finishing above them
  captain: number | null;
  active_chip: string | null;
  chips_now: string[];
  chips_later: string[];
  squad: number[];
  shared: number[];
  mine_only: number[];
  theirs_only: number[];
  /** Points after hits in each gameweek both played, oldest first. */
  weekly: { gw: number; you: number; them: number }[];
  by_gw: { gw: number; you: number | null; them: number | null; edge: number | null; your_captain: number | null; their_captain: number | null }[];
}

export interface League {
  id: number;
  name: string;
  gw: number;
  size: number;
  partial: boolean;
  loaded: number; // managers whose squads were fetched (the top of a big league, plus you)
  my_rank: number;
  my_total: number;
  standings: Standing[];
  /** Rivals only (you excluded). EO counts the captain twice and the bench zero. */
  ownership: { rivals: number; rows: { id: number; owners: number; captains: number; eo: number | null }[] };
  rival: Rival | null;
}

export interface Chip {
  name: string;
  label: string;
  status: "available" | "played" | "expired" | string;
  window: [number, number] | null;
  event: number | null;
}

export interface Plan {
  team: { id: number; name: string | null; overall_rank: number | null; overall_points: number | null };
  gameweek: { planning: number; next: number; deadline: string | null; horizon: number[] };
  budget: { free_transfers: number; free_transfers_source: string; bank: number; bank_source: string };
  chips: Chip[];
  summary: { next_gw_points: number | null; delta_next: number | null; delta_horizon: number | null; hits: number };
  moves: Move[];
  captain: number;
  vice_captain: number;
  lineup: { xi: number[]; bench: number[]; formation: string };
  chip_advice: string[];
  /** Chips scheduled to distinct weeks before they expire; gw null = hold past the forecast. */
  chip_plan: { name: string; label: string; gw: number | null; gain: number | null; expires: number; on_wildcard_squad: boolean }[];
  plan_by_gw: { gw: number; captain: number | null; xi_points: number | null; bench_points: number | null }[];
  players: Record<string, PlayerCard>;
  league: League | null;
  /** Every classic league the team is in, private (mini-leagues) first. */
  leagues: { id: number; name: string; rank: number | null; size: number | null; private: boolean }[];
  notes: string[];
  synced: boolean;
  rationale: string;
}

export interface ModelCheck {
  horizon: number;
  predictions: number;
  gameweeks: number;
  first_gw: number;
  last_gw: number;
  model_miss: number;
  baseline_miss: number;
  model_top20: number;
  baseline_top20: number;
  hindsight_top20: number;
  average_player: number;
  bias: number;
}
