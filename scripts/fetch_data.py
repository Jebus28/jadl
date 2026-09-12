#!/usr/bin/env python3
"""
Pull everything the site needs from Sleeper and write it to data/.

Runs on a schedule in GitHub Actions. Nothing here is typed by hand.
Sleeper's read API needs no key and no account.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
API = "https://api.sleeper.app/v1"

USER_AGENT = "jadl-site/1.0 (github actions)"


# --------------------------------------------------------------------------- #
# plumbing
# --------------------------------------------------------------------------- #
def get(url: str, tries: int = 4):
    """GET some JSON, retrying politely. Returns None on a 404."""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if attempt == tries - 1:
                raise
        except Exception:
            if attempt == tries - 1:
                raise
        time.sleep(2 * (attempt + 1))
    return None


def write(name: str, payload) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / name
    path.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    print(f"  wrote {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")


def load_config() -> dict:
    return json.loads((ROOT / "league.config.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# players: one big file, trimmed hard and refreshed at most daily
# --------------------------------------------------------------------------- #
KEEP_PLAYER_FIELDS = ("full_name", "position", "team", "injury_status", "years_exp")


def fetch_players(force: bool = False) -> dict:
    path = DATA / "players.json"
    day = 24 * 60 * 60
    if path.exists() and not force and (time.time() - path.stat().st_mtime) < day:
        print("  players.json is fresh, skipping the 5MB download")
        return json.loads(path.read_text(encoding="utf-8"))

    print("  downloading the player index (large, once a day)")
    raw = get(f"{API}/players/nfl") or {}
    trimmed = {}
    for pid, p in raw.items():
        if not isinstance(p, dict):
            continue
        if not p.get("full_name") and not p.get("last_name"):
            continue
        trimmed[pid] = {k: p.get(k) for k in KEEP_PLAYER_FIELDS if p.get(k) is not None}
    write("players.json", trimmed)
    return trimmed


# --------------------------------------------------------------------------- #
# projections: Sleeper's projected stats, for the playoff odds
# --------------------------------------------------------------------------- #
PROJECTIONS = "https://api.sleeper.app/projections/nfl"
PROJECTED_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")
PROJECTIONS_EVERY = 6 * 60 * 60


def fetch_projections(current: dict, state: dict, last_week: int) -> None:
    """
    Sleeper's projected stats for each regular-season week still to play, scored
    with this league's own settings (the TE premium included) and kept as
    player -> points. The feed is not in Sleeper's documented API, so if it fails
    the old file stays and the odds fall back on each team's scoring. Refreshed
    at most every six hours. The time is kept inside the file, because a fresh
    checkout gives every file a new mtime.
    """
    path = DATA / "projections.json"
    season = str(current.get("season"))
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if old.get("season") == season and time.time() - (old.get("fetched") or 0) < PROJECTIONS_EVERY:
        print("  projections.json is fresh, skipping")
        return
    kind = state.get("season_type")
    if str(state.get("season")) != season or kind not in ("pre", "regular"):
        print("  no regular season to project")
        return
    first = 1 if kind == "pre" else max(1, int(state.get("week") or 1))
    scoring = current.get("scoring_settings") or {}
    query = "&".join("position[]=" + p for p in PROJECTED_POSITIONS)
    weeks = {}
    try:
        for wk in range(first, last_week + 1):
            points = {}
            for row in get(f"{PROJECTIONS}/{season}/{wk}?season_type=regular&{query}") or []:
                stats = row.get("stats") or {}
                total = sum(v * scoring.get(k, 0) for k, v in stats.items() if isinstance(v, (int, float)))
                if row.get("player_id") and total:
                    points[row["player_id"]] = round(total, 2)
            if points:
                weeks[str(wk)] = points
    except Exception as exc:
        print(f"  projections unavailable ({exc}), keeping what we had")
        return
    if not weeks:
        print("  projections came back empty, keeping what we had")
        return
    write("projections.json", {"season": season, "fetched": int(time.time()), "weeks": weeks})


# --------------------------------------------------------------------------- #
# which league is the current one
# --------------------------------------------------------------------------- #
def successor(league: dict, managers: list) -> dict | None:
    """
    The league that follows this one on Sleeper, or None if there is not one
    yet. Sleeper links each season back to the one before but never forward, so
    the way on is a manager's own leagues for the next season: whichever of them
    points back at the league we hold. Tried manager by manager, because only
    the people in a league can list it.
    """
    season = int(league.get("season") or 0) + 1
    if season < 2020:
        return None
    for uid in managers:
        for lg in get(f"{API}/user/{uid}/leagues/nfl/{season}") or []:
            if lg.get("previous_league_id") == league.get("league_id"):
                return lg
    return None


def resolve_league(cfg: dict, state: dict) -> str:
    """
    The league id of the season the league is on now, walking forward from the
    one in league.config.json. Sleeper mints a new id every season, and this is
    what saves Matt changing the config when the league rolls over: as soon as
    he creates the new season on Sleeper, the site follows it.

    The walk only looks ahead once the season it holds is finished, so an
    ordinary in-season refresh costs one extra call and no more.
    """
    league_id = cfg["league"]["current_league_id"]
    managers = list(cfg.get("managers") or {})
    for _step in range(10):
        league = get(f"{API}/league/{league_id}")
        if not league:
            return league_id
        over = (league.get("status") == "complete"
                or int(state.get("season") or 0) > int(league.get("season") or 0))
        nxt = successor(league, managers) if over else None
        if not nxt:
            return league_id
        print(f"  {league.get('season')} has rolled over to {nxt.get('season')}"
              f" ({nxt['league_id']})")
        league_id = nxt["league_id"]
    return league_id


# --------------------------------------------------------------------------- #
# one season
# --------------------------------------------------------------------------- #
def fetch_season(league_id: str, weeks: int, want_matchups: bool = True) -> dict:
    league = get(f"{API}/league/{league_id}")
    if not league:
        raise SystemExit(f"Sleeper has no league {league_id}")
    # However the playoffs are set up, go as far as the championship week.
    weeks = max(weeks, ((league.get("settings") or {}).get("playoff_week_start") or 0) + 2)

    season = {
        "league_id": league_id,
        "season": league.get("season"),
        "name": league.get("name"),
        "status": league.get("status"),
        "settings": league.get("settings", {}),
        "metadata": league.get("metadata", {}),
        "scoring_settings": league.get("scoring_settings", {}),
        "roster_positions": league.get("roster_positions", []),
        "previous_league_id": league.get("previous_league_id"),
        "users": get(f"{API}/league/{league_id}/users") or [],
        "rosters": get(f"{API}/league/{league_id}/rosters") or [],
        "matchups": {},
        "brackets": {},
    }

    if want_matchups:
        for wk in range(1, weeks + 1):
            wk_data = get(f"{API}/league/{league_id}/matchups/{wk}")
            if not wk_data:
                continue
            # A week nobody has played yet comes back as a list of zeroes.
            if all((m.get("points") or 0) == 0 for m in wk_data) and wk > 1:
                season["matchups"][str(wk)] = wk_data
                continue
            season["matchups"][str(wk)] = wk_data

    for bracket in ("winners_bracket", "losers_bracket"):
        got = get(f"{API}/league/{league_id}/{bracket}")
        if got:
            season["brackets"][bracket] = got

    season["transactions"] = {}
    for wk in range(1, weeks + 1):
        got = get(f"{API}/league/{league_id}/transactions/{wk}")
        if got:
            # Trades whole, for the Trade Centre. Of the rest, only completed
            # waiver claims, trimmed to what the waiver record needs: who, whom
            # and the FAAB bid. Free-agent pickups and failed bids are noise.
            keep = [t for t in got if t.get("type") == "trade"]
            keep += [
                {k: t.get(k) for k in ("type", "status", "roster_ids", "adds", "settings",
                                       "leg", "created", "transaction_id")}
                for t in got
                if t.get("type") == "waiver" and t.get("status") == "complete"
            ]
            # A commissioner move that takes a player off one team and gives him
            # to another is the player half of a trade made by hand - the draft-day
            # deals Sleeper never recorded. Kept so the build can check each one
            # is accounted for in league.config.json.
            keep += [
                {k: t.get(k) for k in ("type", "status", "roster_ids", "adds", "drops",
                                       "leg", "status_updated", "transaction_id")}
                for t in got
                if t.get("type") == "commissioner" and t.get("status") == "complete"
                and len(t.get("roster_ids") or []) > 1
            ]
            if keep:
                season["transactions"][str(wk)] = keep

    # The rookie drafts, so a traded pick can be shown as the player it became,
    # and so the build can spot a pick that changed hands in the draft room,
    # where Sleeper records no trade. Auctions are free-agent bidding, not drafts.
    season["drafts"] = []
    for draft in get(f"{API}/league/{league_id}/drafts") or []:
        if draft.get("type") == "auction":
            continue
        full = get(f"{API}/draft/{draft['draft_id']}") or draft
        picks = get(f"{API}/draft/{draft['draft_id']}/picks") or []
        season["drafts"].append({
            "draft_id": draft["draft_id"],
            "season": draft.get("season"),
            "type": draft.get("type"),
            "status": full.get("status"),
            "start_time": full.get("start_time"),
            "rounds": (full.get("settings") or {}).get("rounds"),
            "teams": (full.get("settings") or {}).get("teams"),
            "slot_to_roster_id": full.get("slot_to_roster_id") or {},
            "picks": [{
                "round": p.get("round"),
                "draft_slot": p.get("draft_slot"),
                "pick_no": p.get("pick_no"),
                "roster_id": p.get("roster_id"),
                "player_id": p.get("player_id"),
                "name": " ".join(filter(None, ((p.get("metadata") or {}).get("first_name"),
                                               (p.get("metadata") or {}).get("last_name")))),
                "position": (p.get("metadata") or {}).get("position"),
            } for p in picks],
        })

    return season


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    cfg = load_config()
    total_weeks = cfg["season"]["championship_week"]

    print("Sleeper state")
    state = get(f"{API}/state/nfl") or {}
    write("state.json", state)
    print(f"  {state.get('season')} {state.get('season_type')} week {state.get('week')}")

    print("Current season")
    current_id = resolve_league(cfg, state)
    current = fetch_season(current_id, total_weeks)
    write("current.json", current)

    print("Projections")
    fetch_projections(current, state, cfg["season"]["regular_season_weeks"])

    print("Player index")
    fetch_players()

    print("Past seasons")
    history = []
    prev_id = current.get("previous_league_id")
    guard = 0
    while prev_id and guard < 25:
        guard += 1
        past = fetch_season(prev_id, total_weeks)
        print(f"  {past['season']} ({prev_id})")
        history.append(past)
        prev_id = past.get("previous_league_id")
    write("history.json", history)

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
