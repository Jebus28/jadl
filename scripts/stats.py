#!/usr/bin/env python3
"""
All-time league statistics, computed from every season Sleeper holds.

The league has two eras:
  * BCE — Before the Conference Era. Seasons one and two, 2020 and 2021.
    Everyone played everyone; there were no conferences.
  * The Conference Era — season three onward, 2022 to date, when the
    Lombardi (LFC) and Madden (MFC) conferences came in.

Head-to-head records are kept three ways because of that: against your own
conference, against the other one, and everything from BCE.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone

SLOT_ELIGIBILITY = {
    "QB": {"QB"}, "RB": {"RB"}, "WR": {"WR"}, "TE": {"TE"}, "K": {"K"}, "DEF": {"DEF"},
    "FLEX": {"RB", "WR", "TE"},
    "WRRB_FLEX": {"RB", "WR"},
    "REC_FLEX": {"WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}
SINGLE_SLOTS = {"QB", "RB", "WR", "TE", "K", "DEF"}


def optimal_points(scores: dict | None, roster_positions: list, players: dict,
                   played_as: dict | None = None) -> float:
    """
    The most a lineup could have scored - Sleeper's max points - from every
    rostered player's score that week. A player fills his position, or any
    position he was started at that season: Sleeper re-files players now and
    then, and Travis Hunter is a DB in its index now but played WR in 2025.
    """
    pool = []
    for pid, score in (scores or {}).items():
        eligible = set((played_as or {}).get(pid, ()))
        if (players.get(pid) or {}).get("position"):
            eligible.add(players[pid]["position"])
        if eligible:
            pool.append((pid, eligible, float(score or 0)))
    pool.sort(key=lambda row: row[2], reverse=True)
    slots = sorted((s for s in roster_positions if s in SLOT_ELIGIBILITY),
                   key=lambda s: len(SLOT_ELIGIBILITY[s]))
    used, total = set(), 0.0
    for slot in slots:
        for pid, eligible, score in pool:
            if pid not in used and eligible & SLOT_ELIGIBILITY[slot]:
                used.add(pid)
                total += score
                break
    return round(total, 2)


def _pts(settings: dict, key: str) -> float:
    return round((settings.get(key) or 0) + (settings.get(f"{key}_decimal") or 0) / 100, 2)


def bracket_pairs(bracket: list | None) -> set:
    """The set of roster pairings that met in a bracket."""
    pairs = set()
    for match in bracket or []:
        t1, t2 = match.get("t1"), match.get("t2")
        if isinstance(t1, int) and isinstance(t2, int):
            pairs.add(frozenset((t1, t2)))
    return pairs


def final_places(brackets: dict, roster_owner: dict, playoff_teams: int) -> dict:
    """
    owner_id -> final place, from the placement games. The winners bracket settles
    1st to 6th. The losers bracket - the toilet bowl - settles the rest, winners
    advancing, so its p=1 game is for 7th (and the 1.01) and the loser of its last
    game is 10th, Loser of All Losers. Empty until every placement game is played.
    """
    out = {}
    for name, offset in (("winners_bracket", 0), ("losers_bracket", playoff_teams)):
        for match in brackets.get(name) or []:
            p, w, l = match.get("p"), match.get("w"), match.get("l")
            if p and w and l and roster_owner.get(w) and roster_owner.get(l):
                out[roster_owner[w]] = offset + p
                out[roster_owner[l]] = offset + p + 1
    return out if len(out) == len(roster_owner) else {}


def index_season(season: dict, conference_from: int, through_week: int | None = None) -> dict:
    """
    Flatten one season into something the all-time maths can walk. `through_week`
    is the last week whose games are over; later weeks are left out, so a week
    still being played never counts as a result or sets a record.
    """
    year = int(season.get("season") or 0)
    rosters = season.get("rosters") or []
    settings = season.get("settings") or {}
    brackets = season.get("brackets") or {}

    roster_owner = {r["roster_id"]: r.get("owner_id") for r in rosters}
    roster_div = {r["roster_id"]: str((r.get("settings") or {}).get("division") or "1") for r in rosters}
    positions = season.get("roster_positions") or []

    fixtures, lineups, squads, played_as = {}, {}, {}, defaultdict(set)
    for wk, entries in (season.get("matchups") or {}).items():
        if through_week is not None and int(wk) > through_week:
            continue
        grouped = defaultdict(list)
        for entry in entries:
            if entry.get("matchup_id") is not None:
                grouped[entry["matchup_id"]].append(entry)
                # Who started and what each scored, for the player records.
                lineups.setdefault(int(wk), {})[entry["roster_id"]] = [
                    (pid, round(float(pts or 0), 2))
                    for pid, pts in zip(entry.get("starters") or [], entry.get("starters_points") or [])
                    if pid and pid != "0"
                ]
                # Every rostered player's score, for max points and Best Manager.
                squads.setdefault(int(wk), {})[entry["roster_id"]] = entry.get("players_points") or {}
                for slot, pid in zip(positions, entry.get("starters") or []):
                    if slot in SINGLE_SLOTS and pid and pid != "0":
                        played_as[pid].add(slot)
        rows = []
        for sides in grouped.values():
            if len(sides) == 2:
                a, b = sides
                rows.append((
                    (a["roster_id"], round(float(a.get("points") or 0), 2)),
                    (b["roster_id"], round(float(b.get("points") or 0), 2)),
                ))
        fixtures[int(wk)] = rows

    playoff_teams = settings.get("playoff_teams") or 6
    playoff_week_start = settings.get("playoff_week_start") or 15
    starters = [p for p in season.get("roster_positions") or [] if p not in ("BN", "IR", "TAXI")]
    return {
        "season": year,
        "era": "conference" if year >= conference_from else "bce",
        "playoff_week_start": playoff_week_start,
        "playoff_teams": playoff_teams,
        # The last regular-season week has been played, so the table is final.
        "regular_done": any(a[1] or b[1] for a, b in fixtures.get(playoff_week_start - 1, [])),
        "flex": starters.count("FLEX"),
        # Starting slots a player fills. DEF is a team, so it is not one.
        "players": len([p for p in starters if p != "DEF"]),
        "final": final_places(brackets, roster_owner, playoff_teams),
        "roster_owner": roster_owner,
        "roster_div": roster_div,
        "fixtures": fixtures,
        "lineups": lineups,
        "squads": squads,
        "played_as": dict(played_as),
        "roster_positions": positions,
        # The final: the winners bracket's game for 1st, as (winner, loser) roster ids.
        "title_game": next(((m["w"], m["l"]) for m in brackets.get("winners_bracket") or []
                            if m.get("p") == 1 and m.get("w") and m.get("l")), None),
        "winners": bracket_pairs(brackets.get("winners_bracket")),
        "losers": bracket_pairs(brackets.get("losers_bracket")),
        "rosters": rosters,
    }


def games(season: dict):
    """
    Every game that counts in an indexed season, in week order, as
    (week, phase, (roster_id, points), (roster_id, points)), phase being
    "regular", "playoffs" or "consolation". Unplayed weeks are skipped, and so
    are playoff-week games in neither bracket: Sleeper still pairs eliminated
    teams off against each other, and counting those would inflate records.
    """
    cutoff = season["playoff_week_start"]
    for wk, rows in sorted(season["fixtures"].items()):
        for a, b in rows:
            if a[1] == 0 and b[1] == 0:
                continue
            pairing = frozenset((a[0], b[0]))
            if wk < cutoff:
                phase = "regular"
            elif pairing in season["winners"]:
                phase = "playoffs"
            elif pairing in season["losers"]:
                phase = "consolation"
            else:
                continue
            yield wk, phase, a, b


def blank_record() -> dict:
    return {"w": 0, "l": 0, "t": 0}


def _log(rec: dict, mine: float, theirs: float) -> None:
    if mine > theirs:
        rec["w"] += 1
    elif mine < theirs:
        rec["l"] += 1
    else:
        rec["t"] += 1


def all_time(seasons: list[dict], transactions: dict | None = None) -> dict:
    """
    owner_id -> career totals, per-era head-to-head, and notable single weeks.
    `seasons` should be indexed seasons, any order.
    """
    stats = defaultdict(lambda: {
        "career": blank_record(),
        "bce": blank_record(),
        "vs_lfc": blank_record(),
        "vs_mfc": blank_record(),
        "playoffs": blank_record(),
        "consolation": blank_record(),
        "playoff_seasons": set(),
        "pf": 0.0,
        "pa": 0.0,
        "games": 0,
        "best_week": None,     # (points, season, week)
        "worst_week": None,
        "h2h": defaultdict(lambda: {
            "bce": blank_record(),
            "conference": blank_record(),
            "playoffs": blank_record(),
            "consolation": blank_record(),
            "opponent_division": None,
        }),
        "seasons_played": set(),
        "trades": 0,
    })

    for season in sorted(seasons, key=lambda s: s["season"]):
        owner = season["roster_owner"]
        div = season["roster_div"]
        era = season["era"]

        for wk, phase, (rid_a, pts_a), (rid_b, pts_b) in games(season):
            ua, ub = owner.get(rid_a), owner.get(rid_b)
            if not ua or not ub:
                continue

            for me, opp, mine, theirs, opp_rid in (
                (ua, ub, pts_a, pts_b, rid_b),
                (ub, ua, pts_b, pts_a, rid_a),
            ):
                s = stats[me]
                s["seasons_played"].add(season["season"])
                h2h = s["h2h"][opp]

                # Best and worst weeks span every game, playoffs included - Dave's
                # 204.86 came in a playoff week. A side yet to score has not played.
                if mine:
                    best = s["best_week"]
                    if best is None or mine > best[0]:
                        s["best_week"] = (mine, season["season"], wk)
                    worst = s["worst_week"]
                    if worst is None or mine < worst[0]:
                        s["worst_week"] = (mine, season["season"], wk)

                if phase == "regular":
                    _log(s["career"], mine, theirs)
                    s["pf"] += mine
                    s["pa"] += theirs
                    s["games"] += 1

                    if era == "bce":
                        _log(s["bce"], mine, theirs)
                        _log(h2h["bce"], mine, theirs)
                    else:
                        bucket = "vs_lfc" if div.get(opp_rid) == "1" else "vs_mfc"
                        _log(s[bucket], mine, theirs)
                        _log(h2h["conference"], mine, theirs)
                        h2h["opponent_division"] = div.get(opp_rid)
                else:
                    _log(s[phase], mine, theirs)
                    _log(h2h[phase], mine, theirs)
                    if phase == "playoffs":
                        s["playoff_seasons"].add(season["season"])

    for owner_id, s in stats.items():
        played = s["career"]["w"] + s["career"]["l"] + s["career"]["t"]
        s["win_pct"] = round(100 * (s["career"]["w"] + 0.5 * s["career"]["t"]) / played) if played else 0
        s["ppg"] = round(s["pf"] / s["games"], 1) if s["games"] else 0.0
        s["pf"] = round(s["pf"], 2)
        s["pa"] = round(s["pa"], 2)
        s["playoff_appearances"] = len(s["playoff_seasons"])

    if transactions:
        for owner_id, count in transactions.items():
            if owner_id in stats:
                stats[owner_id]["trades"] = count

    return stats


def _owners(season: dict) -> dict:
    return {r["roster_id"]: r.get("owner_id") for r in season.get("rosters") or []}


# --------------------------------------------------------------------------- #
# trades - the Trade Centre
# --------------------------------------------------------------------------- #
# A trade is held as a list of moves, each one asset going from one manager to
# another: a player, a draft pick (season, round and whose pick it was to begin
# with) or FAAB. Sleeper's trades and the ones made by hand take the same shape.
def kickoff(year: int, state: dict | None = None) -> date:
    """
    The day an NFL season starts. Sleeper gives it for the season it is on;
    otherwise it is the Thursday after Labor Day, the first Monday in September.
    """
    if state and str(state.get("season")) == str(year) and state.get("season_start_date"):
        return date.fromisoformat(state["season_start_date"])
    first = date(year, 9, 1)
    return first + timedelta(days=(7 - first.weekday()) % 7 + 3)


def trade_window(trade: dict, state: dict | None = None) -> tuple:
    """
    ("in", 2025) for a trade made during the 2025 season; ("off", 2025) for one
    in the off-season before it, the old site's "2024/25 off-season". Sleeper
    files everything from a league's creation to the end of week one under leg
    1, so a leg-1 trade is in-season only once kickoff day is over.
    """
    season, leg = trade["season"], trade.get("leg")
    if leg and leg > trade.get("last_week", 17):
        return ("off", season + 1)
    if leg and leg > 1:
        return ("in", season)
    over = datetime.combine(kickoff(season, state) + timedelta(days=1), time(), timezone.utc)
    return ("off", season) if trade["when"] < over.timestamp() * 1000 else ("in", season)


def _sleeper_trade(txn: dict, owner: dict) -> dict:
    rosters = txn.get("roster_ids") or []
    drops = txn.get("drops") or {}
    moves = []
    for pid, rid in (txn.get("adds") or {}).items():
        giver = drops.get(pid)
        if giver is None and len(rosters) == 2:
            giver = next(r for r in rosters if r != rid)
        moves.append({"kind": "player", "player_id": pid, "to": owner.get(rid), "from": owner.get(giver)})
    for pick in txn.get("draft_picks") or []:
        moves.append({"kind": "pick", "season": str(pick["season"]), "round": pick["round"],
                      "original": owner.get(pick["roster_id"]),
                      "to": owner.get(pick["owner_id"]), "from": owner.get(pick["previous_owner_id"])})
    for faab in txn.get("waiver_budget") or []:
        moves.append({"kind": "faab", "amount": faab["amount"],
                      "to": owner.get(faab["receiver"]), "from": owner.get(faab["sender"])})
    return {"id": txn["transaction_id"], "when": txn.get("status_updated") or txn.get("created") or 0,
            "leg": txn.get("leg"), "manual": False, "note": "",
            "owners": [owner.get(r) for r in rosters], "moves": moves}


def manual_trades(entries: list[dict], managers: dict, players: dict) -> list[dict]:
    """
    The trades Sleeper never recorded, from league.config.json: deals done by
    hand on draft day, the picks moved in the draft room and any player by a
    commissioner move. `managers` maps name -> user_id. A pick is written
    "season round original-owner" - "2025 3 Dave" is Dave's 2025 third - and a
    player by name, or by Sleeper id where the name is not unique.
    """
    lookup = defaultdict(list)
    for pid, p in players.items():
        if p.get("full_name"):
            lookup[p["full_name"].lower()].append(pid)

    def uid(name):
        if name not in managers:
            raise SystemExit(f"manual_trades: there is no manager called {name!r}")
        return managers[name]

    def player_id(name):
        if str(name).isdigit():
            return str(name)
        found = lookup.get(str(name).lower(), [])
        if len(found) != 1:
            raise SystemExit(f"manual_trades: {name!r} matches {len(found)} players - give the Sleeper id")
        return found[0]

    out = []
    for i, entry in enumerate(entries):
        # A day, or a day and a UTC time where it has to sort against other trades.
        stamp = datetime.fromisoformat(str(entry["date"]))
        if len(str(entry["date"])) == 10:
            stamp = stamp.replace(hour=12)
        stamp = stamp.replace(tzinfo=stamp.tzinfo or timezone.utc)
        day = stamp.date()
        sides = list((entry.get("sides") or {}).items())
        if len(sides) != 2:
            raise SystemExit(f"manual_trades: the {day} trade needs exactly two sides")
        (a, got_a), (b, got_b) = sides
        moves = []
        for to, frm, got in ((uid(a), uid(b), got_a), (uid(b), uid(a), got_b)):
            for name in got.get("players") or []:
                moves.append({"kind": "player", "player_id": player_id(name), "to": to, "from": frm})
            for text in got.get("picks") or []:
                season, rnd, original = str(text).split()
                moves.append({"kind": "pick", "season": season, "round": int(rnd),
                              "original": uid(original), "to": to, "from": frm})
            if got.get("faab"):
                moves.append({"kind": "faab", "amount": int(got["faab"]), "to": to, "from": frm})
        # Trades at the same moment keep the order they are listed in.
        out.append({"id": f"manual-{day}-{i}", "when": int(stamp.timestamp() * 1000) + i,
                    "season": day.year, "leg": None, "manual": True, "note": entry.get("note") or "",
                    "owners": [uid(a), uid(b)], "moves": moves})
    return out


def trade_log(seasons: list[dict], manual: list[dict] = (), state: dict | None = None) -> list[dict]:
    """
    Every completed trade, oldest first: Sleeper's, and the ones it never
    recorded. Each carries its window - the season it was made in, or the
    off-season before one - and its number within that window, oldest first,
    as the old Trade Centre numbered them.
    """
    log = [dict(t) for t in manual]
    for season in seasons:
        owner = _owners(season)
        last_week = ((season.get("settings") or {}).get("playoff_week_start") or 15) + 2
        for items in (season.get("transactions") or {}).values():
            for txn in items:
                if txn.get("type") == "trade" and txn.get("status") == "complete":
                    log.append(dict(_sleeper_trade(txn, owner), season=int(season["season"]),
                                    last_week=last_week))
    log.sort(key=lambda t: t["when"])
    count = defaultdict(int)
    for trade in log:
        trade["window"] = trade_window(trade, state)
        count[trade["window"]] += 1
        trade["number"] = count[trade["window"]]
    return log


def draft_board(seasons: list[dict]) -> dict:
    """
    (season, round, original owner) -> what became of that pick: its number in
    the round and the player taken with it. Read from the rookie drafts, whose
    slot map says whose pick each slot was to begin with. The first season's
    draft was the startup, not a rookie draft, so it is left out.
    """
    board = {}
    for season in seasons:
        if season.get("previous_league_id") in (None, "", "0"):
            continue
        owner = _owners(season)
        for draft in season.get("drafts") or []:
            slots = {int(k): owner.get(v) for k, v in (draft.get("slot_to_roster_id") or {}).items()}
            teams = draft.get("teams") or len(slots) or 1
            for p in draft.get("picks") or []:
                original = slots.get(p.get("draft_slot"))
                if not original or not p.get("round") or not p.get("pick_no"):
                    continue
                board[(str(draft.get("season")), p["round"], original)] = {
                    "number": f"{p['round']}.{p['pick_no'] - (p['round'] - 1) * teams:02d}",
                    "player_id": p.get("player_id"), "name": p.get("name"),
                    "position": p.get("position"), "made_by": owner.get(p.get("roster_id")),
                }
    return board


def trade_table(log: list[dict]) -> dict:
    """owner_id -> trades made, what came in and went out, and who with."""
    out = defaultdict(lambda: {"trades": 0, "players_in": 0, "players_out": 0, "picks_in": 0,
                               "picks_out": 0, "faab_in": 0, "faab_out": 0, "partners": Counter()})
    for trade in log:
        for uid in trade["owners"]:
            out[uid]["trades"] += 1
            out[uid]["partners"].update(o for o in trade["owners"] if o != uid)
        for move in trade["moves"]:
            kind = {"player": "players", "pick": "picks", "faab": "faab"}[move["kind"]]
            n = move["amount"] if move["kind"] == "faab" else 1
            if move["to"]:
                out[move["to"]][kind + "_in"] += n
            if move["from"]:
                out[move["from"]][kind + "_out"] += n
    return out


def trade_loose_ends(seasons: list[dict], log: list[dict], board: dict) -> list[dict]:
    """
    Anything Sleeper shows changing hands that no trade explains - a pick sent
    by someone who did not hold it, a pick made in the draft by someone the
    trades never gave it to, or a player moved between teams by the
    commissioner. Each is the sign of a deal done by hand that belongs in
    league.config.json's manual_trades.
    """
    ends, holder = [], {}
    for trade in log:
        for move in trade["moves"]:
            if move["kind"] != "pick":
                continue
            key = (move["season"], move["round"], move["original"])
            if move["from"] != holder.get(key, move["original"]):
                ends.append({"kind": "sent", "pick": key, "trade": trade,
                             "sender": move["from"], "holder": holder.get(key, move["original"])})
            holder[key] = move["to"]
    for key, made in sorted(board.items()):
        if made["made_by"] and made["made_by"] != holder.get(key, key[2]):
            ends.append({"kind": "made", "pick": key, "made": made, "holder": holder.get(key, key[2])})

    by_hand = {(m["player_id"], m["from"], m["to"])
               for t in log if t["manual"] for m in t["moves"] if m["kind"] == "player"}
    for season in seasons:
        owner = _owners(season)
        for items in (season.get("transactions") or {}).values():
            for txn in items:
                if txn.get("type") != "commissioner":
                    continue
                for pid, rid in (txn.get("adds") or {}).items():
                    giver = (txn.get("drops") or {}).get(pid)
                    if giver is None or giver == rid:
                        continue
                    if (pid, owner.get(giver), owner.get(rid)) not in by_hand:
                        ends.append({"kind": "moved", "player_id": pid, "from": owner.get(giver),
                                     "to": owner.get(rid), "when": txn.get("status_updated")})
    return ends


def conference_finish(season: dict) -> dict:
    """
    owner_id -> (division, place) for where each manager finished in their own
    conference. Matt schedules the following season's inter-conference games off
    this: last year's two fifth-placed teams meet first, the two winners last.
    """
    by_div = defaultdict(list)
    for r in season["rosters"]:
        st = r.get("settings") or {}
        by_div[str(st.get("division") or "1")].append(
            (st.get("wins", 0), _pts(st, "fpts"), r.get("owner_id"))
        )
    out = {}
    for div, rows in by_div.items():
        rows.sort(reverse=True)
        for place, (_w, _pf, owner_id) in enumerate(rows, 1):
            if owner_id:
                out[owner_id] = (div, place)
    return out


def season_table(season: dict, players: dict | None = None) -> list[dict]:
    """Final regular-season table for one season, richest first."""
    rows = []
    for r in season["rosters"]:
        st = r.get("settings") or {}
        rows.append({
            "roster_id": r["roster_id"],
            "owner_id": r.get("owner_id"),
            "division": str(st.get("division") or "1"),
            "wins": st.get("wins", 0),
            "losses": st.get("losses", 0),
            "ties": st.get("ties", 0),
            "fpts": _pts(st, "fpts"),
            "fpts_against": _pts(st, "fpts_against"),
            "max_points": _pts(st, "ppts"),
        })
    rows.sort(key=lambda r: (r["wins"], r["fpts"]), reverse=True)
    for i, row in enumerate(rows, 1):
        row["place"] = i
    return rows


# --------------------------------------------------------------------------- #
# the record books - rebuilt from the Google Sheets on the old History page
# --------------------------------------------------------------------------- #
def weekly_scores(seasons: list[dict]) -> list[dict]:
    """
    One row per side per game that counts - regular season, playoffs and toilet
    bowl alike, as Matt's sheets have it. A side yet to score is left out.
    """
    out = []
    for season in seasons:
        owner = season["roster_owner"]
        for wk, phase, a, b in games(season):
            for (rid, pts), (opp_rid, against) in ((a, b), (b, a)):
                if pts and owner.get(rid):
                    out.append({"owner_id": owner[rid], "opponent_id": owner.get(opp_rid),
                                "points": pts, "against": against, "season": season["season"],
                                "week": wk, "phase": phase, "flex": season["flex"]})
    return out


def player_weeks(seasons: list[dict]) -> list[dict]:
    """
    Every starter's score in every game that counts. Bench points won nothing,
    and nor did a game outside both brackets in a playoff week, so neither sets
    a record however big.
    """
    out = []
    for season in seasons:
        owner = season["roster_owner"]
        for wk, phase, a, b in games(season):
            for rid, _team_points in (a, b):
                if not owner.get(rid):
                    continue
                for pid, pts in season["lineups"].get(wk, {}).get(rid, []):
                    out.append({"player_id": pid, "points": pts, "owner_id": owner[rid],
                                "season": season["season"], "week": wk, "phase": phase})
    return out


def season_records(seasons: list[dict]) -> list[dict]:
    """
    One row per manager per finished regular season, for the Dominators and the
    Loser-minators. Points are Sleeper's own season total, as on the History and
    Standings pages; summing the games can differ by a point where a stat
    correction landed late. Points per player per game divide by the starting
    slots less DEF, which puts one-flex and two-flex seasons on the same footing.
    """
    out = []
    for season in seasons:
        if not season["regular_done"]:
            continue
        tally = defaultdict(lambda: {"w": 0, "l": 0, "t": 0, "pf": 0.0})
        for _wk, phase, a, b in games(season):
            if phase == "regular":
                for (rid, pts), (_opp, against) in ((a, b), (b, a)):
                    _log(tally[rid], pts, against)
                    tally[rid]["pf"] += pts
        in_conferences = season["era"] == "conference"
        conf = conference_finish(season) if in_conferences else {}
        table = season_table(season)
        overall = {row["owner_id"]: row["place"] for row in table}
        official = {row["roster_id"]: row["fpts"] for row in table}
        for rid, t in tally.items():
            uid = season["roster_owner"].get(rid)
            played = t["w"] + t["l"] + t["t"]
            if not uid or not played:
                continue
            out.append({
                "owner_id": uid, "season": season["season"],
                "division": season["roster_div"].get(rid) if in_conferences else None,
                "w": t["w"], "l": t["l"], "t": t["t"],
                "win_pct": (t["w"] + 0.5 * t["t"]) / played,
                "pf": official.get(rid, round(t["pf"], 2)),
                "per_player": official.get(rid, t["pf"]) / played / max(season["players"], 1),
                "regular_place": conf[uid][1] if uid in conf else overall.get(uid),
                "final_place": season["final"].get(uid),
            })
    return out


def streaks(seasons: list[dict]) -> dict:
    """
    owner_id -> {"W": run, "L": run}: each manager's longest winning and losing
    runs, as lists of (season, week). Runs carry across seasons and through the
    playoffs and the toilet bowl. A bye is no game, so it neither extends nor
    breaks a run; a tie breaks both. Of equal runs, the first stands.
    """
    results = defaultdict(list)
    for season in sorted(seasons, key=lambda s: s["season"]):
        owner = season["roster_owner"]
        for wk, _phase, a, b in games(season):
            for (rid, pts), (_opp, against) in ((a, b), (b, a)):
                if owner.get(rid):
                    res = "W" if pts > against else "L" if pts < against else "T"
                    results[owner[rid]].append((season["season"], wk, res))
    out = {}
    for uid, played in results.items():
        best = {"W": [], "L": []}
        run, kind = [], None
        for season, wk, res in played:
            if res != kind:
                run, kind = [], res
            run.append((season, wk))
            if res in best and len(run) > len(best[res]):
                best[res] = list(run)
        out[uid] = best
    return out


def waiver_record(seasons_transactions: list[dict], seasons: list[dict], players: dict) -> dict | None:
    """The biggest winning FAAB bid there has been. The first to reach it keeps it."""
    best = None
    for season, txns in zip(seasons, seasons_transactions):
        for wk, items in sorted((txns or {}).items(), key=lambda kv: int(kv[0])):
            for txn in items:
                if txn.get("type") != "waiver" or txn.get("status") != "complete":
                    continue
                bid = (txn.get("settings") or {}).get("waiver_bid") or 0
                if best is not None and bid <= best["bid"]:
                    continue
                adds = txn.get("adds") or {}
                pid = next(iter(adds), None)
                rid = adds.get(pid) if pid else (txn.get("roster_ids") or [None])[0]
                best = {"bid": bid, "owner_id": season["roster_owner"].get(rid),
                        "player": (players.get(pid) or {}).get("full_name") or pid,
                        "season": season["season"], "week": int(wk)}
    return best


# --------------------------------------------------------------------------- #
# team honours - rebuilt from the Honours block on the old team pages
# --------------------------------------------------------------------------- #
def best_managers(seasons: list[dict], players: dict) -> dict:
    """
    owner_id -> {season: [weeks]}, the weeks each manager was Best Manager: the
    highest score as a share of max points, which is the Awards sheet's rule in
    Matt's 2025 and 2026 workbooks. Regular season only. A tie shares the week.
    """
    out = defaultdict(lambda: defaultdict(list))
    for season in seasons:
        owner, shares = season["roster_owner"], defaultdict(dict)
        for wk, phase, a, b in games(season):
            if phase != "regular":
                continue
            for rid, pts in (a, b):
                most = optimal_points(season["squads"].get(wk, {}).get(rid), season["roster_positions"],
                                      players, season["played_as"])
                if pts and most and owner.get(rid):
                    shares[wk][owner[rid]] = round(pts / most, 9)
        for wk, week in sorted(shares.items()):
            top = max(week.values())
            for uid, share in week.items():
                if share == top:
                    out[uid][season["season"]].append(wk)
    return out


def honours(seasons: list[dict]) -> dict:
    """
    owner_id -> every honour won, newest season first, each appearing once it is
    settled and never before. From the brackets, once the placement games are
    all played: champion (with the final), the consolation bracket (7th, the
    1.01) and Loser of All Losers. From the finished regular season: the
    conference winners - the whole league's in BCE - and the top scorer, on
    Sleeper's own season total. From the finished season: its highest and lowest
    weekly scores, and its best player week. Single weeks count every game, as
    the record books do.
    """
    out = defaultdict(list)
    for season in sorted(seasons, key=lambda s: s["season"], reverse=True):
        year, final, owner = season["season"], season["final"], season["roster_owner"]

        def add(uid, kind, **detail):
            if uid:
                out[uid].append(dict(detail, kind=kind, season=year))

        if final:
            placed = {p: uid for uid, p in final.items()}
            detail = {}
            if season["title_game"]:
                won, lost = season["title_game"]
                for _wk, phase, a, b in games(season):
                    if phase == "playoffs" and frozenset((a[0], b[0])) == frozenset((won, lost)):
                        mine, theirs = (a, b) if a[0] == won else (b, a)
                        detail = {"opponent": owner.get(lost), "points": mine[1], "against": theirs[1]}
            add(placed.get(1), "champion", **detail)
            add(placed.get(season["playoff_teams"] + 1), "consolation", place=season["playoff_teams"] + 1)
            add(placed.get(len(final)), "spoon", place=len(final))

        if season["regular_done"]:
            table = season_table(season)
            if season["era"] == "conference":
                standing = conference_finish(season)
                winners = [r for r in table if standing.get(r["owner_id"], ("", 0))[1] == 1]
            else:
                winners = table[:1]
            for row in sorted(winners, key=lambda r: r["division"]):
                add(row["owner_id"], "regular", w=row["wins"], l=row["losses"], t=row["ties"],
                    division=row["division"] if season["era"] == "conference" else None)
            top = max(table, key=lambda r: r["fpts"])
            add(top["owner_id"], "top_scorer", points=top["fpts"])

        if final:
            scores = weekly_scores([season])
            for kind, pick in (("high_week", max), ("low_week", min)):
                row = pick(scores, key=lambda r: (r["points"], -r["week"] if pick is max else r["week"]))
                add(row["owner_id"], kind, points=row["points"], week=row["week"], phase=row["phase"])
            best = max(player_weeks([season]), key=lambda r: (r["points"], -r["week"]), default=None)
            if best:
                add(best["owner_id"], "player_week", player_id=best["player_id"], points=best["points"],
                    week=best["week"], phase=best["phase"])
    return out
