import type { Move, PlayerCard, Pos } from "./types";

// SAMPLE DATA for the landing page: an illustrative squad, labelled "Sample" wherever
// it appears. Players are real, numbers are made up for the illustration.
const H = ["12", "13", "14", "15", "16", "17"];

function card(id: number, name: string, team: string, pos: Pos, price: number, x: Partial<PlayerCard> = {}): PlayerCard {
  const next = x.xpts_next ?? 4;
  return {
    id, name, full_name: name, team, pos, price, selling_price: price, owned: true,
    fixture: "—", games_next: 1, xmins: 85, xg90: 0.1, xa90: 0.1, dc_rate: pos === "GK" ? null : 0.3,
    cs_next: 0.3, xpts_next: next, xpts_horizon: next * 6,
    xpts_by_gw: Object.fromEntries(H.map((g, i) => [g, Math.round((next + ((i % 3) - 1) * 0.4) * 10) / 10])),
    p_return_next: 0.5, returns: "6/11", news: "", chance_next: null, selected_by: 10,
    league_eo: 20, rival_owns: false, ...x,
  };
}

export const SAMPLE_RIVAL = "Dan Hughes";

export const SAMPLE_PLAYERS: Record<string, PlayerCard> = Object.fromEntries(
  [
    card(1, "Raya", "ARS", "GK", 5.6, { fixture: "BOU (H)", xpts_next: 4.6, rival_owns: true }),
    card(2, "Gabriel", "ARS", "DEF", 6.3, { fixture: "BOU (H)", xpts_next: 5.1, rival_owns: true }),
    card(3, "Virgil", "LIV", "DEF", 6.1, { fixture: "BRE (a)", xpts_next: 4.4 }),
    card(4, "Muñoz", "CRY", "DEF", 5.8, { fixture: "FUL (H)", xpts_next: 4.2, chance_next: 75, news: "Knock: 75% chance of playing" }),
    card(5, "Salah", "LIV", "MID", 14.1, { fixture: "BRE (a)", xpts_next: 7.4, rival_owns: true }),
    card(6, "Mbeumo", "MUN", "MID", 8.1, { fixture: "EVE (H)", xpts_next: 5.6 }),
    card(7, "Semenyo", "BOU", "MID", 7.4, { fixture: "ARS (a)", xpts_next: 4.3 }),
    card(8, "Palmer", "CHE", "MID", 10.6, {
      fixture: "WOL (H)", xpts_next: 7.0, xmins: 88, xg90: 0.38, xa90: 0.29, returns: "8/11", rival_owns: true, owned: false,
    }),
    card(9, "Haaland", "MCI", "FWD", 14.9, { fixture: "LEE (H)", xpts_next: 9.2, games_next: 1, rival_owns: true }),
    card(10, "Isak", "LIV", "FWD", 10.8, { fixture: "BRE (a)", xpts_next: 5.8 }),
    card(11, "Watkins", "AVL", "FWD", 8.7, { fixture: "SUN (H)", xpts_next: 5.2 }),
    card(12, "Saka", "ARS", "MID", 10.1, { fixture: "BOU (H)", xpts_next: 4.1, chance_next: 50, news: "Hamstring: 50% chance of playing" }),
    card(13, "Sánchez", "CHE", "GK", 5.0, { fixture: "WOL (H)", xpts_next: 3.9 }),
    card(14, "Andersen", "FUL", "DEF", 4.5, { fixture: "CRY (a)", xpts_next: 3.1 }),
    card(15, "Mitoma", "BHA", "MID", 6.4, { fixture: "NFO (a)", xpts_next: 3.6 }),
    card(16, "Wood", "NFO", "FWD", 7.6, { fixture: "BHA (H)", xpts_next: 3.8 }),
  ].map((p) => [String(p.id), p]),
);

export const SAMPLE_XI = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
export const SAMPLE_BENCH = [13, 14, 15, 16];
export const SAMPLE_MOVES: Move[] = [
  { out: 12, in: 8, position: "MID", sell_price: 10.1, buy_price: 10.6, gain_next: 3.1, gain_horizon: 7.8, alternatives: [] },
];
export const SAMPLE_CAPTAIN = 9;
export const SAMPLE_VICE = 5;
