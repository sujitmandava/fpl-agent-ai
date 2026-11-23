"""Persistent agent memory: your FPL setup between runs.

One readable JSON file per team (the CLI and API use
``<FPL_MEMORY_DIR>/<team id>.json``, default ``memory/``), separate from the
SQLite cache so season or schema resets never erase it. Any tool or agent can
read it.

What it holds:

* **Setup snapshot** from the last sync: squad with purchase/selling prices,
  bank, free transfers, chips (played / available / expired per window),
  team name, rank and leagues.
* **Overrides** for facts the public API can't see, e.g. transfers you have
  already made for the next deadline. Each override is tied to a gameweek
  and expires once that deadline passes.
* **Preferences**: locked players (never sell / must buy), banned players
  (never buy / sell if owned), free-text notes.
* **Recommendation log**: the last recommendations, so you can compare plan
  vs. outcome.

If the FPL API is unreachable, the agent plans from the last snapshot.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fpl_agent.data_ingest.manager import ManagerState

DEFAULT_PATH = Path("fpl_memory.json")
MEMORY_VERSION = 1
MAX_RECOMMENDATIONS = 20
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty() -> dict:
    return {
        "version": MEMORY_VERSION,
        "manager": {},
        "season": None,
        "synced_at": None,
        "synced_source": None,
        "planning_gw": None,
        "squad": [],
        "bank": None,
        "free_transfers": None,
        "team_value": None,
        "chips": [],
        "overrides": {},
        "locked": [],
        "banned": [],
        "notes": [],
        "recommendations": [],
    }


class AgentMemory:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or os.environ.get("FPL_MEMORY") or DEFAULT_PATH)
        self.data = _empty()
        if self.path.exists():
            loaded = json.loads(self.path.read_text())
            self.data.update(loaded)

    # -- Persistence ----------------------------------------------------------

    def save(self) -> None:
        """Write atomically so a crash can't leave a half-written file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".fpl_memory.", suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

    @property
    def has_snapshot(self) -> bool:
        return bool(self.data.get("squad"))

    # -- Sync -----------------------------------------------------------------

    def record_sync(
        self,
        manager_id: int,
        state: ManagerState,
        planning_gw: int,
        season: str | None,
        players,  # DataFrame
        teams,    # DataFrame
        chips: list[dict],
    ) -> None:
        """Store the latest setup pulled from the FPL API."""
        if self.data.get("season") and season and self.data["season"] != season:
            # New season: old squad, chips and log are meaningless; keep notes.
            notes = self.data.get("notes", [])
            self.data = _empty()
            self.data["notes"] = notes
        name = dict(zip(players["id"], players["web_name"]))
        pos = dict(zip(players["id"], players["element_type"]))
        team_of = dict(zip(players["id"], players["team_id"]))
        now_cost = dict(zip(players["id"], players["now_cost"]))
        short = dict(zip(teams["id"], teams["short_name"])) if not teams.empty else {}
        bought = getattr(state, "purchase_prices", {}) or {}

        entry = state.entry or {}
        # Every classic league, private (invitational) ones first: those are the
        # mini-leagues worth planning against; public ones compare with the top.
        leagues = sorted(
            ({"id": lg.get("id"), "name": lg.get("name"), "rank": lg.get("entry_rank"),
              "size": lg.get("rank_count"), "private": lg.get("league_type") == "x"}
             for lg in (entry.get("leagues", {}) or {}).get("classic", [])),
            key=lambda lg: not lg["private"],
        )
        self.data.update(
            season=season,
            synced_at=_now(),
            synced_source=state.source,
            planning_gw=planning_gw,
            manager={
                "id": manager_id,
                "team_name": entry.get("name") or self.data["manager"].get("team_name"),
                "overall_points": entry.get("summary_overall_points"),
                "overall_rank": entry.get("summary_overall_rank"),
                "leagues": leagues or self.data["manager"].get("leagues", []),
            },
            squad=[
                {
                    "id": int(pid),
                    "name": name.get(pid, str(pid)),
                    "pos": POS.get(int(pos.get(pid, 0)), "?"),
                    "team": short.get(team_of.get(pid), ""),
                    "selling_price": int(state.selling_prices.get(pid, 0)),
                    "purchase_price": int(bought[pid]) if pid in bought else None,
                    "now_cost": int(now_cost.get(pid, 0)),
                }
                for pid in state.squad
            ],
            bank=int(state.bank),
            free_transfers=int(state.free_transfers),
            team_value=entry.get("last_deadline_value"),
            chips=chips,
        )
        self.prune_overrides(planning_gw)

    def to_manager_state(self) -> ManagerState:
        """Rebuild the last-known setup (offline fallback)."""
        squad = [p["id"] for p in self.data["squad"]]
        return ManagerState(
            squad=squad,
            selling_prices={p["id"]: p["selling_price"] for p in self.data["squad"]},
            bank=int(self.data.get("bank") or 0),
            free_transfers=int(self.data.get("free_transfers") or 1),
            source="memory",
            notes=[f"FPL API unreachable: planning from memory saved {self.data.get('synced_at')}."],
            chips_played=[{"name": c["name"], "event": c["event"]}
                          for c in self.data.get("chips", []) if c.get("status") == "played"],
        )

    # -- Overrides ------------------------------------------------------------

    def set_override(self, key: str, value, gw: int, reason: str = "") -> None:
        self.data["overrides"][key] = {"value": value, "gw": gw, "set_at": _now(), "reason": reason}

    def clear_overrides(self) -> None:
        self.data["overrides"] = {}

    def prune_overrides(self, planning_gw: int) -> list[str]:
        """Drop overrides for gameweeks whose deadline has passed."""
        expired = [k for k, v in self.data["overrides"].items() if v.get("gw") != planning_gw]
        for k in expired:
            del self.data["overrides"][k]
        return expired

    def active_overrides(self, planning_gw: int) -> dict:
        return {k: v["value"] for k, v in self.data["overrides"].items() if v.get("gw") == planning_gw}

    # -- Preferences ----------------------------------------------------------

    def _ids(self, key: str) -> set[int]:
        return {p["id"] for p in self.data.get(key, [])}

    @property
    def locked_ids(self) -> set[int]:
        return self._ids("locked")

    @property
    def banned_ids(self) -> set[int]:
        return self._ids("banned")

    def lock(self, pid: int, name: str) -> None:
        self.unlock(pid)
        self.data["locked"].append({"id": pid, "name": name, "added_at": _now()})

    def ban(self, pid: int, name: str) -> None:
        self.unlock(pid)
        self.data["banned"].append({"id": pid, "name": name, "added_at": _now()})

    def unlock(self, pid: int) -> bool:
        before = len(self.data["locked"]) + len(self.data["banned"])
        self.data["locked"] = [p for p in self.data["locked"] if p["id"] != pid]
        self.data["banned"] = [p for p in self.data["banned"] if p["id"] != pid]
        return before != len(self.data["locked"]) + len(self.data["banned"])

    def add_note(self, text: str) -> None:
        self.data["notes"].append({"text": text, "added_at": _now()})

    def remove_note(self, index: int) -> dict:
        return self.data["notes"].pop(index)

    # -- Recommendation log ---------------------------------------------------

    def record_recommendation(self, gw: int, rec, names: dict[int, str], chip_advice: list[str]) -> None:
        self.data["recommendations"].append({
            "gw": gw,
            "created_at": _now(),
            "transfers": [{"out": t.sell_name, "in": t.buy_name} for t in rec.transfers],
            "hits": rec.transfer_cost,
            "captain": names.get(rec.captain_id),
            "vice_captain": names.get(rec.vice_captain_id),
            "starting_xi": [names.get(p) for p in rec.starting_xi],
            "projected_points": rec.next_gw_points,
            "chip_advice": chip_advice,
        })
        self.data["recommendations"] = self.data["recommendations"][-MAX_RECOMMENDATIONS:]

    # -- Chips ----------------------------------------------------------------

    def available_chips(self) -> list[dict]:
        return [c for c in self.data.get("chips", []) if c.get("status") == "available"]
