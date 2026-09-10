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

from collections import defaultdict


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


def index_season(season: dict, conference_from: int) -> dict:
    """Flatten one season into something the all-time maths can walk."""
    year = int(season.get("season") or 0)
    rosters = season.get("rosters") or []
    settings = season.get("settings") or {}
    brackets = season.get("brackets") or {}

    roster_owner = {r["roster_id"]: r.get("owner_id") for r in rosters}
    roster_div = {r["roster_id"]: str((r.get("settings") or {}).get("division") or "1") for r in rosters}

    fixtures = {}
    for wk, entries in (season.get("matchups") or {}).items():
        grouped = defaultdict(list)
        for entry in entries:
            if entry.get("matchup_id") is not None:
                grouped[entry["matchup_id"]].append(entry)
        rows = []
        for sides in grouped.values():
            if len(sides) == 2:
                a, b = sides
                rows.append((
                    (a["roster_id"], round(float(a.get("points") or 0), 2)),
                    (b["roster_id"], round(float(b.get("points") or 0), 2)),
                ))
        fixtures[int(wk)] = rows

    return {
        "season": year,
        "era": "conference" if year >= conference_from else "bce",
        "playoff_week_start": settings.get("playoff_week_start") or 15,
        "roster_owner": roster_owner,
        "roster_div": roster_div,
        "fixtures": fixtures,
        "winners": bracket_pairs(brackets.get("winners_bracket")),
        "losers": bracket_pairs(brackets.get("losers_bracket")),
        "rosters": rosters,
    }


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
        cutoff = season["playoff_week_start"]
        era = season["era"]

        for wk, rows in sorted(season["fixtures"].items()):
            for (rid_a, pts_a), (rid_b, pts_b) in rows:
                # A week nobody has played yet is not a result.
                if pts_a == 0 and pts_b == 0:
                    continue
                ua, ub = owner.get(rid_a), owner.get(rid_b)
                if not ua or not ub:
                    continue

                pairing = frozenset((rid_a, rid_b))
                if wk < cutoff:
                    phase = "regular"
                elif pairing in season["winners"]:
                    phase = "playoffs"
                elif pairing in season["losers"]:
                    phase = "consolation"
                else:
                    # Playoff-week game that isn't in either bracket: ignore it,
                    # Sleeper still pairs eliminated teams off against each other.
                    continue

                for me, opp, mine, theirs, my_rid, opp_rid in (
                    (ua, ub, pts_a, pts_b, rid_a, rid_b),
                    (ub, ua, pts_b, pts_a, rid_b, rid_a),
                ):
                    s = stats[me]
                    s["seasons_played"].add(season["season"])
                    h2h = s["h2h"][opp]

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

                        best = s["best_week"]
                        if best is None or mine > best[0]:
                            s["best_week"] = (mine, season["season"], wk)
                        worst = s["worst_week"]
                        if worst is None or mine < worst[0]:
                            s["worst_week"] = (mine, season["season"], wk)
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


def count_trades(seasons_transactions: list[dict], seasons: list[dict]) -> dict:
    """
    owner_id -> number of completed trades they were party to, across all seasons.
    `seasons_transactions` is a list of {week: [transaction, ...]} aligned with `seasons`.
    """
    counts = defaultdict(int)
    for season, txns in zip(seasons, seasons_transactions):
        owner = season["roster_owner"]
        for _wk, items in (txns or {}).items():
            for txn in items:
                if txn.get("type") != "trade" or txn.get("status") != "complete":
                    continue
                for rid in txn.get("roster_ids") or []:
                    uid = owner.get(rid)
                    if uid:
                        counts[uid] += 1
    return dict(counts)


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
