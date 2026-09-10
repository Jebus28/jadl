#!/usr/bin/env python3
"""
Turn data/ + league.config.json into the published site in docs/.

Everything a human might want to change from season to season lives in
league.config.json. Nothing in here needs editing year to year.
"""
from __future__ import annotations

import html
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DOCS = ROOT / "docs"
ASSETS = ROOT / "assets"

# Which real positions may fill each starting slot.
SLOT_ELIGIBILITY = {
    "QB": {"QB"},
    "RB": {"RB"},
    "WR": {"WR"},
    "TE": {"TE"},
    "K": {"K"},
    "DEF": {"DEF"},
    "FLEX": {"RB", "WR", "TE"},
    "WRRB_FLEX": {"RB", "WR"},
    "REC_FLEX": {"WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def load(name: str, default=None):
    path = DATA / name
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def e(value) -> str:
    """Escape for HTML."""
    return html.escape(str(value if value is not None else ""), quote=True)


def pts(roster_settings: dict, key: str = "fpts") -> float:
    whole = roster_settings.get(key) or 0
    decimal = roster_settings.get(f"{key}_decimal") or 0
    return round(whole + decimal / 100, 2)


def optimal_points(entry: dict, roster_positions: list[str], players: dict) -> float:
    """
    The most points this roster could have scored with a legal lineup.
    Greedy over the most restrictive slots first, which matches how these
    are normally quoted and is exact for all but pathological rosters.
    """
    scores = entry.get("players_points") or {}
    if not scores:
        return 0.0

    pool = []
    for pid, score in scores.items():
        pos = (players.get(pid) or {}).get("position")
        if pos:
            pool.append([pid, pos, float(score or 0)])
    pool.sort(key=lambda row: row[2], reverse=True)

    slots = [s for s in roster_positions if s in SLOT_ELIGIBILITY]
    slots.sort(key=lambda s: len(SLOT_ELIGIBILITY[s]))

    used, total = set(), 0.0
    for slot in slots:
        allowed = SLOT_ELIGIBILITY[slot]
        for row in pool:
            pid, pos, score = row
            if pid in used or pos not in allowed:
                continue
            used.add(pid)
            total += score
            break
    return round(total, 2)


def manager_lookup(cfg: dict, users: list[dict], rosters: list[dict]) -> dict:
    """roster_id -> everything the templates need about that team."""
    by_user = {u["user_id"]: u for u in users}
    out = {}
    for r in rosters:
        uid = r.get("owner_id")
        user = by_user.get(uid, {})
        configured = (cfg.get("managers") or {}).get(uid, {})
        meta = user.get("metadata") or {}
        out[r["roster_id"]] = {
            "roster_id": r["roster_id"],
            "user_id": uid,
            "manager": configured.get("name") or user.get("display_name") or "Unknown",
            "handle": user.get("display_name") or "",
            "team": (meta.get("team_name") or user.get("display_name") or "Unnamed").strip(),
            "image": configured.get("image"),
            "portrait": configured.get("portrait"),
            "division": str(r.get("settings", {}).get("division") or "1"),
            "wins": r.get("settings", {}).get("wins", 0),
            "losses": r.get("settings", {}).get("losses", 0),
            "ties": r.get("settings", {}).get("ties", 0),
            "fpts": pts(r.get("settings", {}), "fpts"),
            "fpts_against": pts(r.get("settings", {}), "fpts_against"),
        }
    return out


def weekly_results(season: dict, players: dict) -> dict:
    """week -> list of fixtures, each with both sides, scores and optimal points."""
    positions = season.get("roster_positions", [])
    out = {}
    for wk, entries in (season.get("matchups") or {}).items():
        pairs: dict[int, list] = {}
        for entry in entries:
            mid = entry.get("matchup_id")
            if mid is None:
                continue
            pairs.setdefault(mid, []).append(entry)
        fixtures = []
        for mid, sides in sorted(pairs.items()):
            if len(sides) != 2:
                continue
            a, b = sides
            fixtures.append({
                "matchup_id": mid,
                "home": {
                    "roster_id": a["roster_id"],
                    "points": round(float(a.get("points") or 0), 2),
                    "optimal": optimal_points(a, positions, players),
                },
                "away": {
                    "roster_id": b["roster_id"],
                    "points": round(float(b.get("points") or 0), 2),
                    "optimal": optimal_points(b, positions, players),
                },
            })
        out[int(wk)] = fixtures
    return out


def power_rankings(teams: dict, results: dict, upto_week: int) -> list[dict]:
    """
    Matt's workbook method, with real points standing in for the projections
    he used to type in: score = ((cumulative wins + own points) / 2) - opponent points,
    averaged over the weeks played so far.
    """
    tally = {rid: {"score": 0.0, "weeks": 0, "wins": 0} for rid in teams}
    for wk in sorted(results):
        if wk > upto_week:
            break
        for fx in results[wk]:
            if fx["home"]["points"] == 0 and fx["away"]["points"] == 0:
                continue
            for side, other in (("home", "away"), ("away", "home")):
                rid = fx[side]["roster_id"]
                if rid not in tally:
                    continue
                mine = fx[side]["points"]
                theirs = fx[other]["points"]
                if mine > theirs:
                    tally[rid]["wins"] += 1
                tally[rid]["score"] += ((tally[rid]["wins"] + mine) / 2) - theirs
                tally[rid]["weeks"] += 1

    rows = []
    for rid, t in tally.items():
        weeks = max(t["weeks"], 1)
        rows.append({**teams[rid], "power": round(t["score"] / weeks, 2), "played": t["weeks"]})
    rows.sort(key=lambda r: r["power"], reverse=True)
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows


# --------------------------------------------------------------------------- #
# page furniture
# --------------------------------------------------------------------------- #
def page(cfg: dict, title: str, active: str, body: str) -> str:
    league = cfg["league"]
    season = cfg["season"]
    stamp = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    nav_items = [
        ("index.html", "Scoreboard"),
        ("standings.html", "Standings"),
        ("teams.html", "Teams"),
        ("history.html", "History"),
    ]
    nav_bits = []
    for href, label in nav_items:
        current_attr = ' aria-current="page"' if label == active else ""
        nav_bits.append(f'<a href="{href}"{current_attr}>{label}</a>')
    nav = "".join(nav_bits)
    return f"""<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} &middot; {e(league['short_name'])}</title>
<meta name="description" content="{e(league['name'])} — {e(cfg['site']['tagline'])}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&family=Public+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<link rel="stylesheet" href="assets/site.css">
</head>
<body>
<header class="masthead">
  <div class="wrap">
    <div class="brand">
      <span class="mark">{e(league['short_name'])}</span>
      <span class="full">{e(league['name'])} &middot; est. {e(league['established'])}</span>
    </div>
    <span class="statuspill"><span class="dot" aria-hidden="true"></span>{e(season['year'])} season</span>
  </div>
</header>
<nav class="sitenav" aria-label="Sections"><div class="wrap">{nav}</div></nav>
<main class="wrap">
{body}
</main>
<footer class="sitefoot">
  <div class="wrap">
    <p>{e(cfg['site']['footer_note'])} Last refreshed {stamp}.</p>
    <p><a href="{e(league['sleeper_url'])}">League on Sleeper</a></p>
  </div>
</footer>
</body>
</html>
"""


def crest(team: dict, cfg: dict) -> str:
    conf = cfg["conferences"].get(team["division"], {})
    short = conf.get("short", "")
    cls = "lc" if team["division"] == "1" else "mc"
    if team.get("image"):
        return f'<img class="crest img" src="assets/teams/{e(team["image"])}" alt="" loading="lazy">'
    return f'<div class="crest {cls}">{e(short)}</div>'


# --------------------------------------------------------------------------- #
# pages
# --------------------------------------------------------------------------- #
def build_scoreboard(cfg, teams, results, week) -> str:
    fixtures = results.get(week, [])
    rows = []
    for fx in fixtures:
        home, away = teams.get(fx["home"]["roster_id"]), teams.get(fx["away"]["roster_id"])
        if not home or not away:
            continue
        hp, ap = fx["home"]["points"], fx["away"]["points"]
        hcls = "lead" if hp >= ap else "trail"
        acls = "lead" if ap >= hp else "trail"
        rows.append(f"""
      <article class="fixture">
        <div class="side home">
          {crest(home, cfg)}
          <div class="who"><div class="team">{e(home['team'])}</div><div class="mgr">{e(home['manager'])}</div></div>
          <div class="score {hcls}">{hp:.2f}</div>
        </div>
        <div class="vs">vs</div>
        <div class="side away">
          {crest(away, cfg)}
          <div class="who"><div class="team">{e(away['team'])}</div><div class="mgr">{e(away['manager'])}</div></div>
          <div class="score {acls}">{ap:.2f}</div>
        </div>
      </article>""")

    if not rows:
        rows = ['<p class="empty">No fixtures published for this week yet.</p>']

    return f"""
  <section>
    <div class="sechead">
      <h2>Week {week}</h2>
      <span class="note">Scores come straight from Sleeper.</span>
    </div>
    <div class="fixtures">{''.join(rows)}</div>
  </section>"""


def standings_table(cfg, teams, division: str) -> str:
    conf = cfg["conferences"].get(division, {})
    cls = "lc" if division == "1" else "mc"
    members = [t for t in teams.values() if t["division"] == division]
    members.sort(key=lambda t: (t["wins"], t["fpts"]), reverse=True)
    body = "".join(
        f"""<tr>
          <td><div class="tm"><span class="nm">{e(t['team'])}</span><span class="hd">{e(t['manager'])}</span></div></td>
          <td class="num">{t['wins']}&ndash;{t['losses']}</td>
          <td class="num">{t['fpts']:,.2f}</td>
          <td class="num">{t['fpts_against']:,.2f}</td>
        </tr>"""
        for t in members
    )
    return f"""
      <div class="conf {cls}">
        <div class="conf-head"><span class="swatch" aria-hidden="true"></span><h3>{e(conf.get('name', 'Conference'))}</h3></div>
        <div class="tablewrap">
          <table>
            <thead><tr><th>Team</th><th>W&ndash;L</th><th>PF</th><th>PA</th></tr></thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </div>"""


def build_standings_section(cfg, teams, heading="Standings") -> str:
    return f"""
  <section>
    <div class="sechead"><h2>{e(heading)}</h2><span class="note">Sorted by record, then points for.</span></div>
    <div class="conf-grid">{standings_table(cfg, teams, '1')}{standings_table(cfg, teams, '2')}</div>
  </section>"""


def build_power_section(cfg, rankings) -> str:
    if not rankings or all(r["played"] == 0 for r in rankings):
        return ""
    top = max(abs(r["power"]) for r in rankings) or 1
    rows = []
    for r in rankings:
        width = max(2, min(100, (r["power"] / top) * 100 if r["power"] > 0 else 2))
        cls = " top" if r["rank"] == 1 else ""
        rows.append(f"""
      <div class="prrow{cls}">
        <div class="prrank num">{r['rank']}</div>
        <div class="prname">{e(r['team'])} <span class="hd">{e(r['manager'])}</span></div>
        <div class="bar"><span style="width:{width:.0f}%"></span></div>
        <div class="prpts">{r['power']:+.1f}</div>
      </div>""")
    return f"""
  <section>
    <div class="sechead"><h2>Power Rankings</h2><span class="note">Your workbook formula, computed on real results.</span></div>
    <div class="pr">
      <div class="prrow prhead"><div class="prrank">#</div><div class="prname">Team</div><div class="bar" style="border:0;background:none"></div><div class="prpts">Score</div></div>
      {''.join(rows)}
    </div>
  </section>"""


def build_honours(cfg) -> str:
    champs = cfg.get("champions", {})
    year = cfg["season"]["year"]
    cards = []
    for season in sorted(set(list(champs) + [str(year)])):
        winner = champs.get(season)
        current = season == str(year) and not winner
        cards.append(f"""
      <div class="yr{' current' if current else ''}">
        <span class="season">{e(season)}</span>
        <span class="winner">{e(winner or '—')}</span>
        <span class="cap">{'In progress' if current else 'Champion'}</span>
      </div>""")
    return f"""
  <section>
    <div class="sechead"><h2>Honours</h2><span class="note">Every champion since {e(cfg['league']['established'])}.</span></div>
    <div class="honours">{''.join(cards)}</div>
  </section>"""


def build_teams_page(cfg, teams, rankings) -> str:
    rank_by = {r["roster_id"]: r["rank"] for r in rankings}
    cards = []
    for t in sorted(teams.values(), key=lambda x: x["team"].lower()):
        conf = cfg["conferences"].get(t["division"], {})
        portrait = (f'<img class="portrait" src="assets/teams/{e(t["portrait"])}" alt="{e(t["manager"])}" loading="lazy">'
                    if t.get("portrait") else "")
        cards.append(f"""
      <article class="teamcard">
        {portrait}
        {crest(t, cfg)}
        <div class="who">
          <div class="team">{e(t['team'])}</div>
          <div class="mgr">{e(t['manager'])} &middot; {e(conf.get('name',''))}</div>
        </div>
        <dl class="teamstats">
          <div><dt>Record</dt><dd class="num">{t['wins']}&ndash;{t['losses']}</dd></div>
          <div><dt>Points for</dt><dd class="num">{t['fpts']:,.0f}</dd></div>
          <div><dt>Power</dt><dd class="num">{rank_by.get(t['roster_id'], '—')}</dd></div>
        </dl>
      </article>""")
    return f"""
  <section>
    <div class="sechead"><h2>Teams</h2><span class="note">Ten franchises, two conferences.</span></div>
    <div class="teamgrid">{''.join(cards)}</div>
  </section>"""


def build_history_page(cfg, history) -> str:
    blocks = []
    for season in history:
        teams = manager_lookup(cfg, season.get("users", []), season.get("rosters", []))
        if not teams:
            continue
        blocks.append(f"""
  <section>
    <div class="sechead"><h2>{e(season.get('season'))} Season</h2><span class="note">Final regular-season standings.</span></div>
    <div class="conf-grid">{standings_table(cfg, teams, '1')}{standings_table(cfg, teams, '2')}</div>
  </section>""")
    return "".join(blocks)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    cfg = json.loads((ROOT / "league.config.json").read_text(encoding="utf-8"))
    current = load("current.json")
    if not current:
        raise SystemExit("data/current.json missing — run scripts/fetch_data.py first")
    state = load("state.json", {}) or {}
    players = load("players.json", {}) or {}
    history = load("history.json", []) or []

    teams = manager_lookup(cfg, current.get("users", []), current.get("rosters", []))
    results = weekly_results(current, players)

    week = int(state.get("week") or 1)
    if str(state.get("season")) != str(current.get("season")):
        week = cfg["season"]["regular_season_weeks"]
    week = max(1, min(week, cfg["season"]["championship_week"]))

    rankings = power_rankings(teams, results, week)

    DOCS.mkdir(parents=True, exist_ok=True)
    if ASSETS.exists():
        shutil.copytree(ASSETS, DOCS / "assets", dirs_exist_ok=True)
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")

    home = build_scoreboard(cfg, teams, results, week) + build_power_section(cfg, rankings) + build_honours(cfg)
    (DOCS / "index.html").write_text(page(cfg, "Scoreboard", "Scoreboard", home), encoding="utf-8")

    (DOCS / "standings.html").write_text(
        page(cfg, "Standings", "Standings", build_standings_section(cfg, teams, f"{cfg['season']['year']} Standings")),
        encoding="utf-8")

    (DOCS / "teams.html").write_text(
        page(cfg, "Teams", "Teams", build_teams_page(cfg, teams, rankings)), encoding="utf-8")

    (DOCS / "history.html").write_text(
        page(cfg, "History", "History", build_honours(cfg) + build_history_page(cfg, history)), encoding="utf-8")

    print(f"Built docs/ for {current.get('season')} week {week}: "
          f"{len(teams)} teams, {len(results)} weeks of results, {len(history)} past seasons.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
