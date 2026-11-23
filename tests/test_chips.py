"""Tests for the chip plan: chips expire with their window and share weeks."""

from __future__ import annotations

from fpl_agent.planner.chips import ChipValues, chip_outlook, schedule_chips


def _chip(name, window=(1, 19), status="available"):
    label = {"wildcard": "Wildcard", "freehit": "Free Hit", "bboost": "Bench Boost", "3xc": "Triple Captain"}[name]
    return {"name": name, "label": label, "window": list(window), "status": status}


def test_one_chip_per_week_and_all_played_before_expiry():
    weeks = [17, 18, 19]
    # Both chips peak in GW18; only one can have it.
    values = ChipValues(weeks, {"bboost": {17: 5, 18: 12, 19: 6}, "3xc": {17: 6, 18: 10, 19: 7}})
    picks = schedule_chips(values, [_chip("bboost"), _chip("3xc")])
    by = {p.name: p.gw for p in picks}
    assert len(set(by.values())) == 2
    assert by == {"bboost": 18, "3xc": 19}   # 12 + 7 beats 10 + 6
    assert all(p.gw is not None for p in picks)   # expiring chips are never held


def test_hold_when_window_runs_past_lookahead():
    # Window runs to GW19 but the forecast stops at GW4: an ordinary week is held.
    values = ChipValues([3, 4], {"3xc": {3: 6.0, 4: 6.0}})
    assert schedule_chips(values, [_chip("3xc")])[0].gw is None
    # A standout week beats the average week, so it's played.
    values.by_chip["3xc"][3] = 12.0
    assert schedule_chips(values, [_chip("3xc")])[0].gw == 3


def test_chips_after_wildcard_use_rebuilt_squad():
    weeks = [18, 19]
    values = ChipValues(
        weeks,
        {"wildcard": {18: 10.0, 19: 3.0}, "bboost": {18: 5.0, 19: 5.0}},
        after_wildcard={18: {"bboost": {19: 14.0}}},
    )
    picks = {p.name: p for p in schedule_chips(values, [_chip("wildcard"), _chip("bboost")])}
    assert picks["wildcard"].gw == 18 and picks["bboost"].gw == 19
    assert picks["bboost"].on_wildcard_squad and picks["bboost"].gain == 14.0


def test_fixed_chip_is_pinned_and_expired_ignored():
    values = ChipValues([12, 13], {"freehit": {12: 1.0, 13: 9.0}, "bboost": {12: 3.0, 13: 4.0}})
    chips = [_chip("freehit"), _chip("bboost"), _chip("3xc", status="expired")]
    picks = {p.name: p.gw for p in schedule_chips(values, chips, fixed={"freehit": 12})}
    assert picks == {"freehit": 12, "bboost": 13}


def test_outlook_lines_name_this_week():
    values = ChipValues([19], {"bboost": {19: 8.0}})
    chips = [_chip("bboost"), _chip("bboost", window=(20, 38), status="upcoming")]
    lines = chip_outlook(schedule_chips(values, chips), values, chips, {19: {"doubles": [], "blanks": []}})
    assert any("expire after GW19" in line and "GW20" in line for line in lines)
    assert "This week: play Bench Boost." in lines


def test_wildcard_gain_counts_hits_and_kept_free_transfers():
    import pandas as pd
    from fpl_agent.optimizer.milp import OptimizationResult
    from fpl_agent.planner.chips import wildcard_gain

    fc = pd.DataFrame({"player_id": [1, 2], "expected_points_gw5": [6.0, 2.0], "expected_points_gw6": [6.0, 2.0]})
    def res(xi, cap, ins=(), hits=0):
        return OptimizationResult(selected_ids=[], transfers_in=list(ins), transfers_out=[],
                                  total_expected_points=0, transfer_cost=hits, solver_status="Optimal",
                                  gameweeks=[5, 6], lineups={5: xi, 6: xi}, captains={5: cap, 6: cap},
                                  captain_points={g: float(fc.set_index("player_id").loc[cap, f"expected_points_gw{g}"])
                                                  for g in (5, 6)})
    wc, normal = res([1], 1), res([2], 2, ins=[7, 8, 9], hits=4)
    # (12-4) EP a week over two weeks, +4 hit avoided, +2 free transfers kept at 1.5 each.
    assert wildcard_gain(wc, normal, fc, free_transfers=2, ft_value=1.5) == 16 + 4 + 3
