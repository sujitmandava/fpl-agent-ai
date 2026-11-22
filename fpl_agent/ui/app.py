"""FPL Agent dashboard (Streamlit).

Run with ``python fpl_agent.py ui`` (or ``streamlit run fpl_agent/ui/app.py``).
Reads the same .env, database and memory file as the CLI.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:          # allow `streamlit run fpl_agent/ui/app.py`
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from fpl_agent import engine  # noqa: E402
from fpl_agent.engine import POS, EngineError, PlanOptions  # noqa: E402

load_dotenv(ROOT / ".env")
DB = os.environ.get("FPL_DB", "fpl_agent.db")
MEMORY = os.environ.get("FPL_MEMORY", "fpl_memory.json")

st.set_page_config(page_title="FPL Agent", page_icon="⚽", layout="wide")
ss = st.session_state

GOOD, BAD = (46, 160, 67), (218, 54, 51)


def money(v) -> str:
    return f"£{v / 10:.1f}m" if v else "—"


# -- State --------------------------------------------------------------------

def load_setup(manager_id: int, force: bool = False) -> engine.Setup | None:
    if force or ss.get("setup_for") != manager_id:
        with st.spinner("Refreshing FPL data and your team…"):
            try:
                ss.setup = engine.sync_setup(DB, MEMORY, manager_id,
                                             os.environ.get("FPL_REFRESH_TOKEN") or None)
                ss.setup_for = manager_id
            except EngineError as exc:
                st.error(str(exc))
                return None
        ss.pop("plan_key", None)
    return ss.setup


def invalidate_plan() -> None:
    ss.pop("plan_key", None)


def get_plan(setup: engine.Setup, opts: PlanOptions):
    m = setup.memory
    key = (tuple(vars(opts).items()), frozenset(m.locked_ids), frozenset(m.banned_ids),
           str(m.active_overrides(setup.planning_gw)))
    if ss.get("plan_key") != key:
        with st.spinner("Forecasting and optimising…"):
            ss.plan = engine.plan_from_setup(setup, opts, record=False)
        ss.plan_key = key
    return ss.plan


# -- Sidebar ------------------------------------------------------------------

st.sidebar.title("FPL Agent")
default_id = int(os.environ.get("FPL_MANAGER_ID") or 0)
manager_id = st.sidebar.number_input("Manager ID", min_value=0, value=default_id, step=1)
refresh = st.sidebar.button("Refresh from FPL", width="stretch")

if not manager_id:
    st.info("Enter your FPL manager ID in the sidebar (or set FPL_MANAGER_ID in .env).")
    st.stop()

setup = load_setup(int(manager_id), force=refresh)
if setup is None:
    st.stop()

st.sidebar.subheader("Plan options")
horizon = st.sidebar.slider("Horizon (gameweeks)", 1, 8, int(os.environ.get("FPL_HORIZON", 6)))
chip_modes = ["No chip"]
if setup.chip_available("wildcard"):
    chip_modes.append("Wildcard")
if setup.chip_available("freehit"):
    chip_modes.append("Free Hit")
chip_mode = st.sidebar.radio("Chip this week", chip_modes, horizontal=True)
with st.sidebar.expander("Advanced"):
    ft_choice = st.selectbox("Free transfers", ["From memory / API", 0, 1, 2, 3, 4, 5],
                             help="One-off value for this session. To keep it, use the Memory tab.")
    bank_one_off = st.number_input("Bank override (£m, 0 = none)", min_value=0.0, step=0.1, value=0.0)
    ft_value = st.slider("Value of a saved transfer", 0.0, 3.0, 1.0, 0.25,
                         help="Higher = fewer, surer moves.")
    bench_weight = st.slider("Bench weight", 0.0, 0.5, 0.1, 0.05,
                             help="How much bench xPts count (auto-sub value).")

opts = PlanOptions(
    horizon=horizon,
    free_transfers=None if ft_choice == "From memory / API" else int(ft_choice),
    bank=bank_one_off or None,
    wildcard=chip_mode == "Wildcard",
    free_hit=chip_mode == "Free Hit",
    bench_weight=bench_weight,
    ft_value=ft_value,
)

try:
    plan = get_plan(setup, opts)
except EngineError as exc:
    st.error(str(exc))
    st.stop()

rec, mem = plan.rec, setup.memory.data
table = engine.player_table(setup, plan.forecast).set_index("id")
gw_cols = [c for c in plan.forecast.columns if c.startswith("expected_points_gw")]
gws = [int(c.removeprefix("expected_points_gw")) for c in gw_cols]
name = table["web_name"].to_dict()
next_gw = rec.next_gw or setup.planning_gw
opp = engine.next_opponents(setup.fixtures, setup.teams, next_gw)

st.sidebar.divider()
st.sidebar.caption(f"Data: {'live' if setup.synced else 'memory snapshot (API down)'} · "
                   f"team source: {setup.state.source}")
if st.sidebar.button("Save this plan to memory", width="stretch"):
    names = dict(zip(setup.players["id"], setup.players["web_name"]))
    setup.memory.record_recommendation(setup.planning_gw, rec, names, plan.chip_advice)
    setup.memory.save()
    st.sidebar.success("Saved.")


# -- Header -------------------------------------------------------------------

mgr = mem.get("manager", {})
rank = f" · rank {mgr['overall_rank']:,}" if mgr.get("overall_rank") else ""
st.title(f"{mgr.get('team_name') or 'Your team'}")
st.caption(
    f"Planning GW{setup.planning_gw}{rank} · "
    f"{plan.team_state.free_transfers} free transfers ({plan.sources['free_transfers']}) · "
    f"bank £{plan.team_state.bank / 10:.1f}m ({plan.sources['bank']}) · "
    f"chips: {', '.join(c['label'] + ' (≤GW' + str(c['window'][1]) + ')' for c in setup.chips if c['status'] == 'available') or 'none'}"
)
for note in setup.notes + setup.state.notes:
    st.caption(f"⚠️ {note}")
for n in mem.get("notes", []):
    st.caption(f"📝 {n['text']}")

tab_plan, tab_team, tab_players, tab_fix, tab_mem, tab_model = st.tabs(
    ["Suggestions", "My team", "Players", "Fixtures", "Memory", "Model check"])


def player_rows(ids: list[int], captain: int | None = None, vice: int | None = None) -> pd.DataFrame:
    rows = []
    for pid in ids:
        r = table.loc[pid]
        role = "C" if pid == captain else ("V" if pid == vice else "")
        rows.append({
            "": role, "Pos": r["pos"], "Player": r["web_name"], "Team": r["team"],
            "Opp": opp.get(int(r["team_id"]), "—"),
            "xMins": r.get("exp_minutes"), "xG/90": r.get("xg90"), "xA/90": r.get("xa90"),
            "DC%": None if r["pos"] == "GK" else 100 * (r.get("dc_rate") or 0),
            "CS%": 100 * (r.get("cs_next") or 0),
            f"xPts GW{next_gw}": r.get("expected_points_next"),
            f"xPts {len(gws)}GW": r.get("total_expected_points"),
            "News": r.get("news") or "",
        })
    return pd.DataFrame(rows)


NUM = {
    "xMins": st.column_config.NumberColumn(format="%.0f"),
    "xG/90": st.column_config.NumberColumn(format="%.2f"),
    "xA/90": st.column_config.NumberColumn(format="%.2f"),
    "DC%": st.column_config.NumberColumn(format="%.0f%%", help="Chance of defensive-contribution points in a 60+ min game"),
    "CS%": st.column_config.NumberColumn(format="%.0f%%", help="Clean-sheet chance next GW"),
    f"xPts GW{next_gw}": st.column_config.NumberColumn(format="%.1f"),
    f"xPts {len(gws)}GW": st.column_config.NumberColumn(format="%.1f"),
}


# -- Suggestions --------------------------------------------------------------

with tab_plan:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"Projected GW{next_gw}", f"{rec.next_gw_points:.1f}", help="Starting XI + captain")
    c2.metric(f"vs. no transfers, GW{next_gw}", f"{rec.expected_points_delta:+.1f}")
    c3.metric(f"vs. no transfers, {len(gws)} GWs",
              f"{rec.horizon_delta:+.1f}" if rec.horizon_delta is not None else "—")
    c4.metric("Hits", f"-{rec.transfer_cost}" if rec.transfer_cost else "0")

    st.subheader("Transfers")
    if rec.transfers:
        st.dataframe(pd.DataFrame([{
            "Pos": t.position, "Out": t.sell_name, "Sell": t.sell_price, "In": t.buy_name,
            "Buy": t.buy_price, f"ΔxPts GW{next_gw}": t.ep_gain_next,
            f"ΔxPts {len(gws)}GW": t.ep_gain_horizon,
            "In: next fixtures": " · ".join(
                engine.next_opponents(setup.fixtures, setup.teams, g).get(
                    int(table.loc[t.buy_id, "team_id"]), "—") for g in gws[:3]) if t.buy_id else "",
        } for t in rec.transfers]), hide_index=True, width="stretch", column_config={
            "Sell": st.column_config.NumberColumn(format="£%.1fm"),
            "Buy": st.column_config.NumberColumn(format="£%.1fm"),
            f"ΔxPts GW{next_gw}": st.column_config.NumberColumn(format="%+.1f"),
            f"ΔxPts {len(gws)}GW": st.column_config.NumberColumn(format="%+.1f"),
        })
    else:
        st.success("No transfer clears the bar this week. Bank the free transfer.")

    st.subheader(f"Lineup – GW{next_gw}")
    st.markdown(f"**Captain:** {name.get(rec.captain_id)} · **Vice:** {name.get(rec.vice_captain_id)}")
    st.dataframe(player_rows(rec.starting_xi, rec.captain_id, rec.vice_captain_id),
                 hide_index=True, width="stretch", column_config=NUM)
    st.caption("Bench (in order, GK first)")
    st.dataframe(player_rows(rec.bench_order), hide_index=True, width="stretch",
                 column_config=NUM)

    left, right = st.columns(2)
    with left:
        st.subheader("Chip outlook")
        st.markdown("\n".join(f"- {line}" for line in plan.chip_advice) or "Nothing to flag.")
    with right:
        st.subheader("Plan by gameweek")
        res = plan.result
        st.dataframe(pd.DataFrame([{
            "GW": g, "Captain": name.get(res.captains.get(g)),
            "XI + C xPts": sum(plan.forecast.set_index("player_id").get(f"expected_points_gw{g}",
                                pd.Series(dtype=float)).reindex(res.lineups.get(g, [])).fillna(0))
                           + res.captain_points.get(g, 0),
            "Bench xPts": res.bench_points.get(g, 0),
        } for g in res.gameweeks]), hide_index=True, width="stretch", column_config={
            "XI + C xPts": st.column_config.NumberColumn(format="%.1f"),
            "Bench xPts": st.column_config.NumberColumn(format="%.1f"),
        })
        st.caption("Assumes the recommended squad is held; lineup and captain re-picked each week.")

    with st.expander("Rationale"):
        st.text(rec.rationale)


# -- My team ------------------------------------------------------------------

with tab_team:
    order = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}
    squad = sorted(mem.get("squad", []), key=lambda p: (order.get(p["pos"], 9), p["name"]))
    rows = []
    for p in squad:
        r = table.loc[p["id"]] if p["id"] in table.index else {}
        rows.append({
            "Pos": p["pos"], "Player": p["name"], "Team": p["team"],
            "Bought": (p.get("purchase_price") or 0) / 10, "Sell": p["selling_price"] / 10,
            "Now": p["now_cost"] / 10, f"xPts GW{next_gw}": r.get("expected_points_next"),
            f"xPts {len(gws)}GW": r.get("total_expected_points"),
            "xMins": r.get("exp_minutes"), "Status": r.get("news") or "",
        })
    st.subheader("Squad")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
        **NUM, **{c: st.column_config.NumberColumn(format="£%.1fm") for c in ("Bought", "Sell", "Now")}})

    a, b = st.columns(2)
    with a:
        st.subheader("Chips")
        st.dataframe(pd.DataFrame([{
            "Chip": c["label"], "Window": f"GW{c['window'][0]}–{c['window'][1]}",
            "Status": c["status"] + (f" (GW{c['event']})" if c.get("event") else ""),
        } for c in setup.chips]), hide_index=True, width="stretch")
    with b:
        st.subheader("Mini-leagues")
        leagues = mgr.get("leagues", [])
        if leagues:
            st.dataframe(pd.DataFrame([{"League": lg["name"], "Rank": lg["rank"]} for lg in leagues]),
                         hide_index=True, width="stretch")
        else:
            st.caption("None found.")
        st.metric("Overall points", mgr.get("overall_points", "—"))

    if mem.get("recommendations"):
        st.subheader("Saved plans")
        st.dataframe(pd.DataFrame([{
            "GW": r["gw"], "Saved": r["created_at"][:16].replace("T", " "),
            "Transfers": ", ".join(f"{t['out']} → {t['in']}" for t in r["transfers"]) or "none",
            "Captain": r["captain"],
        } for r in reversed(mem["recommendations"])]), hide_index=True, width="stretch")


# -- Players ------------------------------------------------------------------

with tab_players:
    f1, f2, f3, f4 = st.columns([2, 2, 2, 3])
    pos_sel = f1.multiselect("Position", list(POS.values()), default=[])
    team_sel = f2.multiselect("Team", sorted(setup.teams["short_name"]), default=[])
    max_price = f3.slider("Max price (£m)", 3.5, float(table["price"].max()), float(table["price"].max()), 0.5)
    search = f4.text_input("Search name")
    g1, g2 = st.columns([3, 1])
    min_mins = g1.slider("Min expected minutes", 0, 90, 45, 5)
    mine = g2.toggle("My squad only")

    view = table.reset_index()
    view = view[view["price"] <= max_price]
    view = view[view["exp_minutes"].fillna(0) >= min_mins] if not mine else view
    if pos_sel:
        view = view[view["pos"].isin(pos_sel)]
    if team_sel:
        view = view[view["team"].isin(team_sel)]
    if search:
        q = engine.norm(search)
        view = view[view["web_name"].map(engine.norm).str.contains(q, regex=False)
                    | (view["first_name"].fillna("") + " " + view["second_name"].fillna(""))
                    .map(engine.norm).str.contains(q, regex=False)]
    if mine:
        view = view[view["owned"]]

    out = pd.DataFrame({
        "Mine": view["owned"], "Player": view["web_name"], "Team": view["team"], "Pos": view["pos"],
        "Price": view["price"], "Own%": view["selected_by_percent"],
        "xMins": view["exp_minutes"], "xG/90": view["xg90"], "xA/90": view["xa90"],
        "DC%": (view["dc_rate"] * 100).where(view["pos"] != "GK"),
        "CS%": view["cs_next"] * 100,
        **{f"GW{g}": view[f"expected_points_gw{g}"] for g in gws},
        f"xPts {len(gws)}GW": view["total_expected_points"],
        "xPts/£m": view["total_expected_points"] / view["price"],
        "News": view["news"].fillna(""),
    }).sort_values(f"xPts {len(gws)}GW", ascending=False)

    st.caption(f"{len(out)} players · sorted by {len(gws)}-GW xPts · click a header to re-sort")
    st.dataframe(out, hide_index=True, width="stretch", height=620, column_config={
        **NUM,
        "Price": st.column_config.NumberColumn(format="£%.1fm"),
        "Own%": st.column_config.NumberColumn(format="%.1f%%"),
        "xPts/£m": st.column_config.NumberColumn(format="%.2f"),
        **{f"GW{g}": st.column_config.NumberColumn(format="%.1f") for g in gws},
    })


# -- Fixtures -----------------------------------------------------------------

def _shade(values: pd.DataFrame, higher_is_better: bool) -> pd.DataFrame:
    lo, hi = values.min().min(), values.max().max()
    span = (hi - lo) or 1.0

    def css(v):
        if pd.isna(v):
            return "color: gray"
        t = (v - lo) / span
        t = t if higher_is_better else 1 - t
        r, g, b = GOOD if t >= 0.5 else BAD
        return f"background-color: rgba({r},{g},{b},{abs(t - 0.5) * 1.2:.2f})"
    return values.map(css)


with tab_fix:
    metric = st.radio("Colour by", ["Attack (expected goals for)", "Defence (clean-sheet chance)"],
                      horizontal=True)
    grid = engine.fixture_grid(plan.ratings, setup.fixtures, setup.teams, gws)
    grid["value"] = grid["xg_for"] if metric.startswith("Attack") else grid["cs"]
    grid.loc[grid["opp"] == "—", "value"] = float("nan")
    labels = grid.groupby(["team", "gw"])["opp"].apply(lambda s: " + ".join(x for x in s if x != "—") or "—") \
        .unstack()
    values = grid.groupby(["team", "gw"])["value"].sum(min_count=1).unstack()
    order = values.mean(axis=1).sort_values(ascending=False).index
    labels, values = labels.loc[order], values.loc[order]
    labels.columns = values.columns = [f"GW{g}" for g in labels.columns]
    shown = labels.copy()
    fmt = (lambda v: f"{v:.1f}") if metric.startswith("Attack") else (lambda v: f"{v * 100:.0f}%")
    for c in shown.columns:
        shown[c] = [f"{lab}  {fmt(v)}" if pd.notna(v) else lab for lab, v in zip(labels[c], values[c])]
    styled = shown.style.apply(lambda _: _shade(values, True).to_numpy(), axis=None)
    st.dataframe(styled, width="stretch", height=740)
    st.caption("From the model's opponent-adjusted team ratings (xG-weighted, recent form counts more). "
               "Doubles add up; blanks show —. Sorted best to worst over the horizon.")

    st.subheader("Team ratings")
    short = dict(zip(setup.teams["id"], setup.teams["short_name"]))
    r = plan.ratings
    tr = pd.DataFrame({"Team": [short.get(t, t) for t in r.att], "Attack": list(r.att.values()),
                       "Defence": [r.dfn[t] for t in r.att]})
    if not r.form.empty:
        form = r.form.assign(Team=r.form["team_id"].map(short))[
            ["Team", "xg_for", "xg_against", "goals_for", "goals_against"]]
        form.columns = ["Team", "xG for /match", "xG against /match", "Goals for", "Goals against"]
        tr = tr.merge(form, on="Team", how="left")
    st.dataframe(tr.sort_values("Attack", ascending=False), hide_index=True, width="stretch",
                 column_config={"Attack": st.column_config.NumberColumn(format="%.2f", help="1.00 = league average; higher scores more"),
                                "Defence": st.column_config.NumberColumn(format="%.2f", help="1.00 = league average; lower concedes less")})
    st.caption("Recent form = last 6 matches.")


# -- Memory -------------------------------------------------------------------

with tab_mem:
    m = setup.memory
    gw = setup.planning_gw
    ov = m.active_overrides(gw)
    st.subheader(f"Overrides for GW{gw}")
    st.caption("Use these when the API can't see something (e.g. a transfer you already made while "
               "logged out). They expire after the deadline.")
    o1, o2, o3 = st.columns(3)
    with o1.form("ft"):
        ft_new = st.number_input("Free transfers", 0, 5, int(ov.get("free_transfers", m.data.get("free_transfers") or 1)))
        if st.form_submit_button("Save"):
            m.set_override("free_transfers", int(ft_new), gw, "dashboard")
            m.save()
            invalidate_plan()
            st.rerun()
    with o2.form("bank"):
        bank_new = st.number_input("Bank (£m)", 0.0, 100.0, (ov.get("bank", m.data.get("bank") or 0)) / 10, 0.1)
        if st.form_submit_button("Save"):
            m.set_override("bank", int(round(bank_new * 10)), gw, "dashboard")
            m.save()
            invalidate_plan()
            st.rerun()
    with o3:
        st.write("")
        st.write(f"API: {m.data.get('free_transfers')} FT, {money(m.data.get('bank'))}")
        if ov and st.button("Clear overrides"):
            m.clear_overrides()
            m.save()
            invalidate_plan()
            st.rerun()

    st.subheader("Locked and banned players")
    label = {int(pid): f"{r.web_name} ({r.team}, £{r.price:.1f}m)" for pid, r in table.iterrows()}
    ids = sorted(label, key=lambda p: label[p])
    with st.form("prefs"):
        locked_sel = st.multiselect("Locked (always keep or buy)", ids, default=sorted(m.locked_ids),
                                    format_func=label.get)
        banned_sel = st.multiselect("Banned (never buy; sell if owned)", ids, default=sorted(m.banned_ids),
                                    format_func=label.get)
        if st.form_submit_button("Save preferences"):
            for pid in (m.locked_ids | m.banned_ids):
                m.unlock(pid)
            for pid in locked_sel:
                m.lock(pid, name[pid])
            for pid in banned_sel:
                m.ban(pid, name[pid])
            m.save()
            invalidate_plan()
            st.rerun()

    st.subheader("Notes")
    for i, n in enumerate(m.data.get("notes", [])):
        a, b = st.columns([10, 1])
        a.write(f"{n['text']}  \n:gray[{n['added_at'][:10]}]")
        if b.button("✕", key=f"del-note-{i}"):
            m.remove_note(i)
            m.save()
            st.rerun()
    with st.form("note", clear_on_submit=True):
        text = st.text_input("Add a note", placeholder="e.g. Saving Free Hit for the GW blank")
        if st.form_submit_button("Add") and text.strip():
            m.add_note(text.strip())
            m.save()
            st.rerun()
    st.caption(f"Memory file: {m.path.resolve()}")


# -- Model check --------------------------------------------------------------

HOW_IT_WORKS = """
**1. Team strength.** Every team gets an attack and a defence rating from this season's
matches (70% xG, 30% actual goals, recent games count more, adjusted for who they played).
That gives expected goals for and against in every upcoming fixture.

**2. Each player's habits.** From recent matches: how likely he is to play and to play 60+
minutes, his xG and xA per 90, how often he earns defensive-contribution points, plus
saves, bonus and cards. Players with few minutes are pulled toward their position's
average, so one lucky cameo doesn't make a star.

**3. Points per fixture.** Habits × fixture: xG/90 scaled by the minutes he'll play and how
leaky the opponent is, times the points a goal is worth for his position; the same for
assists; clean-sheet and goals-conceded odds from the goals his team is expected to
concede; and so on for every scoring rule. Injury flags cut the next gameweek and fade
over four. Blanks score 0 and doubles add up.

**4. The plan.** An optimiser picks the squad, XI and captain for every gameweek in the
horizon to maximise those points, within budget, formation and 3-per-club rules. A
transfer has to beat the value of saving it, and a hit has to beat 4 points plus that.
"""


def _pct(a: float, b: float) -> str:
    return f"{abs(1 - a / b):.0%}" if b else "—"


with tab_model:
    with st.expander("How the model works", expanded=False):
        st.markdown(HOW_IT_WORKS)

    st.subheader("Has the model been right?")
    st.write("This replays the season. It pretends it's an earlier gameweek, hides everything "
             "after it, asks the model to predict the next few gameweeks, then checks what "
             "actually happened. As a yardstick it does the same with the simplest possible "
             "guess: *each player scores his average so far*.")
    bh = st.slider("Predict this many gameweeks ahead", 1, 6, 3,
                   help="Further ahead is harder; 1 is the next deadline only.")
    bt_key = (bh, setup.planning_gw)
    if st.button("Run backtest", type="primary"):
        from fpl_agent.forecast.backtest import backtest_predictions

        done = setup.fixtures[setup.fixtures["finished"].fillna(0).astype(bool)]
        last_done = int(done["event"].max()) if not done.empty else 0
        cutoffs = [c for c in range(last_done - bh - 3, last_done - bh + 1) if c >= 3]
        if not cutoffs:
            st.warning("Not enough completed gameweeks yet.")
        else:
            with st.spinner("Replaying past gameweeks…"):
                ss.bt = (bt_key, backtest_predictions(
                    setup.players, setup.history, setup.fixtures, setup.teams,
                    setup.scoring, cutoffs, bh))

    if ss.get("bt") and ss.bt[0] == bt_key and not ss.bt[1].empty:
        from fpl_agent.forecast.backtest import by_window, calibration, summarise, top_picks_avg

        d = ss.bt[1]
        m = summarise(d).set_index("model")
        mae_m, mae_b = m.at["xpts", "mae"], m.at["ppg_baseline", "mae"]
        top_m, top_b = top_picks_avg(d, "xpts"), top_picks_avg(d, "ppg_baseline")
        hindsight = top_picks_avg(d, "actual")
        avg_player = float(d["actual"].mean())
        bias = m.at["xpts", "bias"]
        n_gws = d["gw"].nunique()

        k1, k2, k3 = st.columns(3)
        k1.metric("Typical miss per player, per week", f"{mae_m:.1f} pts",
                  f"{mae_m - mae_b:+.1f} vs. average-so-far guess", delta_color="inverse",
                  help="Average gap between predicted and actual points (MAE). Lower is better.")
        k2.metric("Model's top 20 picks scored", f"{top_m:.1f} pts each",
                  f"{top_m - top_b:+.1f} vs. average-so-far picks",
                  help="Each week, take the 20 players the model rated highest and average "
                       "what they really scored. This is what matters for picking a team.")
        k3.metric("Leaning", "about right" if abs(bias) < 0.25 else
                  ("too optimistic" if bias > 0 else "too cautious"),
                  f"{bias:+.1f} pts per prediction", delta_color="off",
                  help="Average of predicted minus actual. Positive = predicts too high.")

        better = mae_m < mae_b and top_m > top_b
        st.markdown(
            f"{'✅' if better else '⚠️'} Over **{len(d):,} predictions** across **{n_gws} gameweeks**, "
            f"the model missed by **{mae_m:.1f} pts** on a typical player-week, "
            f"{_pct(mae_m, mae_b)} {'less' if mae_m < mae_b else 'more'} than the "
            f"average-so-far guess ({mae_b:.1f}). If you had picked its top 20 every week, they'd "
            f"have averaged **{top_m:.1f} pts**, against **{top_b:.1f}** for the guess's top 20, "
            f"**{avg_player:.1f}** for a typical regular, and **{hindsight:.1f}** with perfect "
            f"hindsight.")

        left, right = st.columns([1, 1])
        with left:
            st.markdown("**When the model says X, what did players actually score?**")
            cal = calibration(d)
            st.bar_chart(cal[["predicted", "actual"]].rename(
                columns={"predicted": "Model predicted", "actual": "Actually scored"}),
                stack=False, y_label="Average points", x_label="Predicted points band",
                height=300)
            st.caption("Matching bars mean the forecasts can be taken at face value. "
                       + ", ".join(f"{b}: {int(c):,}" for b, c in cal["count"].items())
                       + " predictions per band.")
        with right:
            st.markdown("**Window by window**")
            w = by_window(d)
            st.dataframe(pd.DataFrame({
                "Predicting": [f"GW{a}–{b}" if a != b else f"GW{a}"
                               for a, b in zip(w["first_gw"], w["last_gw"])],
                "Model miss": w["xpts_mae"], "Guess miss": w["ppg_mae"],
                "Model top 20": w["xpts_top"], "Guess top 20": w["ppg_top"],
            }), hide_index=True, width="stretch", column_config={
                c: st.column_config.NumberColumn(format="%.1f")
                for c in ("Model miss", "Guess miss", "Model top 20", "Guess top 20")})
            st.caption("Each row only uses data from before the weeks it predicts. "
                       "Lower miss and higher top-20 are better.")

        with st.expander("Why is the miss still around 2 points?"):
            st.write("FPL scores are lumpy: a forward who \"should\" get 5 points gets 2 or 8 "
                     "depending on one shot. No model gets close to zero, so judge it against "
                     "the yardstick and on whether its top picks outscore other picks, not on "
                     "the raw miss. A correlation of 0.3 between predicted and actual points is "
                     "normal for single gameweeks.")
        with st.expander("Raw numbers"):
            st.dataframe(m.reset_index(), hide_index=True, width="stretch")
            st.caption("mae = average absolute error; correlation = how well predictions rank "
                       "players (1 = perfectly); bias = predicted − actual on average; "
                       "top20_actual_avg = real points of the top 20 picks each week.")
