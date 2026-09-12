#!/usr/bin/env python3
"""
Turn data/ + league.config.json into the published site in docs/.

Everything a human might want to change from season to season lives in
league.config.json. Nothing in here needs editing year to year.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import documents as D
import stats as S

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DOCS = ROOT / "docs"
ASSETS = ROOT / "assets"
RECORDS = ASSETS / "records"
RANKINGS = ASSETS / "rankings"


def load(name, default=None):
    path = DATA / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def e(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def slugify(text):
    out = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return out or "team"


def pts(settings, key="fpts"):
    return round((settings.get(key) or 0) + (settings.get(key + "_decimal") or 0) / 100, 2)


def rec(r):
    base = str(r["w"]) + "&ndash;" + str(r["l"])
    return base + "&ndash;" + str(r["t"]) if r.get("t") else base


def sleeper_logo(user, own=None):
    """
    The team logo. The one named for that manager in league.config.json (a file
    in assets/teams/) comes first: Matt's own artwork, whole, for a team whose
    logo Sleeper has squared off - the Raiders lost half their lettering. Then
    the team's own logo in this league on Sleeper, and failing that the
    manager's Sleeper picture. Sleeper's are linked, not copied, so a new one
    there is on the site at the next refresh, unless the config names a logo.
    """
    if own and (ASSETS / "teams" / own).exists():
        return "assets/teams/" + own
    meta = user.get("metadata") or {}
    if meta.get("avatar"):
        return meta["avatar"]
    return "https://sleepercdn.com/avatars/" + user["avatar"] if user.get("avatar") else ""


def manager_lookup(cfg, users, rosters):
    by_user = {u["user_id"]: u for u in users}
    out = {}
    for r in rosters:
        uid = r.get("owner_id")
        user = by_user.get(uid, {})
        conf = (cfg.get("managers") or {}).get(uid, {})
        meta = user.get("metadata") or {}
        st = r.get("settings") or {}
        team = (meta.get("team_name") or user.get("display_name") or "Unnamed").strip()
        out[r["roster_id"]] = {
            "roster_id": r["roster_id"], "user_id": uid,
            "manager": conf.get("name") or user.get("display_name") or "Unknown",
            "team": team, "slug": slugify(team),
            # The AI pictures are for the Scoreboard only; everywhere else has the team logo.
            "image": conf.get("image"), "portrait": conf.get("portrait"),
            "logo": sleeper_logo(user, conf.get("logo")),
            "division": str(st.get("division") or "1"),
            "wins": st.get("wins", 0), "losses": st.get("losses", 0), "ties": st.get("ties", 0),
            "fpts": pts(st, "fpts"), "fpts_against": pts(st, "fpts_against"),
        }
    return out


def weekly_results(season, players):
    positions = season.get("roster_positions", [])
    out = {}
    for wk, entries in (season.get("matchups") or {}).items():
        pairs = {}
        for entry in entries:
            if entry.get("matchup_id") is not None:
                pairs.setdefault(entry["matchup_id"], []).append(entry)
        fixtures = []
        for mid, sides in sorted(pairs.items()):
            if len(sides) != 2:
                continue
            a, b = sides
            fixtures.append({
                "home": {"roster_id": a["roster_id"], "points": round(float(a.get("points") or 0), 2),
                         "optimal": S.optimal_points(a.get("players_points"), positions, players)},
                "away": {"roster_id": b["roster_id"], "points": round(float(b.get("points") or 0), 2),
                         "optimal": S.optimal_points(b.get("players_points"), positions, players)},
            })
        out[int(wk)] = fixtures
    return out


POWER_FILE = "power_rankings.json"


def power_store(cfg, current, season, projections, players, state, now=None):
    """
    Every week's power ranking as it was fixed. A week is settled at noon UK on
    the Wednesday before its games and never moves again, however the
    projections shift afterwards, so each one is written to
    data/power_rankings.json the first time a build runs past that moment and
    left alone from then on. The file holds one season; it starts again by
    itself when the league rolls over.
    """
    now = now or datetime.now(timezone.utc)
    year = str(current.get("season"))
    store = load(POWER_FILE, {}) or {}
    if str(store.get("season")) != year:
        store = {"season": year, "weeks": {}}
    weeks = store.setdefault("weeks", {})
    changed = False
    for wk in range(1, cfg["season"]["regular_season_weeks"] + 1):
        if str(wk) in weeks:
            continue
        if now < S.power_freeze(int(year), wk, state):
            break
        rows = S.power_rankings(current, season, projections, players, wk)
        if not rows:
            # Sleeper only projects weeks still to come, so a week missed at the
            # time can never be filled in. The next one carries on regardless.
            continue
        weeks[str(wk)] = {
            "fixed": now.replace(microsecond=0).isoformat(),
            "source": "projections",
            "teams": {r["owner_id"]: {k: r[k] for k in ("rank", "score", "proj", "opp_proj")}
                      for r in rows if r["owner_id"]},
        }
        changed = True
    if changed:
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / POWER_FILE).write_text(json.dumps(store, indent=1, sort_keys=True),
                                       encoding="utf-8")
    return store


def power_table(store, teams):
    """
    The week showing on the Scoreboard: the last one fixed, and how far each
    team has moved since the week fixed before it. None until a week is fixed.
    """
    fixed = sorted((int(w) for w in (store.get("weeks") or {})), reverse=True)
    if not fixed:
        return None
    week, before = fixed[0], {}
    if len(fixed) > 1:
        before = (store["weeks"][str(fixed[1])].get("teams") or {})
    by_owner = {t["user_id"]: t for t in teams.values()}
    rows = []
    for uid, row in (store["weeks"][str(week)].get("teams") or {}).items():
        if uid not in by_owner:
            continue
        was = (before.get(uid) or {}).get("rank")
        rows.append(dict(by_owner[uid], rank=row["rank"],
                         move=None if not was else was - row["rank"]))
    if not rows:
        return None
    rows.sort(key=lambda r: r["rank"])
    return {"week": week, "rows": rows, "since": fixed[1] if len(fixed) > 1 else None,
            "source": store["weeks"][str(week)].get("source")}


NAV = [("index.html", "Scoreboard"), ("standings.html", "Standings"), ("teams.html", "Teams"),
       ("calendar.html", "Calendar"), ("updates.html", "Commissioner Updates"),
       ("trades.html", "Trade Centre"), ("history.html", "History"),
       ("records.html", "Records"), ("rules.html", "Rules")]


def page(cfg, title, active, body):
    league, season = cfg["league"], cfg["season"]
    stamp = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    bits = []
    for href, label in NAV:
        attr = ' aria-current="page"' if label == active else ""
        bits.append('<a href="' + href + '"' + attr + '>' + label + "</a>")
    # The league logo is THE logo: shown exactly as Matt made it, white ground and all.
    logo = league.get("logo")
    if logo and (ASSETS / "league" / logo).exists():
        mark = ('<a class="leaguelogo" href="index.html"><img src="assets/league/' + e(logo)
                + '" alt="' + e(league["name"]) + '"></a>')
    else:
        mark = '<a class="mark" href="index.html">' + e(league["short_name"]) + "</a>"
    return f"""<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} &middot; {e(league['short_name'])}</title>
<meta name="description" content="{e(league['name'])} &mdash; {e(cfg['site']['tagline'])}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Roboto+Slab:wght@600;700;800;900&family=Public+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<link rel="stylesheet" href="assets/site.css">
</head>
<body>
<header class="masthead">
  <div class="wrap">
    <p class="leaguename">{e(league['name'])}<small>{e(cfg['site']['tagline'])}</small></p>
    {mark}
    <span class="statuspill"><span class="dot" aria-hidden="true"></span>{e(season['year'])} season</span>
  </div>
</header>
<nav class="sitenav" aria-label="Sections"><div class="wrap">{''.join(bits)}</div></nav>
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


def shot(team, cfg):
    """
    The manager's AI picture on the Scoreboard, whole and large: Matt makes a new
    set every season and the detail is the point. Some are landscape and some
    portrait, so each sits uncropped in a 3:2 frame, over a blurred copy of
    itself that fills whatever it leaves, and opens full size when clicked. The
    square crest crop is the fallback.
    """
    pic = next((p for p in (team.get("portrait"), team.get("image"))
                if p and (ASSETS / "teams" / p).exists()), None)
    if not pic:
        conf = cfg["conferences"].get(team["division"], {})
        cls = "lc" if team["division"] == "1" else "mc"
        return '<div class="shot none ' + cls + '"><span>' + e(conf.get("short", "")) + "</span></div>"
    src = "assets/teams/" + e(pic)
    return ('<a class="shot" href="' + src + '" title="Open full size">'
            '<img class="blur" src="' + src + '" alt="" aria-hidden="true" loading="lazy">'
            '<img class="pic" src="' + src + '" alt="' + e(team["manager"] + ", " + team["team"])
            + '" loading="lazy"></a>')


def sechead(title, note=""):
    extra = '<span class="note">' + e(note) + "</span>" if note else ""
    return '<div class="sechead"><h2>' + e(title) + "</h2>" + extra + "</div>"


def ordinal(n):
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return str(n) + suffix


def conference_places(cfg, teams):
    """roster_id -> 'LFC 1st', as the old site showed on every fixture."""
    out = {}
    for division in cfg["conferences"]:
        members = sorted((t for t in teams.values() if t["division"] == division),
                         key=lambda t: (t["wins"], t["fpts"]), reverse=True)
        short = cfg["conferences"][division].get("short", "")
        for place, team in enumerate(members, 1):
            out[team["roster_id"]] = short + " " + ordinal(place)
    return out


def featured_name(cfg, week, home, away, prev_finish):
    """
    The one inter-conference game in a divisional week, named after the place both
    teams finished in their own conference last season. Matt schedules these by
    hand, so we only recognise a pairing that really is rank-against-rank.
    """
    dw = cfg.get("divisional_weeks") or {}
    if not (dw.get("from_week", 0) <= week <= dw.get("to_week", -1)):
        return ""
    if home["division"] == away["division"]:
        return ""
    here, there = prev_finish.get(home["user_id"]), prev_finish.get(away["user_id"])
    if not here or not there or here[1] != there[1]:
        return ""
    return (dw.get("names") or {}).get(str(here[1]), "")


def week_heading(cfg, week):
    rounds = {str(k): v for k, v in (cfg.get("playoff_rounds") or {}).items()
              if not str(k).startswith("_")}
    return rounds.get(str(week)) or ("Week " + str(week))


def is_divisional_week(cfg, week):
    dw = cfg.get("divisional_weeks") or {}
    return dw.get("from_week", 0) <= week <= dw.get("to_week", -1)


def conf_band(cfg, division):
    """
    The conference header that separates the two blocks in a divisional week.
    The crest carries the conference name, so it does the labelling; the stars on
    it are championships won by the managers currently in that conference.
    """
    conf = cfg["conferences"].get(division, {})
    cls = "lc" if division == "1" else "mc"
    crest_file = conf.get("crest")
    name = conf.get("name", "Conference")
    if crest_file:
        mark = ('<img class="conflogo" src="assets/conferences/' + e(crest_file)
                + '" alt="' + e(name) + '" loading="lazy">')
    else:
        mark = "<h3>" + e(name) + "</h3>"
    return '<div class="confband ' + cls + '">' + mark + "</div>"


def chance(p):
    """A simulated chance as a percentage. Never 0% or 100%: a simulation is not a proof."""
    if p < 0.005:
        return "&lt;1%"
    if p > 0.995:
        return "&gt;99%"
    return f"{p * 100:.0f}%"


def odds_line(odds, team):
    """Playoff and bye chances under a team on the Scoreboard, while there is a race."""
    o = (odds or {}).get("teams", {}).get(team["user_id"])
    if not o:
        return ""
    return (f'<div class="odds">Playoffs <b>{chance(o["playoffs"])}</b> &middot; '
            f'Bye <b>{chance(o["bye"])}</b></div>')


def odds_section(cfg, teams, odds):
    """
    The playoff odds table, a conference at a time: each team's chance of the
    playoffs, of the bye that goes with winning the conference, and of the
    toilet bowl, from stats.playoff_odds. Only while regular-season games remain.
    """
    if not odds:
        return ""
    labels = (cfg.get("side_competitions") or {}).get("labels", {})
    blocks = []
    for division in sorted(cfg["conferences"]):
        conf = cfg["conferences"][division]
        cls = "lc" if division == "1" else "mc"
        members = [t for t in teams.values() if t["division"] == division and t["user_id"] in odds["teams"]]
        members.sort(key=lambda t: (-odds["teams"][t["user_id"]]["playoffs"], -odds["teams"][t["user_id"]]["bye"],
                                    -odds["teams"][t["user_id"]]["wins"]))
        rows = []
        for t in members:
            o = odds["teams"][t["user_id"]]
            rows.append(f"""<tr>
        <td><div class="tm"><span class="nm"><a href="team-{e(t['slug'])}.html">{e(t['team'])}</a></span><span class="hd">{e(t['manager'])}</span></div></td>
        <td class="num">{rec(o)}</td>
        <td class="num">{o['wins']:.1f}</td>
        <td class="num pct"><span class="pbar" style="--p:{o['playoffs'] * 100:.1f}%"></span>{chance(o['playoffs'])}</td>
        <td class="num">{chance(o['bye'])}</td>
        <td class="num">{chance(o['toilet'])}</td></tr>""")
        blocks.append(f"""
      <div class="conf {cls}">
        <div class="conf-head"><span class="swatch" aria-hidden="true"></span><h3>{e(conf.get('name', 'Conference'))}</h3></div>
        <div class="tablewrap"><table>
          <thead><tr><th>Team</th><th>W&ndash;L</th><th title="Average wins at the end of the regular season">Proj. W</th><th>Playoffs</th><th title="Winning the conference: a bye to the Conference Championships">Bye</th><th>{e(labels.get('consolation', 'Toilet Bowl'))}</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table></div>
      </div>""")
    weeks = odds["weeks_left"]
    note = (f"The {weeks} regular-season week{'s' if weeks != 1 else ''} left, played out {odds['sims']:,} times. "
            "Each team's expected score is Sleeper's projection for its best lineup from the players it can start, "
            "nudged towards its own results this season as the games come in. Past seasons only set how much any "
            f"team's scores move about: roughly {odds['swing']:.0f} points either way in a week, and "
            f"{odds['doubt']:.0f} a week over a whole season. A team's own history is left out, since this year's "
            "roster may be a different team. Places go by the rulebook: the conference winners get the bye, second "
            "place is in, and third is in unless Rule 3 applies.")
    if odds["weeks_projected"] < weeks:
        missing = weeks - odds["weeks_projected"]
        note += (f" Sleeper had no projections for {missing} of those week{'s' if missing != 1 else ''}, "
                 "so they use each team's scoring average instead.")
    return ("<section>" + sechead("Playoff odds", "Updated with every refresh.")
            + '<div class="conf-grid oddsgrid">' + "".join(blocks) + "</div>"
            + '<p class="oddsnote">' + e(note) + "</p></section>")


def scoreboard(cfg, teams, results, week, career, prev_finish, odds=None):
    rows = []
    places = conference_places(cfg, teams)
    for fx in results.get(week, []):
        home, away = teams.get(fx["home"]["roster_id"]), teams.get(fx["away"]["roster_id"])
        if not home or not away:
            continue
        hp, ap = fx["home"]["points"], fx["away"]["points"]
        billing = featured_name(cfg, week, home, away, prev_finish)
        # Conference-era regular season only. BCE was a different league shape and
        # Matt does not want it folded into the head-to-head shown on a fixture.
        h2h = ""
        hs = career.get(home["user_id"])
        if hs:
            against = hs["h2h"].get(away["user_id"])
            if against:
                w, l = against["conference"]["w"], against["conference"]["l"]
                if w or l:
                    h2h = ('<div class="h2hline">Since ' + e(cfg["eras"]["conference_from"])
                           + " &middot; " + str(w) + "&ndash;" + str(l) + "</div>")
        marquee = ('<div class="billing">' + e(billing) + "</div>") if billing else ""
        # "featured" for the inter-conference game, otherwise the division both
        # sides share. Used to group the week into LFC and MFC blocks.
        group = "featured" if billing else (
            home["division"] if home["division"] == away["division"] else "mixed")
        rows.append((group, f"""
      <article class="fixture{' featured' if billing else ''}">
        {marquee}
        <div class="side home">
          {shot(home, cfg)}
          <div class="line">
            <div class="who">
              <div class="team"><a href="team-{e(home['slug'])}.html">{e(home['team'])}</a></div>
              <div class="mgr">{e(home['manager'])} &middot; {home['wins']}&ndash;{home['losses']} &middot; {e(places.get(home['roster_id'], ''))}</div>
              {odds_line(odds, home)}
            </div>
            <div class="score {'lead' if hp >= ap else 'trail'}">{hp:.2f}</div>
          </div>
        </div>
        <div class="vs">vs{h2h}</div>
        <div class="side away">
          {shot(away, cfg)}
          <div class="line">
            <div class="who">
              <div class="team"><a href="team-{e(away['slug'])}.html">{e(away['team'])}</a></div>
              <div class="mgr">{e(away['manager'])} &middot; {away['wins']}&ndash;{away['losses']} &middot; {e(places.get(away['roster_id'], ''))}</div>
              {odds_line(odds, away)}
            </div>
            <div class="score {'lead' if ap >= hp else 'trail'}">{ap:.2f}</div>
          </div>
        </div>
      </article>"""))

    if not rows:
        inner = '<p class="empty">No fixtures published for this week yet.</p>'
    elif is_divisional_week(cfg, week):
        # The named game leads, then the two conferences under their own headers.
        blocks = ["".join(html for group, html in rows if group == "featured")]
        for division in sorted(cfg["conferences"]):
            games = [html for group, html in rows if group == division]
            if games:
                blocks.append(conf_band(cfg, division) + "".join(games))
        leftovers = [html for group, html in rows if group == "mixed"]
        inner = "".join(blocks) + "".join(leftovers)
    else:
        inner = "".join(html for _group, html in rows)

    return ("<section>" + sechead(week_heading(cfg, week), "Scores and records straight from Sleeper.")
            + '<div class="fixtures">' + inner + "</div></section>")


def standings_table(cfg, teams, division):
    conf = cfg["conferences"].get(division, {})
    cls = "lc" if division == "1" else "mc"
    members = sorted((t for t in teams.values() if t["division"] == division),
                     key=lambda t: (t["wins"], t["fpts"]), reverse=True)
    body = "".join(f"""<tr>
        <td><div class="tm"><span class="nm"><a href="team-{e(t['slug'])}.html">{e(t['team'])}</a></span><span class="hd">{e(t['manager'])}</span></div></td>
        <td class="num">{t['wins']}&ndash;{t['losses']}</td>
        <td class="num">{t['fpts']:,.2f}</td>
        <td class="num">{t['fpts_against']:,.2f}</td></tr>""" for t in members)
    return f"""
      <div class="conf {cls}">
        <div class="conf-head"><span class="swatch" aria-hidden="true"></span><h3>{e(conf.get('name','Conference'))}</h3></div>
        <div class="tablewrap"><table>
          <thead><tr><th>Team</th><th>W&ndash;L</th><th>PF</th><th>PA</th></tr></thead>
          <tbody>{body}</tbody>
        </table></div>
      </div>"""


def standings_section(cfg, teams, heading):
    return ("<section>" + sechead(heading, "Sorted by record, then points for.")
            + '<div class="conf-grid">' + standings_table(cfg, teams, "1")
            + standings_table(cfg, teams, "2") + "</div></section>")


def move_chip(move):
    """How far a team has moved since the week before, as an arrow."""
    if move is None:
        return '<span class="move new">&mdash;</span>'
    if move > 0:
        return '<span class="move up">&#9650;&#8202;' + str(move) + "</span>"
    if move < 0:
        return '<span class="move down">&#9660;&#8202;' + str(-move) + "</span>"
    return '<span class="move level">&ndash;</span>'


def power_section(cfg, table):
    if not table:
        return ""
    # The workbook formula stays off the site: Matt's own, and not for publishing.
    note = "Week " + str(table["week"]) + " — fixed at noon on Wednesday."
    rows = []
    for r in table["rows"]:
        rows.append(f"""
      <div class="prrow{' top' if r['rank'] == 1 else ''}">
        <div class="prrank num">{r['rank']}</div>
        <div class="prname"><a href="team-{e(r['slug'])}.html">{e(r['team'])}</a> <span class="hd">{e(r['manager'])}</span></div>
        <div class="prmove">{move_chip(r['move'])}</div>
      </div>""")
    return ("<section>" + sechead("Power Rankings", note)
            + '<div class="pr"><div class="prrow prhead"><div class="prrank">#</div>'
            + '<div class="prname">Team</div><div class="prmove">Move</div></div>'
            + "".join(rows) + "</div></section>")


def placed(season, place):
    """Whoever finished in `place` once the placement games were played, or None."""
    return next((uid for uid, p in season["final"].items() if p == place), None)


# --------------------------------------------------------------------------- #
# the off-season Scoreboard
# --------------------------------------------------------------------------- #
# Between the final and kickoff there are no fixtures, no playoff odds and no
# power rankings, and the front page used to go on showing the last week of the
# season as though it were still being played. In their place it looks back at
# the season just gone and forward to the next one.
def in_days(when, today):
    """"Today", "Tomorrow", "In 23 days" - or None once the day is past."""
    gap = (when - today).days
    if gap < 0:
        return None
    return {0: "Today", 1: "Tomorrow"}.get(gap, "In " + str(gap) + " days")


def day_words(day):
    return str(day.day) + day.strftime(" %B %Y")


def next_draft(current):
    """The rookie draft still to come in the season now on, or None."""
    year = str(current.get("season"))
    drafts = [d for d in current.get("drafts") or []
              if str(d.get("season")) == year and d.get("status") != "complete"
              and d.get("start_time")]
    return min(drafts, key=lambda d: d["start_time"], default=None)


def up_next(cfg, current, state, today=None):
    """
    What the league is waiting for: the rookie draft and kickoff, with the days
    to each. Empty once both are behind us.
    """
    today = today or datetime.now(timezone.utc).date()
    year = int(current.get("season") or 0)
    dates = []
    draft = next_draft(current)
    if draft:
        when = datetime.fromtimestamp(draft["start_time"] / 1000, timezone.utc).date()
        rounds = draft.get("rounds")
        dates.append(("Rookie draft", when, (str(rounds) + " rounds") if rounds else ""))
    if year:
        dates.append(("Kickoff", S.kickoff(year, state), "Week 1 of " + str(year)))
    cards = []
    for label, when, note in dates:
        away = in_days(when, today)
        if not away:
            continue
        cards.append(f"""
      <div class="upnext">
        <span class="uplabel">{e(label)}</span>
        <span class="upwhen">{e(day_words(when))}</span>
        <span class="upaway">{e(away)}</span>
        <span class="upnote">{e(note)}</span>
      </div>""")
    if not cards:
        # The season is settled and Matt has not created the next one on Sleeper
        # yet, so there is no draft date and no kickoff to count down to.
        if not year:
            return ""
        return ("<section>" + sechead("Next up")
                + '<p class="empty">The ' + e(year + 1) + " season is not up on Sleeper yet. "
                + "As soon as it is, the site will follow it.</p></section>")
    return ("<section>" + sechead("Next up", "Counting down to the new season.")
            + '<div class="upgrid">' + "".join(cards) + "</div></section>")


def draft_class_section(cfg, current, names):
    """The rookie draft just made, pick by pick. Nothing until it has been."""
    year = str(current.get("season"))
    picks = []
    for draft in current.get("drafts") or []:
        if str(draft.get("season")) == year and draft.get("status") == "complete":
            owner = {r["roster_id"]: r.get("owner_id") for r in current.get("rosters") or []}
            teams = draft.get("teams") or 10
            for p in sorted(draft.get("picks") or [], key=lambda p: p.get("pick_no") or 0):
                if not p.get("round") or not p.get("pick_no"):
                    continue
                picks.append((f"{p['round']}.{p['pick_no'] - (p['round'] - 1) * teams:02d}",
                              p.get("name") or "&mdash;", p.get("position") or "",
                              names.get(owner.get(p.get("roster_id"))) or "Unknown"))
    if not picks:
        return ""
    rows = "".join(f'<tr><td class="num">{e(no)}</td><td><div class="tm"><span class="nm">{e(who)}'
                   f'</span></div></td><td>{e(pos)}</td><td>{e(by)}</td></tr>'
                   for no, who, pos, by in picks)
    return ("<section>" + sechead(year + " Rookie Draft", "Every pick, in order.")
            + '<div class="finishes">'
            + finish_card("The class of " + year, "As drafted.",
                          "<th>Pick</th><th>Player</th><th>Pos</th><th>Drafted by</th>", [rows])
            + "</div></section>")


# --------------------------------------------------------------------------- #
# the Pro Bowl
# --------------------------------------------------------------------------- #
# Once a year the two conferences put an all-star side out against each other,
# captained by last season's conference winners and drawn from the players their
# conference holds. The captains pick; everything else here is computed. The
# picks come from Matt's Google Sheet (data/probowl.json, fetched) or from
# assets/probowl/<season>.json, which overrides it.
PROBOWL = ASSETS / "probowl"

# Sleeper files a defence under its team's code and keeps no name for it, so a
# sheet saying "Rams" needs this to find LAR.
NFL_NICKNAMES = {
    "cardinals": "ARI", "falcons": "ATL", "ravens": "BAL", "bills": "BUF", "panthers": "CAR",
    "bears": "CHI", "bengals": "CIN", "browns": "CLE", "cowboys": "DAL", "broncos": "DEN",
    "lions": "DET", "packers": "GB", "texans": "HOU", "colts": "IND", "jaguars": "JAX",
    "chiefs": "KC", "chargers": "LAC", "rams": "LAR", "raiders": "LV", "dolphins": "MIA",
    "vikings": "MIN", "patriots": "NE", "saints": "NO", "giants": "NYG", "jets": "NYJ",
    "eagles": "PHI", "steelers": "PIT", "seahawks": "SEA", "49ers": "SF", "niners": "SF",
    "buccaneers": "TB", "bucs": "TB", "titans": "TEN", "commanders": "WAS",
}


def name_key(text):
    """A name flattened for matching: lower case, letters and digits only."""
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def conference_pool(current, teams, division):
    """Every player held by a team in one conference, and how to find him by name."""
    pool = set()
    for r in current.get("rosters") or []:
        team = teams.get(r["roster_id"])
        if team and team["division"] == division:
            pool.update(r.get("players") or [])
    return pool


# What a slot can be filled by, so the slot itself helps place a short name.
SLOT_POSITIONS = {
    "QB": {"QB"}, "RB": {"RB"}, "WR": {"WR"}, "TE": {"TE"}, "K": {"K"},
    "DST": {"DEF"}, "DEF": {"DEF"}, "D": {"DEF"},
    "FLEX": {"RB", "WR", "TE"},
    "SUPERFLEX": {"QB", "RB", "WR", "TE"}, "SF": {"QB", "RB", "WR", "TE"},
}


def squad_index(pool, players):
    """
    Every way a player in the pool might be written - his full name, his
    surname, his first name, his initial-and-surname, and everything after his
    first name for the likes of St. Brown - each pointing at all the men it
    could mean. Narrowing that to one is find_player's job.
    """
    by_name, defences = defaultdict(set), {}
    for pid in pool:
        info = players.get(pid) or {}
        if info.get("position") == "DEF":
            defences[(info.get("team") or pid).upper()] = pid
            continue
        name = (info.get("full_name") or "").strip()
        if not name:
            continue
        keys, parts = {name_key(name)}, name.split()
        if len(parts) > 1:
            keys |= {name_key(parts[-1]), name_key(parts[0]),
                     name_key(parts[0][0] + parts[-1]), name_key("".join(parts[1:]))}
        for key in keys - {""}:
            by_name[key].add(pid)
    return by_name, defences


def find_player(written, index, aliases, slot, players, projected):
    """
    The player a sheet entry means, as (id, how sure). Names in the sheet are
    short - a surname, a nickname, sometimes an initialism - so candidates are
    narrowed three ways: only players that conference actually holds, then only
    those who can fill the slot, and if more than one is still standing, the one
    projected to score most that week. The Madden conference holds five Allens;
    only one of them is a quarterback.

    "how" is "sure" when the name pointed at one man, "slot" when the slot
    settled it, and "guess" when it came down to the projection.
    """
    by_name, defences = index
    allowed = SLOT_POSITIONS.get(re.sub(r"[^A-Z]", "", str(slot or "").upper()))
    for attempt in (written, aliases.get(written.strip()) or ""):
        key = name_key(attempt)
        if not key:
            continue
        code = NFL_NICKNAMES.get(key)
        if code is None and attempt.strip().upper() in defences:
            code = attempt.strip().upper()
        if code in defences:
            return defences[code], "sure"
        found = set(by_name.get(key) or ())
        if not found:
            continue
        if len(found) == 1:
            return found.pop(), "sure"
        if allowed:
            found = {p for p in found if (players.get(p) or {}).get("position") in allowed} or found
        if len(found) == 1:
            return found.pop(), "slot"
        return max(found, key=lambda p: float(projected.get(p) or 0)), "guess"
    return None, None


def thanksgiving(year):
    """The fourth Thursday in November."""
    return nth_weekday(year, 11, 3, 4)


def pro_bowl_week(cfg, year, state):
    """
    The week the Pro Bowl is played in: Thanksgiving week, which is the football
    week Thanksgiving itself falls in. None if it falls outside the season.
    """
    day = thanksgiving(year)
    for week in range(1, cfg["season"]["regular_season_weeks"] + 1):
        wednesday = S.week_wednesday(year, week, state)
        if wednesday <= day < wednesday + timedelta(days=7):
            return week
    return None


def load_squads(season):
    """
    The Pro Bowl picks. A file in assets/probowl/ wins, so Matt can correct the
    sheet or work without one; otherwise whatever was last read from the sheet.
    """
    own = PROBOWL / (str(season) + ".json")
    if own.exists():
        try:
            return json.loads(own.read_text(encoding="utf-8"))
        except ValueError:
            pass
    got = load("probowl.json")
    return got if got and str(got.get("season")) == str(season) else None


def pro_bowl(cfg, current, teams, players, projections, prev_finish, state, today=None):
    """
    The Pro Bowl as it stands: each named slot with its man, what he is
    projected to score and what he has scored. Points come from the week's own
    matchups, since every player in it is on somebody's roster. None when there
    is nothing to show - no picks in yet, or no Thanksgiving week this season.
    """
    year = cfg["season"]["year"]
    week = pro_bowl_week(cfg, year, state)
    squads = load_squads(year)
    if not week or not squads or not squads.get("picks"):
        return None
    # The sheet holds whatever was last played until Matt starts this year's, so
    # nothing shows until the week before Thanksgiving week. That is lead-in
    # enough for early picks without last year's game sitting on the front page
    # all season.
    today = today or datetime.now(timezone.utc).date()
    if today < S.week_wednesday(year, max(1, week - 1), state):
        return None

    divisions = sorted(cfg["conferences"])
    aliases = (cfg.get("pro_bowl") or {}).get("aliases") or {}
    index = [squad_index(conference_pool(current, teams, d), players) for d in divisions]

    projected = ((projections or {}).get("weeks") or {}).get(str(week)) or {}
    if str((projections or {}).get("season")) != str(year):
        projected = {}
    scored = {}
    for entry in (current.get("matchups") or {}).get(str(week)) or []:
        scored.update(entry.get("players_points") or {})

    rows, missing, guessed = [], [], []
    totals = [{"proj": 0.0, "points": 0.0} for _ in divisions]
    for pick in squads["picks"]:
        slot, side = pick.get("slot") or "", []
        for i, written in enumerate(pick.get("players") or []):
            if i >= len(divisions):
                break
            written = (written or "").strip()
            if not written:
                side.append(None)
                continue
            pid, how = find_player(written, index[i], aliases, slot, players, projected)
            name = (players.get(pid) or {}).get("full_name") if pid else None
            if not pid:
                missing.append(written)
            elif how == "guess":
                guessed.append(written + " → " + (name or pid))
            proj = round(float(projected.get(pid) or 0), 2) if pid else 0.0
            pts = round(float(scored.get(pid) or 0), 2) if pid else 0.0
            totals[i]["proj"] += proj
            totals[i]["points"] += pts
            side.append({"written": written, "name": name or written, "found": bool(pid),
                         "proj": proj, "points": pts})
        rows.append({"slot": slot, "side": side})

    if not any(p for row in rows for p in row["side"]):
        return None
    # Nobody has played yet until somebody scores, and a column of 0.00s before
    # kickoff says nothing. Until then the projection is the figure that counts.
    live = any(t["points"] for t in totals)
    captains = {}
    for uid, (division, place) in (prev_finish or {}).items():
        if place == 1:
            captains[division] = uid
    return {
        "week": week, "day": thanksgiving(year), "divisions": divisions, "rows": rows, "live": live,
        "totals": [{k: round(v, 2) for k, v in t.items()} for t in totals],
        "captains": captains, "missing": sorted(set(missing)), "guessed": sorted(set(guessed)),
        "title": ((cfg.get("pro_bowl") or {}).get("titles") or {}).get(str(year)) or "JADL Pro Bowl",
    }


def pro_bowl_section(cfg, game, names):
    """The Pro Bowl on the Scoreboard, laid out as Matt's sheet has it."""
    if not game:
        return ""
    heads = []
    for i, division in enumerate(game["divisions"]):
        conf = cfg["conferences"].get(division, {})
        cls = "lc" if division == "1" else "mc"
        captain = names.get(game["captains"].get(division))
        total = game["totals"][i]
        big = total["points"] if game["live"] else total["proj"]
        under = (f"{total['proj']:.2f} projected") if game["live"] else "projected"
        heads.append(f"""
        <div class="pbside {cls}">
          <span class="pbconf">{e(conf.get('short') or conf.get('name') or '')}</span>
          <span class="pbcap">{e(captain + ' (c)') if captain else '&mdash;'}</span>
          <span class="pbtotal num">{big:.2f}</span>
          <span class="pbproj num">{under}</span>
        </div>""")

    lines = []
    for row in game["rows"]:
        cells = []
        for i, man in enumerate(row["side"]):
            if man is None:
                who, pts, proj = '<span class="pbtbn">To be named</span>', "", ""
            else:
                who = e(man["name"])
                if not man["found"]:
                    who = ('<span class="pbunknown" title="Not matched to a Sleeper player">'
                           + e(man["written"]) + "</span>")
                pts = f"{man['points']:.2f}" if game["live"] else ""
                proj = f"{man['proj']:.2f}"
            cells.append((who, pts, proj))
        left, right = (cells + [("", "", "")] * 2)[:2]
        lines.append(f"""
        <li class="pbrow">
          <span class="pbname l">{left[0]}</span>
          <span class="pbproj num l">{left[2]}</span>
          <span class="pbpts num l">{left[1]}</span>
          <span class="pbslot">{e(row['slot'])}</span>
          <span class="pbpts num r">{right[1]}</span>
          <span class="pbproj num r">{right[2]}</span>
          <span class="pbname r">{right[0]}</span>
        </li>""")

    note = ("Thanksgiving week &middot; Week " + str(game["week"]) + ". Last season's conference "
            "winners captain a side drawn from their own conference.")
    return ("<section>" + sechead(game["title"], "") + '<div class="pb">'
            + '<div class="pbhead">' + heads[0] + '<div class="pbvs">v</div>' + heads[1] + "</div>"
            + '<ol class="pbslots">' + "".join(lines) + "</ol>"
            + '<p class="oddsnote">' + note + "</p></div></section>")


# --------------------------------------------------------------------------- #
# the Calendar
# --------------------------------------------------------------------------- #
# The old site's Calendar page, computed. Every date the league keeps follows
# from Sleeper's season start, its playoff weeks and its rookie draft, so the
# only dates in league.config.json are the two Sleeper cannot know: the Pro Bowl
# and the AGM. Dates are British, as Matt has always listed them - the NFL's
# Thursday night is our Friday morning.
def nth_weekday(year, month, weekday, n):
    """The nth given weekday of a month. Monday is 0."""
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def span_words(start, end=None):
    """'17 August 2026', or '18 – 22 December 2026' with the month said once."""
    if not end or end == start:
        return day_words(start)
    if (start.month, start.year) == (end.month, end.year):
        return str(start.day) + "&ndash;" + day_words(end)
    if start.year == end.year:
        return str(start.day) + start.strftime(" %B") + " &ndash; " + day_words(end)
    return day_words(start) + " &ndash; " + day_words(end)


def season_calendar(cfg, year, current, state):
    """
    One season's calendar, in date order: (date, end date or None, prefix,
    title, [notes]). The season is the year it is played in, so the playoffs
    and the post-season that spill into January belong to the year before them,
    exactly as the old page had it.
    """
    cal = cfg.get("calendar") or {}
    notes = cal.get("notes") or {}
    shape = cfg["season"]
    settings = current.get("settings") or {}
    events = []

    def add(when, title, key=None, end=None, prefix="", extra=()):
        if when:
            events.append((when, end, prefix, title, list(extra) + list(notes.get(key) or [])))

    # The Pro Bowl: Thanksgiving week. It starts a day before an ordinary week,
    # because the Thanksgiving games kick off in the afternoon over there, which
    # is still Thursday evening here.
    bowl = pro_bowl_week(cfg, year, state)
    if bowl:
        _opens, closes = S.week_window(year, bowl, state)
        add(thanksgiving(year), ((cfg.get("pro_bowl") or {}).get("titles") or {}).get(str(year))
            or "JADL Pro Bowl", "pro_bowl", end=closes,
            extra=["Thanksgiving week, week " + str(bowl) + "."])

    agm = (cal.get("meeting") or {}).get(str(year)) or {}
    if agm.get("on"):
        title = "JADL " + str(year) + " Meeting"
        if agm.get("qualifier"):
            title += " (" + agm["qualifier"] + ")"
        add(date.fromisoformat(agm["on"]), title, "meeting")

    # The rookie draft, from Sleeper once the league for that season exists.
    draft = next((d for d in current.get("drafts") or [] if str(d.get("season")) == str(year)
                  and d.get("start_time")), None)
    if draft:
        day = datetime.fromtimestamp(draft["start_time"] / 1000, timezone.utc).date()
        add(day - timedelta(days=1), "Roster space for the rookie draft", "draft_prep", prefix="By")
        rounds = draft.get("rounds") or (settings.get("draft_rounds") or 0)
        add(day, "Rookie Draft", extra=[str(rounds) + " rounds."] if rounds else ())

    # The pre-season: the auction, the roster deadline and the first waivers.
    add(nth_weekday(year, 8, 0, 3), "Free Agency Auction", prefix="w/c")
    squad = len([p for p in current.get("roster_positions") or [] if p not in ("IR", "TAXI")])
    shapes = []
    if squad:
        shapes.append("Rosters are set for the season at " + str(squad)
                      + ", with " + str(settings.get("reserve_slots") or 0) + " IR spots and "
                      + str(settings.get("taxi_slots") or 0) + " taxi spots.")
    add(date(year, 9, 1), str(year) + " Season Roster Deadline", "roster_deadline", extra=shapes)

    first = S.kickoff(year, state) + timedelta(days=1)
    wednesday = S.week_wednesday(year, 1, state)
    add(wednesday, "First Primary Waiver",
        extra=["Last day to place players on the taxi squad."])
    add(first, "First Game")
    add(wednesday + timedelta(days=2), "First Secondary Waiver")
    add(wednesday + timedelta(days=4), "First Tertiary Waiver")

    # The playoffs, the toilet bowl and the deadline that sits among them.
    for i in range(shape["championship_week"] - shape["playoff_start_week"]):
        opens, closes = S.week_window(year, shape["playoff_start_week"] + i, state)
        add(opens, "Playoff Week " + str(i + 1), end=closes)
    deadline = shape.get("trade_deadline_week")
    if deadline:
        add(S.week_window(year, deadline, state)[0], "Trade Deadline Day")
    final_from, final_to = S.week_window(year, shape["championship_week"], state)
    add(final_from, "Championship Week", end=final_to)
    add(final_to + timedelta(days=1), "First Day of the Post-Season", "post_season")

    # Date order, and where two fall on the same day the longer one leads: the
    # trade deadline sits inside playoff week two, as the old page had it.
    events.sort(key=lambda ev: (ev[0], -((ev[1] or ev[0]) - ev[0]).days))
    return events


def calendar_page(cfg, current, state, today=None):
    """
    The league year, this season and next. Past dates are dimmed and the next
    one up is marked, so the page says where the league is as well as what is
    coming.
    """
    today = today or datetime.now(timezone.utc).date()
    year = cfg["season"]["year"]
    blocks, flagged = [], False
    for season in (year, year + 1):
        rows = []
        for when, end, prefix, title, notes in season_calendar(cfg, season, current, state):
            past = (end or when) < today
            mark = ""
            if not past and not flagged:
                mark, flagged = " next", True
            items = "".join("<li>" + e(n) + "</li>" for n in notes)
            rows.append(f"""
      <li class="calrow{' past' if past else ''}{mark}">
        <div class="caldate"><span class="calwhen">{('<span class="calpre">' + e(prefix) + '</span> ') if prefix else ''}{span_words(when, end)}</span></div>
        <div class="calwhat"><h3>{e(title)}</h3>{('<ul>' + items + '</ul>') if items else ''}</div>
      </li>""")
        if rows:
            note = "Worked out from Sleeper and the rulebook." if season == year else ""
            blocks.append("<section>" + sechead(str(season) + " Season", note)
                          + '<ol class="cal">' + "".join(rows) + "</ol></section>")
    return "".join(blocks)


def load_rankings():
    """
    Matt's own rankings, from `assets/rankings/<season>.json`: how he rates each
    roster for the season ahead and for the long haul. Found by filename, no
    config entry, and **nothing in the build computes them** - they are worked
    out elsewhere and read in. The newest file wins.
    """
    files = sorted(RANKINGS.glob("*.json"), key=lambda p: p.stem) if RANKINGS.exists() else []
    for path in reversed(files):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
    return None


def rank_cell(col, value):
    kind = col.get("kind")
    if kind == "change":
        # A blank in the sheet means the manager has not moved.
        return '<td class="num">' + move_chip(int(value or 0)) + "</td>"
    if value is None:
        return '<td class="num"><span class="hd">&mdash;</span></td>'
    if kind == "score":
        return '<td class="num">' + f"{float(value):.2f}" + "</td>"
    return '<td class="num">' + e(value) + "</td>"


def rankings_sections(cfg, rankings, teams):
    """
    The two personalised rankings, each as its own section: the season's, and
    the dynasty one. Columns come from the file, grouped under a spanning header
    the way Matt's sheets have them, so the shape can change without the site
    changing with it.
    """
    if not rankings:
        return ""
    slugs = {t["manager"]: t["slug"] for t in teams.values()}
    out = []
    for table in rankings.get("tables") or []:
        cols = [c for c in table.get("columns") or [] if c.get("key")]
        rows = list(table.get("rows") or [])
        if not cols or not rows:
            continue
        # Two header rows: the groups spanning across the top, labels beneath.
        spans, i = [], 0
        while i < len(cols):
            group, n = cols[i].get("group") or "", 1
            while i + n < len(cols) and (cols[i + n].get("group") or "") == group:
                n += 1
            spans.append((group, n))
            i += n
        top = ('<th rowspan="2" class="l">Manager</th>'
               + "".join('<th colspan="' + str(n) + '" class="grp">' + e(g) + "</th>"
                         for g, n in spans))
        second = "".join("<th>" + e(c.get("label") or "") + "</th>" for c in cols)

        key = table.get("rank_by")
        if key:
            rows.sort(key=lambda r: (r.get("cells") or {}).get(key) or 99)
        body = []
        for row in rows:
            name = row.get("manager") or ""
            label = e(name)
            if name in slugs:
                label = '<a href="team-' + e(slugs[name]) + '.html">' + label + "</a>"
            cells = row.get("cells") or {}
            body.append('<tr><td class="l"><div class="tm"><span class="nm">' + label
                        + "</span></div></td>"
                        + "".join(rank_cell(c, cells.get(c["key"])) for c in cols) + "</tr>")

        sub = (table.get("subtitle") or "").strip()
        when = table.get("updated")
        if when:
            try:
                sub = (sub + " Updated " + day_words(date.fromisoformat(when)) + ".").strip()
            except ValueError:
                pass
        notes = "".join("<li>" + e(n) + "</li>" for n in table.get("notes") or [])
        out.append("<section>" + sechead(table.get("title") or "Rankings", sub)
                   + '<div class="rank"><div class="tablewrap"><table>'
                   + "<thead><tr>" + top + "</tr><tr>" + second + "</tr></thead>"
                   + "<tbody>" + "".join(body) + "</tbody></table></div>"
                   + ('<ul class="ranknote">' + notes + "</ul>" if notes else "")
                   + "</div></section>")
    return "".join(out)


def offseason_home(cfg, phase, current, indexed, names, log, board, players, teams, state):
    """
    The Scoreboard between seasons. Looks forward to the draft and kickoff, back
    at the season just settled, and at whatever has happened since the final:
    the rookie draft, and every trade in this off-season window.
    """
    year = int(current.get("season") or 0)
    # The season being looked back on: this one if it is settled, otherwise the
    # most recent one that was.
    review = max((s for s in indexed if s["final"]), key=lambda s: s["season"], default=None)
    # The rankings lead: they are the thing worth reading between seasons.
    parts = [up_next(cfg, current, state, None),
             rankings_sections(cfg, load_rankings(), teams)]

    if review:
        era = cfg["eras"].get(review["era"], {})
        parts.append('<section class="seasonblock">'
                     + sechead(str(review["season"]) + " in review", era.get("label", ""))
                     + season_podium(cfg, review, names)
                     + '<div class="finishes">' + final_standings_card(cfg, review, names)
                     + "</div></section>")

    parts.append(draft_class_section(cfg, current, names))

    # Trades since the final. In the preseason that is this year's off-season
    # window; once a season is settled but the next league is not up, the trades
    # already belong to next year's window.
    window = ("off", year if phase == "preseason" else year + 1)
    moves = [t for t in log if t["window"] == window]
    if moves:
        slugs = {t["user_id"]: t["slug"] for t in teams.values()}
        logos = {t["user_id"]: t["logo"] for t in teams.values()}
        parts.append("<section>" + sechead(window_name(window) + " trades",
                                           str(len(moves)) + " so far. Every one is in the Trade Centre.")
                     + '<div class="trades">'
                     + "".join(trade_card(t, board, names, players, slugs, logos)
                               for t in reversed(moves))
                     + "</div></section>")
    return "".join(p for p in parts if p)


def honours_section(cfg, indexed, names):
    note = "Every champion since " + str(cfg["league"]["established"]) + ", from the playoff brackets."
    cards = []
    for season in sorted(indexed, key=lambda s: s["season"]):
        winner = names.get(placed(season, 1))
        current = not season["final"]
        cap = "In progress" if current else "Champion"
        cards.append(f"""
      <div class="yr{' current' if current else ''}">
        <span class="season">{e(season['season'])}</span>
        <span class="winner">{e(winner) if winner else "&mdash;"}</span>
        <span class="cap">{cap}</span>
      </div>""")
    return ("<section>" + sechead("Honours", note) + '<div class="honours">'
            + "".join(cards) + "</div></section>")


def era_note(cfg):
    eras = cfg.get("eras", {})
    bce, con = eras.get("bce", {}), eras.get("conference", {})
    return f"""
  <div class="eras">
    <div class="era bce">
      <span class="eralabel">{e(bce.get('label','BCE'))}</span>
      <span class="erayears">{e(bce.get('seasons',''))}</span>
      <p>{e(bce.get('long',''))}. Seasons one and two: no conferences, everyone played everyone.</p>
    </div>
    <div class="era con">
      <span class="eralabel">{e(con.get('label','Conference Era'))}</span>
      <span class="erayears">{e(con.get('seasons',''))}</span>
      <p>{e(con.get('long',''))}. From season three the league split in two, so head-to-head records split with it.</p>
    </div>
  </div>"""


def h2h_table(title, entries, note=""):
    if not entries:
        return ""
    body = "".join('<tr><td>' + e(name) + '</td><td class="num">' + str(r["w"])
                   + '</td><td class="num">' + str(r["l"]) + "</td></tr>" for name, r in entries)
    sub = '<p class="h2hnote">' + e(note) + "</p>" if note else ""
    return f"""
      <div class="h2hblock">
        <h4>{e(title)}</h4>{sub}
        <div class="tablewrap"><table>
          <thead><tr><th>Manager</th><th>W</th><th>L</th></tr></thead>
          <tbody>{body}</tbody>
        </table></div>
      </div>"""


def week_list(weeks):
    """[1, 3, 4, 10, 11, 12] -> '1, 3–4, 10–12'."""
    runs = []
    for wk in sorted(weeks):
        if runs and wk == runs[-1][1] + 1:
            runs[-1][1] = wk
        else:
            runs.append([wk, wk])
    return ", ".join(str(a) if a == b else f"{a}&ndash;{b}" for a, b in runs)


def team_honours(cfg, uid, won, best_weeks, names, players):
    """
    The trophy cabinet, as the old team pages' Honours block had it: a card for
    each honour and a row in it for every season it was won, all computed
    (stats.honours, stats.best_managers). The titles lead; the two dishonours,
    Loser of All Losers and the season's lowest score, come last.
    """
    side = cfg.get("side_competitions") or {}
    labels, cups = side.get("labels", {}), side.get("consolation_by_season", {})
    phase_tag = {"playoffs": labels.get("playoffs", "Playoffs"),
                 "consolation": labels.get("consolation", "Toilet Bowl")}

    def when(h):
        tag = phase_tag.get(h["phase"])
        return "week " + str(h["week"]) + (", " + e(tag).lower() if tag else "")

    def detail(h):
        kind = h["kind"]
        if kind == "champion" and h.get("opponent"):
            return (f'Beat {e(names.get(h["opponent"]) or "Unknown")} in the final, '
                    f'<span class="num">{h["points"]:.2f}&ndash;{h["against"]:.2f}</span>')
        if kind == "regular":
            record = f'<span class="num">{rec(h)}</span>'
            if h["division"]:
                cls = "lc" if h["division"] == "1" else "mc"
                short = cfg["conferences"].get(h["division"], {}).get("short", "")
                return f'<span class="badge {cls}">{e(short)}</span>{record}'
            return f'<span class="badge era">{e(cfg["eras"]["bce"].get("label", "BCE"))}</span>{record}'
        if kind == "consolation":
            cup = cups.get(str(h["season"])) or "Consolation bracket"
            return e(cup) + " &middot; " + ordinal(h["place"]) + ", and the 1.01"
        if kind == "spoon":
            return ordinal(h["place"]) + " place"
        if kind == "top_scorer":
            return f'<span class="num">{h["points"]:,.2f}</span> points'
        if kind in ("high_week", "low_week"):
            return f'<span class="num">{h["points"]:.2f}</span> &middot; {when(h)}'
        if kind == "player_week":
            name = (players.get(h["player_id"]) or {}).get("full_name") or h["player_id"]
            return f'{e(name)} &middot; <span class="num">{h["points"]:.2f}</span> &middot; {when(h)}'
        return ""

    mine = won.get(uid, [])
    cards = [("champion", "Champion", "champion", ""),
             ("regular", "Regular-season winner", "regular", "Top of the conference on record, then points for."),
             ("consolation", "Consolation bracket", "trophy", ""),
             ("top_scorer", "Top scorer", "", "Most points in the regular season."),
             ("high_week", "Weekly high score", "", "The season's biggest score, playoffs included."),
             ("player_week", "Player high score", "", "The season's best week by a starter."),
             ("best", "Best Manager", "", "The week's highest score as a share of max points. Regular season."),
             ("spoon", side.get("wooden_spoon", "Loser of All Losers"), "spoon", ""),
             ("low_week", "Weekly low score", "spoon", "The season's smallest score.")]
    html_cards = []
    for kind, title, cls, note in cards:
        if kind == "best":
            seasons = sorted((best_weeks.get(uid) or {}).items(), reverse=True)
            count = sum(len(w) for _yr, w in seasons)
            rows = [(yr, f'<span class="num">{len(w)}</span> &middot; week{"s" if len(w) > 1 else ""} {week_list(w)}')
                    for yr, w in seasons]
        else:
            rows = [(h["season"], detail(h)) for h in mine if h["kind"] == kind]
            count = len(rows)
        if not rows:
            continue
        items = "".join(f'<li><span class="hy num">{yr}</span><span class="hdet">{det}</span></li>'
                        for yr, det in rows)
        foot = '<p class="hnote">' + e(note) + "</p>" if note else ""
        html_cards.append(f"""
      <div class="hcard{' ' + cls if cls else ''}">
        <div class="hhead"><h3>{e(title)}</h3><span class="hcount num">{count}<span class="x">&times;</span></span></div>
        <ul class="hrows">{items}</ul>{foot}
      </div>""")

    inner = ('<div class="cabinet">' + "".join(html_cards) + "</div>") if html_cards else \
        '<p class="empty">Nothing in the cabinet yet.</p>'
    return ("<section>" + sechead("Honours", "Each one appears once it is settled, straight from Sleeper.")
            + inner + "</section>")


def title_stars(uid, won):
    """A star for every championship beside the team name, as the old pages had it."""
    years = [str(h["season"]) for h in won.get(uid, []) if h["kind"] == "champion"]
    if not years:
        return ""
    label = str(len(years)) + " championship" + ("s" if len(years) > 1 else "")
    return (f'<span class="stars" role="img" aria-label="{label}" title="Champion {", ".join(reversed(years))}">'
            + "&#9733;" * len(years) + "</span>")


def team_page(cfg, team, career, names, won, best_weeks, players):
    s = career.get(team["user_id"])
    conf = cfg["conferences"].get(team["division"], {})
    logo = ('<img class="teamlogo" src="' + e(team["logo"]) + '" alt="' + e(team["team"])
            + ' logo">') if team.get("logo") else ""

    if not s:
        return page(cfg, team["team"], "Teams",
                    "<section>" + sechead(team["team"]) + '<p class="empty">No results recorded yet.</p></section>')

    best, worst = s.get("best_week"), s.get("worst_week")
    facts = [
        ("Career record", rec(s["career"])),
        ("vs " + str(cfg["conferences"]["1"].get("short", "LC")), rec(s["vs_lfc"])),
        ("vs " + str(cfg["conferences"]["2"].get("short", "MC")), rec(s["vs_mfc"])),
        ("BCE record", rec(s["bce"])),
        ("Win %", str(s["win_pct"])),
        ("PPG", format(s["ppg"], ".1f")),
        ("Points for", format(s["pf"], ",.2f")),
        ("Points against", format(s["pa"], ",.2f")),
        ("Record week", format(best[0], ".2f") if best else "&mdash;"),
        ("Lowest week", format(worst[0], ".2f") if worst else "&mdash;"),
        ("Playoffs", str(s["playoff_appearances"]) + (" app, " if s["playoff_appearances"] == 1 else " apps, ")
         + rec(s["playoffs"])),
        ("Trades", '<a href="trades.html#' + e(slugify(team["manager"])) + '">' + str(s["trades"]) + "</a>"),
    ]
    fact_html = "".join("<div><dt>" + e(label) + '</dt><dd class="num">' + value + "</dd></div>"
                        for label, value in facts)

    sub = []
    if best:
        sub.append("Record week set in " + str(best[1]) + " week " + str(best[2]) + ".")
    if worst:
        sub.append("Lowest in " + str(worst[1]) + " week " + str(worst[2]) + ".")

    own_div = team["division"]
    same, other, bce, po, con = [], [], [], [], []
    for opp_id, r in s["h2h"].items():
        name = names.get(opp_id) or "Unknown"
        if r["conference"]["w"] or r["conference"]["l"]:
            (same if r["opponent_division"] == own_div else other).append((name, r["conference"]))
        if r["bce"]["w"] or r["bce"]["l"]:
            bce.append((name, r["bce"]))
        if r["playoffs"]["w"] or r["playoffs"]["l"]:
            po.append((name, r["playoffs"]))
        if r["consolation"]["w"] or r["consolation"]["l"]:
            con.append((name, r["consolation"]))
    for group in (same, other, bce, po, con):
        group.sort(key=lambda row: row[0])

    other_conf = cfg["conferences"]["2" if own_div == "1" else "1"]
    labels = (cfg.get("side_competitions") or {}).get("labels", {})
    body = f"""
  <section class="teamhead">
    {logo}
    <div class="teamtitle">
      <span class="eyebrow">{e(conf.get('name',''))}</span>
      <h1>{e(team['team'])}{title_stars(team['user_id'], won)}</h1>
      <p class="lede">{e(team['manager'])} &middot; {rec(s['career'])} all-time &middot; {len(s['seasons_played'])} seasons</p>
    </div>
  </section>

  {team_honours(cfg, team['user_id'], won, best_weeks, names, players)}

  <section>
    {sechead("Record", " ".join(sub))}
    <dl class="factgrid">{fact_html}</dl>
  </section>

  <section>
    {sechead("Head to head", "The league changed shape in 2022, so the record does too.")}
    {era_note(cfg)}
    <div class="h2hgrid">
      {h2h_table("vs " + str(conf.get("name", "own conference")), same, "Conference era, regular season.")}
      {h2h_table("vs " + str(other_conf.get("name", "the other conference")), other, "Conference era, regular season.")}
      {h2h_table("BCE", bce, "Seasons one and two, before conferences.")}
      {h2h_table(labels.get("playoffs", "Playoffs"), po, "Winners bracket.")}
      {h2h_table(labels.get("consolation", "Toilet Bowl"), con, "Losers bracket.")}
    </div>
  </section>
"""
    return page(cfg, team["team"], "Teams", body)


def teams_index(cfg, teams, table, career):
    rank_by = {r["roster_id"]: r["rank"] for r in (table or {}).get("rows", [])}
    cards = []
    for t in sorted(teams.values(), key=lambda x: x["team"].lower()):
        conf = cfg["conferences"].get(t["division"], {})
        s = career.get(t["user_id"])
        alltime = rec(s["career"]) if s else "&mdash;"
        logo = ('<img class="logo" src="' + e(t["logo"]) + '" alt="" loading="lazy">') if t.get("logo") else ""
        cards.append(f"""
      <a class="teamcard" href="team-{e(t['slug'])}.html">
        <div class="teamcardhead">
          {logo}
          <div class="who">
            <div class="team">{e(t['team'])}</div>
            <div class="mgr">{e(t['manager'])} &middot; {e(conf.get('name',''))}</div>
          </div>
        </div>
        <dl class="teamstats">
          <div><dt>This year</dt><dd class="num">{t['wins']}&ndash;{t['losses']}</dd></div>
          <div><dt>All-time</dt><dd class="num">{alltime}</dd></div>
          <div><dt>Power</dt><dd class="num">{rank_by.get(t['roster_id'], '&mdash;')}</dd></div>
        </dl>
      </a>""")
    return ("<section>" + sechead("Teams", "Ten franchises, two conferences.")
            + '<div class="teamgrid">' + "".join(cards) + "</div></section>")


def record_media(season, kind):
    """assets/records/<season>-<kind>.*, as scripts/prepare_media.py leaves it."""
    for ext in ("webp", "jpg", "jpeg", "png", "gif"):
        if (RECORDS / f"{season}-{kind}.{ext}").exists():
            return f"assets/records/{season}-{kind}.{ext}"
    return ""


def honour_figure(cls, role, who, media):
    if media:
        pic = ('<div class="media"><img src="' + e(media) + '" alt="' + e(who + ", " + role)
               + '" loading="lazy"></div>')
    else:
        pic = '<div class="media none"><span>No picture yet</span></div>'
    return (f'<figure class="honour {cls}">{pic}<figcaption>'
            f'<span class="role">{e(role)}</span><span class="who">{e(who)}</span></figcaption></figure>')


def season_podium(cfg, season, names):
    """
    A season's honours: the champion and the Loser of All Losers with their
    pictures, then the conference winners and whoever took the 1.01. Empty until
    every placement game has been played, because none of it is settled before.
    """
    if not season["final"]:
        return ""
    side = cfg.get("side_competitions") or {}
    cup = (side.get("consolation_by_season") or {}).get(str(season["season"])) or "Consolation bracket"
    spoon = side.get("wooden_spoon", "Loser of All Losers")
    in_conferences = season["era"] == "conference"
    standing = S.conference_finish(season) if in_conferences else {}
    first_loser, last, year = season["playoff_teams"] + 1, len(season["final"]), season["season"]

    def who(uid):
        return names.get(uid) or "Unknown"

    podium = [
        honour_figure("champion", "Champion", who(placed(season, 1)), record_media(year, "champion")),
        honour_figure("spoon", spoon, who(placed(season, last)), record_media(year, "loser")),
    ]
    also = []
    for division in (sorted(cfg["conferences"]) if in_conferences else []):
        winner = next((u for u, (d, p) in standing.items() if d == division and p == 1), None)
        cls = "lc" if division == "1" else "mc"
        label = cfg["conferences"][division].get("short", "") + " regular season"
        also.append(f'<div class="{cls}"><dt>{e(label)}</dt><dd>{e(who(winner))}</dd></div>')
    also.append(f'<div class="trophy"><dt>{e(cup)}</dt><dd>{e(who(placed(season, first_loser)))}'
                f'<span class="sub">{ordinal(first_loser)}, and the 1.01</span></dd></div>')
    podium.append('<dl class="honourlist">' + "".join(also) + "</dl>")
    return '<div class="seasonhonours">' + "".join(podium) + "</div>"


def final_standings_card(cfg, season, names):
    """
    Where everyone finished, first to last, settled in the playoffs and the
    toilet bowl. The three honours in it are badged: champion, the consolation
    bracket and its 1.01, and Loser of All Losers.
    """
    if not season["final"]:
        return ""
    side = cfg.get("side_competitions") or {}
    cup = (side.get("consolation_by_season") or {}).get(str(season["season"])) or "Consolation bracket"
    spoon = side.get("wooden_spoon", "Loser of All Losers")
    in_conferences = season["era"] == "conference"
    division_of = {row["owner_id"]: row["division"] for row in S.season_table(season)}
    first_loser, last = season["playoff_teams"] + 1, len(season["final"])
    rows = []
    for uid, place in sorted(season["final"].items(), key=lambda kv: kv[1]):
        badge = ""
        if place == 1:
            badge = '<span class="badge trophy">Champion</span>'
        elif place == first_loser:
            badge = '<span class="badge trophy">' + e(cup) + "</span>"
        elif place == last:
            badge = '<span class="badge spoon">' + e(spoon) + "</span>"
        short = cfg["conferences"].get(division_of.get(uid), {}).get("short", "")
        conf_cell = "<td>" + e(short) + "</td>" if in_conferences else ""
        rows.append(f"""<tr>
              <td class="num">{ordinal(place)}</td>
              <td><div class="tm"><span class="nm">{e(names.get(uid) or 'Unknown')}</span>{badge}</div></td>{conf_cell}
            </tr>""")
    return finish_card("Final standings", "Settled in the playoffs and the toilet bowl.",
                       "<th>Pos</th><th>Manager</th>" + ("<th>Conf</th>" if in_conferences else ""),
                       rows)


def finish_card(title, note, head, rows):
    return f"""
      <div class="finish">
        <div class="finish-head"><h3>{e(title)}</h3><span class="note">{e(note)}</span></div>
        <div class="tablewrap"><table>
          <thead><tr>{head}</tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table></div>
      </div>"""


def history_sections(cfg, indexed, names):
    """
    Two sets of finishes a season, kept apart because they are different things.
    The regular season is decided on record; the playoffs and the toilet bowl
    decide the final places. Topping your conference does not make you champion,
    and finishing bottom of the table does not make you Loser of All Losers.
    The only honours are the regular-season conference winners, the champion,
    7th (the consolation bracket and the 1.01) and 10th.
    """
    blocks = []
    for season in sorted(indexed, key=lambda s: s["season"], reverse=True):
        table = S.season_table(season)
        if not table:
            continue
        year = season["season"]
        in_conferences = season["era"] == "conference"
        era = cfg["eras"].get(season["era"], {})
        division_of = {row["owner_id"]: row["division"] for row in table}

        def who(uid):
            return names.get(uid) or "Unknown"

        def short(uid):
            return cfg["conferences"].get(division_of.get(uid), {}).get("short", "")

        # Regular season: on record, and within each conference once there were any.
        # Nobody has won a conference until the last regular-season week is played.
        decided = season["regular_done"]
        standing = S.conference_finish(season) if in_conferences else {}
        if in_conferences:
            table.sort(key=lambda r: (r["division"], standing.get(r["owner_id"], ("", 99))[1]))
        reg_rows = []
        for row in table:
            uid, badge = row["owner_id"], ""
            if in_conferences:
                place = standing.get(uid, ("", 0))[1]
                pos = short(uid) + " " + ordinal(place)
                if place == 1 and decided:
                    cls = "lc" if row["division"] == "1" else "mc"
                    badge = '<span class="badge ' + cls + '">' + e(short(uid)) + " winner</span>"
            else:
                pos = ordinal(row["place"])
            reg_rows.append(f"""<tr>
              <td class="num">{e(pos)}</td>
              <td><div class="tm"><span class="nm">{e(who(uid))}</span>{badge}</div></td>
              <td class="num">{row['wins']}&ndash;{row['losses']}</td>
              <td class="num">{row['fpts']:,.2f}</td>
              <td class="num">{row['max_points']:,.2f}</td>
            </tr>""")
        reg_card = finish_card("Regular season", "On record, then points for.",
                               "<th>Pos</th><th>Manager</th><th>W&ndash;L</th><th>PF</th><th>Max PF</th>",
                               reg_rows)

        if not season["final"]:
            blocks.append(f"""
  <section class="seasonblock">
    {sechead(str(year) + " Season", "In progress")}
    <div class="finishes">{reg_card}</div>
  </section>""")
            continue

        fin_card = final_standings_card(cfg, season, names)

        blocks.append(f"""
  <section class="seasonblock">
    {sechead(str(year) + " Season", era.get('label', ''))}
    {season_podium(cfg, season, names)}
    <div class="finishes">{fin_card}{reg_card}</div>
  </section>""")
    return "".join(blocks)


FLEX_WORDS = {1: "one flex", 2: "two flex", 3: "three flex"}


def records_page(cfg, indexed, career, names, waiver, players):
    """
    The all-time record books: Sleeper's all-time standings and the Google Sheets
    that sat on the old History page, all computed. Single weeks, margins and
    streaks count every game, playoffs and toilet bowl included, as Matt's
    sheets do; the season tables are regular season only.
    """
    labels = (cfg.get("side_competitions") or {}).get("labels", {})
    phase_tag = {"playoffs": labels.get("playoffs", "Playoffs"),
                 "consolation": labels.get("consolation", "Toilet Bowl")}

    def who(uid):
        return '<span class="nm">' + e(names.get(uid) or "Unknown") + "</span>"

    def week_cell(row):
        tag = phase_tag.get(row["phase"])
        return str(row["week"]) + ('<span class="tag">' + e(tag) + "</span>" if tag else "")

    def section(title, note, inner):
        return "<section>" + sechead(title, note) + inner + "</section>"

    # All-time standings: the regular season, plus what the brackets handed out.
    honours = defaultdict(lambda: {"titles": 0, "first": 0, "spoons": 0})
    for s in indexed:
        last = len(s["final"])
        for uid, place in s["final"].items():
            honours[uid]["titles"] += place == 1
            honours[uid]["first"] += place == s["playoff_teams"] + 1
            honours[uid]["spoons"] += place == last

    def exact_pct(c):
        r = c["career"]
        played = r["w"] + r["l"] + r["t"]
        return (r["w"] + 0.5 * r["t"]) / played if played else 0.0

    order = sorted(career.items(), key=lambda kv: (exact_pct(kv[1]), kv[1]["pf"]), reverse=True)
    rows = []
    for i, (uid, c) in enumerate(order, 1):
        h = honours[uid]
        rows.append(f"""<tr><td class="num">{i}</td><td>{who(uid)}</td>
          <td class="num">{rec(c['career'])}</td><td class="num">{exact_pct(c) * 100:.1f}%</td>
          <td class="num">{c['pf']:,.2f}</td><td class="num">{c['pa']:,.2f}</td>
          <td class="num">{c['playoff_appearances']}</td><td class="num">{h['titles']}</td>
          <td class="num">{h['first']}</td><td class="num">{h['spoons']}</td></tr>""")
    standings = finish_card(
        "Since " + str(cfg["league"]["established"]), "Regular-season record; playoffs and trophies from the brackets.",
        '<th>#</th><th>Manager</th><th>W&ndash;L</th><th>Win %</th><th>PF</th><th>PA</th>'
        '<th>Playoffs</th><th>Titles</th><th title="7th: the consolation bracket and the 1.01">1.01s</th>'
        '<th title="Loser of All Losers">LoaL</th>', rows)

    # Single weeks.
    scores = S.weekly_scores(indexed)
    by_season = sorted(indexed, key=lambda s: s["season"])
    spans = []
    for s in by_season:
        if spans and spans[-1][0] == s["flex"]:
            spans[-1][2] = s["season"]
        else:
            spans.append([s["flex"], s["season"], s["season"]])
    lineup_note = "; ".join(FLEX_WORDS.get(f, f"{f} flex") + " " + (f"{a}&ndash;{b}" if a != b else str(a))
                            for f, a, b in spans)
    lineup_note = lineup_note[:1].upper() + lineup_note[1:] + "."
    flex_now, flex_from = spans[-1][0], spans[-1][1]

    def score_card(title, note, items):
        body = [f"""<tr><td class="num">{i}</td><td>{who(r['owner_id'])}</td>
          <td class="num">{r['season']}</td><td class="num">{week_cell(r)}</td>
          <td class="num">{r['points']:.2f}</td></tr>""" for i, r in enumerate(items, 1)]
        return finish_card(title, note, "<th>#</th><th>Manager</th><th>Season</th><th>Week</th><th>Score</th>", body)

    low_key = lambda r: (r["points"], r["season"], r["week"])  # noqa: E731
    weeks = [score_card("Lowest scores", "All time.", sorted(scores, key=low_key)[:10])]
    if len(spans) > 1:
        weeks.append(score_card("Lowest scores, " + FLEX_WORDS.get(flex_now, f"{flex_now} flex"),
                                "Since " + str(flex_from) + ".",
                                sorted((r for r in scores if r["season"] >= flex_from), key=low_key)[:10]))
    weeks.append(score_card("Highest scores", "All time.",
                            sorted(scores, key=lambda r: (-r["points"], r["season"], r["week"]))[:10]))

    # The best individual weeks: a starter's points, in a game that counted.
    best = sorted(S.player_weeks(indexed), key=lambda r: (-r["points"], r["season"], r["week"]))[:10]
    player_body = []
    for i, r in enumerate(best, 1):
        p = players.get(r["player_id"]) or {}
        pos = '<span class="tag">' + e(p["position"]) + "</span>" if p.get("position") else ""
        player_body.append(f"""<tr><td class="num">{i}</td>
          <td><span class="nm">{e(p.get('full_name') or r['player_id'])}</span>{pos}</td>
          <td class="l">{who(r['owner_id'])}</td><td class="num">{r['season']}</td>
          <td class="num">{week_cell(r)}</td><td class="num">{r['points']:.2f}</td></tr>""")
    weeks.append(finish_card("Best player weeks", "Starters only.",
                             '<th>#</th><th>Player</th><th class="l">Manager</th><th>Season</th>'
                             '<th>Week</th><th>Points</th>', player_body))

    # Seasons.
    seasons = S.season_records(indexed)

    def reg_place(r):
        if r["division"]:
            return e(cfg["conferences"].get(r["division"], {}).get("short", "")) + " " + ordinal(r["regular_place"])
        return ordinal(r["regular_place"])

    def team_card(title, note, items):
        body = [f"""<tr><td class="num">{i}</td><td>{who(r['owner_id'])}</td>
          <td class="num">{r['season']}</td>
          <td class="num">{r['w']}&ndash;{r['l']}{'&ndash;' + str(r['t']) if r['t'] else ''}</td>
          <td class="num">{r['win_pct'] * 100:.1f}%</td><td class="num">{r['pf']:,.2f}</td>
          <td class="num">{r['per_player']:.2f}</td><td class="num">{reg_place(r)}</td>
          <td class="num">{ordinal(r['final_place']) if r['final_place'] else '&mdash;'}</td></tr>"""
                for i, r in enumerate(items, 1)]
        return finish_card(title, note,
                           '<th>#</th><th>Manager</th><th>Season</th><th>W&ndash;L</th><th>Win %</th><th>PF</th>'
                           '<th title="Points per player per game. DEF is a team, so it is left out.">Per player</th>'
                           '<th>Reg</th><th>Final</th>', body)

    high_body = [f"""<tr><td class="num">{i}</td><td>{who(r['owner_id'])}</td>
          <td class="num">{r['season']}</td><td class="num">{r['pf']:,.2f}</td></tr>"""
                 for i, r in enumerate(sorted(seasons, key=lambda r: (-r["pf"], r["season"]))[:10], 1)]
    season_high = finish_card("Highest season scores", "Points for, regular season.",
                              "<th>#</th><th>Manager</th><th>Season</th><th>PF</th>", high_body)
    dominators = team_card("Dominators", "Top 10 teams ever: win %, then points per player per game.",
                           sorted(seasons, key=lambda r: (-r["win_pct"], -r["per_player"]))[:10])
    loserminators = team_card("Loser-minators", "Worst 10 teams ever: the same, the other way up.",
                              sorted(seasons, key=lambda r: (r["win_pct"], r["per_player"]))[:10])

    # Mind the Gap.
    gaps = sorted((r for r in scores if r["points"] > r["against"]),
                  key=lambda r: (-(r["points"] - r["against"]), r["season"], r["week"]))[:25]
    gap_body = [f"""<tr><td class="num">{i}</td><td>{who(r['owner_id'])}</td>
          <td class="num">{r['points']:.2f}</td><td class="l">{who(r['opponent_id'])}</td>
          <td class="num">{r['against']:.2f}</td><td class="num"><strong>{r['points'] - r['against']:.2f}</strong></td>
          <td class="num">{r['season']}</td><td class="num">{week_cell(r)}</td></tr>"""
                for i, r in enumerate(gaps, 1)]
    gap_card = finish_card("Mind the Gap", "All-time greatest margins of victory.",
                           '<th>#</th><th>Winner</th><th>Score</th><th class="l">Loser</th><th>Score</th>'
                           '<th>Margin</th><th>Season</th><th>Week</th>', gap_body)

    # Streakers.
    runs = S.streaks(indexed)

    def span(run):
        years = sorted({yr for yr, _wk in run})
        label = str(years[0]) if len(years) == 1 else f"{years[0]}&ndash;{str(years[-1])[2:]}"
        parts = []
        for yr in years:
            wks = [wk for y, wk in run if y == yr]
            parts.append(str(wks[0]) if wks[0] == wks[-1] else f"{wks[0]}&ndash;{wks[-1]}")
        return label, ", ".join(parts)

    def streak_card(title, kind):
        items = sorted(((uid, r[kind]) for uid, r in runs.items() if r[kind]),
                       key=lambda x: (-len(x[1]), x[1][0]))
        body = []
        for i, (uid, run) in enumerate(items, 1):
            years, wks = span(run)
            body.append(f"""<tr><td class="num">{i}</td><td>{who(uid)}</td><td class="num">{len(run)}</td>
          <td class="num">{years}</td><td class="num">{wks}</td></tr>""")
        return finish_card(title, "Each manager's longest.",
                           "<th>#</th><th>Manager</th><th>Games</th><th>Season</th><th>Weeks</th>", body)

    body = (section("All-time standings", "", standings)
            + section("Single weeks", "Every game counts: regular season, playoffs and toilet bowl.",
                      '<div class="finishes">' + "".join(weeks) + "</div>")
            + section("Seasons", "Regular season only. " + lineup_note,
                      '<div class="stack"><div class="finishes">' + season_high + "</div>"
                      + dominators + loserminators + "</div>")
            + section("Margins", "", gap_card)
            + section("Streakers", "Runs carry across seasons and through the playoffs. A bye is no game.",
                      '<div class="finishes">' + streak_card("Winning streaks", "W")
                      + streak_card("Losing streaks", "L") + "</div>"))
    if waiver:
        body += section("Waiver record", "The biggest winning FAAB bid.", f"""
    <div class="waiver">
      <span class="bid num">${waiver['bid']:,}</span>
      <span class="what">{e(waiver['player'])}</span>
      <span class="when">{e(names.get(waiver['owner_id']) or 'Unknown')} &middot; {waiver['season']} week {waiver['week']}</span>
    </div>""")
    return body


MOVE_ORDER = {"player": 0, "pick": 1, "faab": 2}


def trade_asset(move, board, names, players):
    """One thing a manager received: a player, a pick or some FAAB."""
    if move["kind"] == "faab":
        return '<li class="faab"><span class="num">$' + str(move["amount"]) + "</span> FAAB</li>"
    if move["kind"] == "player":
        p = players.get(move["player_id"]) or {}
        pos = '<span class="tag">' + e(p["position"]) + "</span>" if p.get("position") else ""
        return '<li><span class="nm">' + e(p.get("full_name") or move["player_id"]) + "</span>" + pos + "</li>"
    # A pick shows as the pick it became once the draft is done, and who it took.
    made = board.get((move["season"], move["round"], move["original"]))
    whose = e(names.get(move["original"]) or "Unknown") + "&rsquo;s pick"
    if made:
        label = move["season"] + " " + made["number"]
        took = made.get("name") or (players.get(made.get("player_id")) or {}).get("full_name")
        if took:
            whose += " &rarr; " + e(took)
    else:
        label = move["season"] + " " + ordinal(move["round"])
    return '<li class="pick"><span class="pk num">' + e(label) + '</span><span class="sub">' + whose + "</span></li>"


def trade_card(trade, board, names, players, slugs, logos):
    sides = []
    for uid in trade["owners"]:
        got = sorted((m for m in trade["moves"] if m["to"] == uid),
                     key=lambda m: (MOVE_ORDER[m["kind"]], m.get("season", ""), m.get("round", 0)))
        name = e(names.get(uid) or "Unknown")
        if uid in slugs:
            name = '<a href="team-' + e(slugs[uid]) + '.html">' + name + "</a>"
        pic = ('<img src="' + e(logos[uid]) + '" alt="" loading="lazy">') if logos.get(uid) else ""
        items = "".join(trade_asset(m, board, names, players) for m in got) or '<li class="none">Nothing</li>'
        sides.append(f'<div class="tside"><h4>{pic}<span class="nm">{name}</span>'
                     f'<span class="rcv">receives</span></h4><ul>{items}</ul></div>')
    day = datetime.fromtimestamp(trade["when"] / 1000, timezone.utc)
    extra = ""
    if trade["window"][0] == "in" and trade.get("leg"):
        extra += '<span class="tag">Week ' + str(trade["leg"]) + "</span>"
    if trade["manual"]:
        extra += '<span class="badge hand" title="Sleeper has no record of this trade">By hand</span>'
    note = '<p class="tradenote">' + e(trade["note"]) + "</p>" if trade["note"] else ""
    who = " ".join(slugify(names.get(uid) or "") for uid in trade["owners"])
    return f"""
      <article class="trade" data-who="{e(who)}">
        <header class="tradehead"><span class="tradeno">Trade {trade['number']}</span>{extra}<span class="tradewhen">{day.day} {day:%b %Y}</span></header>
        <div class="tradesides">{''.join(sides)}</div>{note}
      </article>"""


def window_name(window):
    kind, season = window
    return f"{season} in-season" if kind == "in" else f"{season - 1}/{str(season)[2:]} off-season"


def trade_league_table(cfg, table, names, teams):
    """Matt's Trade League Table: trades made, and what came in and went out."""
    division = {t["user_id"]: t["division"] for t in teams.values()}
    cols = ("trades", "players_in", "picks_in", "players_out", "picks_out")

    def partner(row):
        if not row["partners"]:
            return "&mdash;"
        top = max(row["partners"].values())
        who = sorted(names.get(u) or "Unknown" for u, n in row["partners"].items() if n == top)
        return e(" & ".join(who)) + ' <span class="hd">' + str(top) + "</span>"

    rows = []
    order = sorted(table.items(), key=lambda kv: (-kv[1]["trades"], names.get(kv[0]) or ""))
    for i, (uid, row) in enumerate(order, 1):
        name = names.get(uid) or "Unknown"
        rows.append(f'<tr><td class="num">{i}</td><td><div class="tm"><span class="nm">'
                    f'<a href="#{e(slugify(name))}" title="Show {e(name)}&rsquo;s trades">{e(name)}</a></span></div></td>'
                    + "".join(f'<td class="num">{row[c]}</td>' for c in cols)
                    + f'<td class="l"><div class="tm">{partner(row)}</div></td></tr>')
    # The conferences as they stand, as the old sheet had them: a trade between two
    # managers in the same conference counts for both of them.
    for div in sorted(cfg["conferences"]):
        members = [row for uid, row in table.items() if division.get(uid) == div]
        if members:
            cls = "lc" if div == "1" else "mc"
            rows.append(f'<tr class="total {cls}"><td></td><td><span class="nm">'
                        f'{e(cfg["conferences"][div].get("short", ""))}</span></td>'
                        + "".join(f'<td class="num">{sum(r[c] for r in members)}</td>' for c in cols)
                        + '<td class="l"></td></tr>')
    return finish_card("Since " + str(cfg["league"]["established"]),
                       "Busiest first. Conference totals are the managers in each conference now.",
                       "<th>#</th><th>Manager</th><th>Trades</th><th>Players in</th><th>Picks in</th>"
                       '<th>Players out</th><th>Picks out</th><th class="l">Most trades with</th>', rows)


def loose_ends_section(ends, names, players):
    """Changes of hands Sleeper shows that no trade explains. Empty when all is well."""
    if not ends:
        return ""

    def who(uid):
        return e(names.get(uid) or "Unknown")

    def when(ms):
        day = datetime.fromtimestamp((ms or 0) / 1000, timezone.utc)
        return f"{day.day} {day:%b %Y}"

    items = []
    for end in ends:
        if end["kind"] == "made":
            season, _rnd, original = end["pick"]
            made = end["made"]
            took = " (" + e(made["name"]) + ")" if made.get("name") else ""
            items.append(f"<li>{season} {made['number']}, {who(original)}&rsquo;s pick{took}, was made by "
                         f"{who(made['made_by'])}, but no trade gave it to them &mdash; the trades leave it "
                         f"with {who(end['holder'])}.</li>")
        elif end["kind"] == "sent":
            season, rnd, original = end["pick"]
            items.append(f"<li>{when(end['trade']['when'])}: {who(end['sender'])} traded {who(original)}&rsquo;s "
                         f"{season} {ordinal(rnd)}, but the trades before it leave that pick with "
                         f"{who(end['holder'])}.</li>")
        else:
            p = players.get(end["player_id"]) or {}
            items.append(f"<li>{when(end['when'])}: the commissioner moved {e(p.get('full_name') or end['player_id'])} "
                         f"from {who(end['from'])} to {who(end['to'])}.</li>")
    return ("<section>" + sechead("Loose ends", "Sleeper shows these changing hands, but no trade explains them.")
            + '<div class="looseends"><ul>' + "".join(items) + "</ul><p>A deal done by hand goes in "
            "<code>league.config.json</code> under <code>manual_trades</code>.</p></div></section>")


TRADE_FILTER_JS = """
<script>
(function () {
  var pick = document.getElementById("tradewho");
  if (!pick) return;
  function show(who, jump) {
    pick.value = who;
    if (pick.value !== who) { pick.value = ""; who = ""; }
    document.querySelectorAll(".trade").forEach(function (card) {
      card.hidden = !!who && (" " + card.dataset.who + " ").indexOf(" " + who + " ") < 0;
    });
    document.querySelectorAll(".tradewindow").forEach(function (block) {
      block.hidden = !!who && !block.querySelector(".trade:not([hidden])");
    });
    if (who && jump) document.getElementById("tradelog").scrollIntoView();
  }
  pick.addEventListener("change", function () {
    history.replaceState(null, "", pick.value ? "#" + pick.value : location.pathname + location.search);
    show(pick.value, false);
  });
  window.addEventListener("hashchange", function () { show(location.hash.slice(1), true); });
  show(location.hash.slice(1), true);
})();
</script>"""


def trade_centre(cfg, log, table, board, ends, names, players, teams, state):
    """
    Every trade since 2020, rebuilt from the old Trade Centre: Matt's Trade League
    Table, then the trades themselves in windows - each season, and the off-season
    before it - newest first, numbered within each window oldest first as he
    numbered them. Picks show as the player they became once the draft is done.
    """
    slugs = {t["user_id"]: t["slug"] for t in teams.values()}
    logos = {t["user_id"]: t["logo"] for t in teams.values()}
    windows = defaultdict(list)
    for trade in log:
        windows[trade["window"]].append(trade)
    year = int(cfg["season"]["year"])
    if str(state.get("season")) == str(year) and state.get("season_type") in ("regular", "post"):
        windows.setdefault(("in", year), [])

    blocks = []
    for window in sorted(windows, key=lambda w: (w[1], w[0] == "in"), reverse=True):
        items = windows[window]
        count = f"{len(items)} trade{'' if len(items) == 1 else 's'}" if items else ""
        inner = ('<div class="trades">' + "".join(trade_card(t, board, names, players, slugs, logos)
                                                  for t in reversed(items)) + "</div>"
                 if items else '<p class="empty">No trades yet this season.</p>')
        blocks.append('<section class="tradewindow">' + sechead(window_name(window), count) + inner + "</section>")

    by_hand = sum(1 for t in log if t["manual"])
    options = "".join(f'<option value="{e(slugify(n))}">{e(n)}</option>' for n in sorted(filter(None, names.values())))
    note = (f"{len(log)} trades since {cfg['league']['established']}"
            + (f", {by_hand} of them done by hand on draft day and never recorded by Sleeper." if by_hand else "."))
    return ("<section>" + sechead("Trade league table", note) + trade_league_table(cfg, table, names, teams) + "</section>"
            + '<section id="tradelog" class="tradelog">' + sechead("The trades", "Newest first. Picks show the player taken once the draft is done.")
            + '<div class="tradefilter"><label for="tradewho">Show trades for</label>'
            + '<select id="tradewho"><option value="">Everyone</option>' + options + "</select></div></section>"
            + "".join(blocks) + loose_ends_section(ends, names, players) + TRADE_FILTER_JS)


def doc_card(item, latest=False):
    """One document as a card: a picture of its first page, what it is, and when."""
    if item["cover"]:
        pic = '<div class="cover"><img src="assets/covers/' + e(item["cover"]) + '" alt="" loading="lazy"></div>'
    elif item["link"]:
        pic = '<div class="cover none link"><span>' + e(item["link"]) + " &#8599;</span></div>"
    else:
        pic = '<div class="cover none"><span>PDF</span></div>'
    meta = []
    if item["date"]:
        meta.append(f"{item['date'].day} {item['date']:%b %Y}")
    if item["pages"]:
        meta.append(f"{item['pages']} page{'' if item['pages'] == 1 else 's'}")
    if item["link"]:
        meta.append("On " + e(item["link"]))
    kind = e(item["kind"])
    if latest:
        kind = "Latest" + (" &middot; " + kind if kind else "")
    return (f'<a class="doccard{" latest" if latest else ""}" href="{e(item["href"])}">{pic}<div class="docmeta">'
            + (f'<span class="doctype">{kind}</span>' if kind else "")
            + f'<span class="doctitle">{e(item["title"])}</span>'
            + (f'<span class="docwhen">{" &middot; ".join(meta)}</span>' if meta else "") + "</div></a>")


def updates_page(cfg, seasons):
    """
    The commissioner's updates, rebuilt from the old site's season pages of
    embedded Drive files: draft and season previews, schedules, the mid-season
    and regular-season reviews, and the season reviews. A PDF saved into
    assets/updates/<season>/ is on the page at the next build; see documents.py.
    One season shows at a time, picked from the tabs, as the old site had a page
    a season; updates.html#season-2023 opens 2023. Without script, all show.
    """
    if not seasons:
        return "<section>" + sechead("Commissioner updates") + '<p class="empty">Nothing published yet.</p></section>'
    dated = [it for items in seasons.values() for it in items if it["date"]]
    newest = max(dated, key=lambda it: it["date"]) if dated else None
    total = sum(len(items) for items in seasons.values())
    years = sorted(seasons, reverse=True)

    def documents(n):
        return f"{n} document{'' if n == 1 else 's'}"

    tabs = ('<nav class="jump seasontabs" id="seasontabs" aria-label="Seasons">' + "".join(
        f'<a class="num" href="#season-{year}" title="{documents(len(seasons[year]))}">{year}'
        f'<span class="count">{len(seasons[year])}</span></a>' for year in years) + "</nav>")
    blocks = ["<section>" + sechead("Commissioner updates", f"{total} previews, reviews and schedules since "
                                    f"{min(seasons)}, a season at a time.") + tabs + "</section>"]
    for i, year in enumerate(years):
        items = seasons[year]
        earlier = (f'<p class="seasonnext"><a href="#season-{years[i + 1]}">Earlier: the {years[i + 1]} season '
                   "&rarr;</a></p>" if i + 1 < len(years) else "")
        blocks.append(f'<section class="docseason" id="season-{year}">' + sechead(f"{year} season", documents(len(items)))
                      + '<div class="docs">' + "".join(doc_card(it, it is newest) for it in items) + "</div>"
                      + earlier + "</section>")
    return "".join(blocks) + SEASON_TABS_JS


SEASON_TABS_JS = """
<script>
(function () {
  // One season at a time. The tabs and the "Earlier" links are ordinary links to
  // #season-YYYY, so a season can be linked to, and with no script every season shows.
  var tabs = document.querySelectorAll(".seasontabs a");
  var seasons = document.querySelectorAll(".docseason");
  if (!tabs.length || !seasons.length) return;
  function show(id, jump) {
    if (!document.getElementById(id) || !document.getElementById(id).classList.contains("docseason")) {
      id = seasons[0].id;
    }
    seasons.forEach(function (s) { s.hidden = s.id !== id; });
    tabs.forEach(function (a) {
      if (a.getAttribute("href") === "#" + id) a.setAttribute("aria-current", "true");
      else a.removeAttribute("aria-current");
    });
    if (jump) document.getElementById("seasontabs").scrollIntoView({block: "nearest"});
  }
  document.addEventListener("click", function (ev) {
    var link = ev.target.closest('a[href^="#season-"]');
    if (!link) return;
    ev.preventDefault();
    history.replaceState(null, "", link.getAttribute("href"));
    show(link.getAttribute("href").slice(1), true);
  });
  window.addEventListener("hashchange", function () { show(location.hash.slice(1), true); });
  show(location.hash.slice(1), false);
})();
</script>"""


LINEUP_NAMES = {"FLEX": "Flex", "SUPER_FLEX": "Superflex", "WRRB_FLEX": "RB/WR flex",
                "REC_FLEX": "WR/TE flex", "IDP_FLEX": "IDP flex"}

# Sleeper's scoring keys, grouped and named as a rulebook would list them. Any key
# not here still shows, under Other, so a new setting is never hidden.
SCORING = [
    ("Passing", [("pass_yd", "Passing yards"), ("pass_td", "Passing TD"), ("pass_2pt", "Two-point conversion"),
                 ("pass_int", "Interception thrown"), ("pass_int_td", "Pick six thrown")]),
    ("Rushing", [("rush_yd", "Rushing yards"), ("rush_td", "Rushing TD"), ("rush_2pt", "Two-point conversion")]),
    ("Receiving", [("rec", "Reception"), ("bonus_rec_te", "TE reception bonus"), ("rec_yd", "Receiving yards"),
                   ("rec_td", "Receiving TD"), ("rec_2pt", "Two-point conversion")]),
    ("Fumbles", [("fum", "Fumble"), ("fum_lost", "Fumble lost"), ("fum_rec_td", "Fumble recovery TD")]),
    ("Kicking", [("fgm", "Field goal"), ("fgm_yds_over_30", "Field goal yards over 30"),
                 ("fgmiss", "Field goal missed"), ("xpm", "Extra point"), ("xpmiss", "Extra point missed")]),
    ("Defence", [("sack", "Sack"), ("int", "Interception"), ("fum_rec", "Fumble recovery"), ("ff", "Forced fumble"),
                 ("safe", "Safety"), ("def_td", "Defensive TD"), ("blk_kick", "Blocked kick"),
                 ("def_st_td", "Special teams TD"), ("def_st_ff", "Special teams forced fumble"),
                 ("def_st_fum_rec", "Special teams fumble recovery")]),
    ("Points allowed", [("pts_allow_0", "Shutout"), ("pts_allow_1_6", "1&ndash;6"), ("pts_allow_7_13", "7&ndash;13"),
                        ("pts_allow_14_20", "14&ndash;20"), ("pts_allow_21_27", "21&ndash;27"),
                        ("pts_allow_28_34", "28&ndash;34"), ("pts_allow_35p", "35 or more")]),
    ("Player special teams", [("st_td", "Special teams TD"), ("st_ff", "Forced fumble"),
                              ("st_fum_rec", "Fumble recovery")]),
]


def score_value(key, value):
    if key.endswith("_yd") or key == "fgm_yds_over_30":
        per = 1 / value if value else 0
        if value > 0 and abs(per - round(per)) < 1e-6:
            return f"1 per {round(per)} yards"
        return f"{value:g} a yard"
    return (f"{value:+g}" if value else "0").replace("-", "&minus;")


def scoring_groups(scoring):
    """Sleeper's scoring settings as small tables, every non-zero setting shown."""
    s = {k: float(v) for k, v in scoring.items() if isinstance(v, (int, float))}
    kicking = dict(SCORING)["Kicking"]
    buckets = sorted((k for k in s if re.fullmatch(r"fgm_(\d+_\d+|\d+p)", k)),
                     key=lambda k: int(re.findall(r"\d+", k)[0]))
    if buckets and len({s[k] for k in buckets}) == 1:
        s["fgm"] = s[buckets[0]]
        for k in buckets:
            del s[k]
    else:
        kicking = [(k, "Field goal " + k[4:].replace("_", "&ndash;").replace("p", "+") + " yards")
                   for k in buckets] + kicking
    groups, seen = [], set()
    for group, keys in SCORING:
        if group == "Kicking":
            keys = kicking
        rows = []
        for key, label in keys:
            seen.add(key)
            if key in s and (s[key] or group == "Points allowed"):
                rows.append((label, score_value(key, s[key])))
        if rows:
            groups.append((group, rows))
    other = [(e(k.replace("_", " ")), score_value(k, v)) for k, v in sorted(s.items()) if k not in seen and v]
    if other:
        groups.append(("Other", other))
    return groups


def sleeper_section(current):
    """The league as Sleeper has it set up, read at every refresh."""
    st = current.get("settings") or {}
    slots = current.get("roster_positions") or []
    counts = {}
    for slot in slots:
        if slot != "BN":
            counts[slot] = counts.get(slot, 0) + 1
    lineup = " &middot; ".join(f"{n} {e(LINEUP_NAMES.get(p, p))}" for p, n in counts.items())
    taxi_note = ", ".join(filter(None, ["Rookies" if not st.get("taxi_allow_vets") else "",
                                        f"up to {st['taxi_years']} years" if st.get("taxi_years") else ""]))
    facts = [
        ("wide", "Starting lineup", lineup, f"{sum(counts.values())} starters"),
        ("num", "Bench", str(slots.count("BN")), ""),
        ("num", "Injured reserve", str(st.get("reserve_slots", 0)), ""),
        ("num", "Taxi", str(st.get("taxi_slots", 0)), taxi_note.capitalize()),
        ("num", "FAAB", f"${st.get('waiver_budget', 0):,}", "Blind bidding" if st.get("waiver_type") == 2 else ""),
        ("num", "Playoffs", f"{st.get('playoff_teams', '')} teams",
         f"From week {st['playoff_week_start']}" if st.get("playoff_week_start") else ""),
        ("num", "Rookie draft", f"{st.get('draft_rounds', '')} rounds", ""),
    ]
    grid = "".join(f'<div{" class=" + chr(34) + "wide" + chr(34) if kind == "wide" else ""}><dt>{e(label)}</dt>'
                   f'<dd{" class=" + chr(34) + "num" + chr(34) if kind == "num" else ""}>{value}'
                   + (f'<span class="sub">{e(note)}</span>' if note else "") + "</dd></div>"
                   for kind, label, value, note in facts)
    cards = "".join(
        f'<div class="h2hblock"><h4>{e(group)}</h4><div class="tablewrap"><table><tbody>'
        + "".join(f'<tr><td>{label}</td><td class="num">{value}</td></tr>' for label, value in rows)
        + "</tbody></table></div></div>" for group, rows in scoring_groups(current.get("scoring_settings") or {}))
    return ('<section id="on-sleeper">' + sechead("On Sleeper", "Read from the league's settings at every refresh, "
                                                  "so this is what the app is set to today.")
            + f'<div class="stack"><dl class="factgrid">{grid}</dl><div class="h2hgrid scoregrid">{cards}</div></div></section>')


def doc_table(rows, text):
    width = max((sum(c["span"] for c in r["cells"]) for r in rows), default=1)
    out = []
    for r in rows:
        cells = r["cells"]
        if width > 1 and len(cells) == 1 and cells[0]["span"] >= width:
            out.append(f'<tr class="band"><th colspan="{width}">' + "<br>".join(map(text, cells[0]["lines"]))
                       + "</th></tr>")
            continue
        tag = "th" if r["header"] else "td"
        out.append("<tr>" + "".join(f'<{tag}{" colspan=" + chr(34) + str(c["span"]) + chr(34) if c["span"] > 1 else ""}>'
                                    + "<br>".join(map(text, c["lines"])) + f"</{tag}>" for c in cells) + "</tr>")
    return '<div class="tablewrap"><table class="doc">' + "".join(out) + "</table></div>"


def rulebook_html(book):
    """The rulebook's blocks as HTML, and its chapters for the contents."""
    rules = {b["label"].rstrip(".") for b in book["blocks"] if b.get("rule")}
    ids, toc, out = set(), [], []

    def text(t):
        # The rules refer to each other by paragraph number; link those that exist.
        body = e(t).replace("\n", "<br>")
        return re.sub(r"\b(paras?\.?|paragraphs?)(\s+)(\d{1,3})\b",
                      lambda m: m.group(0) if m.group(3) not in rules
                      else f'{m.group(1)}{m.group(2)}<a href="#rule-{m.group(3)}">{m.group(3)}</a>', body)

    def anchor(t):
        base = slugify(t)
        slug, n = base, 2
        while slug in ids:
            slug, n = f"{base}-{n}", n + 1
        ids.add(slug)
        return slug

    for b in book["blocks"]:
        if b["type"] in ("h1", "h2"):
            slug, tag = anchor(b["text"]), "h2" if b["type"] == "h1" else "h3"
            if b["type"] == "h1":
                toc.append((slug, b["text"]))
            out.append(f'<{tag} id="{slug}">{e(b["text"])}</{tag}>')
        elif b["type"] == "table":
            out.append(doc_table(b["rows"], text))
        elif b["rule"]:
            n = e(b["label"].rstrip("."))
            out.append(f'<p class="rule" id="rule-{n}"><a class="rn" href="#rule-{n}">{e(b["label"])}</a>'
                       f'<span>{text(b["text"])}</span></p>')
        elif b["label"]:
            out.append(f'<p class="rule sub"><span class="rn">{e(b["label"])}</span><span>{text(b["text"])}</span></p>')
        else:
            out.append(f'<p{" class=" + chr(34) + "cont" + chr(34) if b["list"] else ""}>{text(b["text"])}</p>')
    return "".join(out), toc


def change_html(runs):
    tags = {"old": ("<del>", "</del>"), "new": ("<ins>", "</ins>"), "same": ("", "")}
    return " ".join(tags[kind][0] + e(words) + tags[kind][1] for kind, words in runs)


def editions_section(editions):
    """Every edition, newest first, with what changed from the one before it."""
    items = []
    for ed in reversed(editions):
        current = ed is editions[-1]
        revised = ed.get("previous") == ed["number"]
        when = ed["month"] + (f", revised {ed['date']:%B %Y}" if revised and ed["date"] else "")
        head = (f'<div class="edhead"><span class="edname">{ordinal(ed["number"])} Edition</span>'
                + ('<span class="badge trophy">In force</span>' if current else "")
                + f'<span class="edwhen">{e(when)}</span>'
                + f'<a href="{e(ed["href"])}">PDF &middot; {ed["pages"]} pages</a></div>')
        found = ed.get("changes")
        if "previous" not in ed:
            detail = '<p class="ednote">The first edition.</p>'
        elif not found:
            detail = '<p class="ednote">No change to the wording.</p>'
        else:
            what = "in the revision" if revised else "from the " + ordinal(ed["previous"]) + " Edition"
            detail = (f'<details><summary>What changed {what} &middot; {len(found)} '
                      f'change{"" if len(found) == 1 else "s"}</summary><ul class="changes">'
                      + "".join("<li>&hellip; " + change_html(runs) + " &hellip;</li>" for runs in found)
                      + "</ul></details>")
        items.append(f'<div class="edition{" current" if current else ""}">{head}{detail}</div>')
    note = (f"{len(editions)} since {editions[0]['month']}, newest first. What changed is worked out word by word "
            "from the PDFs, so nobody has to write it up.")
    return ('<section id="editions">' + sechead("Editions", note)
            + '<div class="editions">' + "".join(items) + "</div></section>")


def rules_page(cfg, current, book, editions, others):
    """
    The Rules tab. The old one embedded each edition's PDF with a line on what
    had changed; this one sets out the current rulebook as a page, straight from
    Matt's Word file, then what Sleeper is set to, then every edition with its
    changes worked out from the PDFs. A new edition is its Word file and PDF saved
    into assets/rules/.
    """
    pdf = next((ed for ed in reversed(editions) if book and ed["number"] == book["number"]), None)
    parts = []
    if book:
        body, toc = rulebook_html(book)
        lede = e(book["edition"]) + (f' &middot; <a href="{e(pdf["href"])}">PDF, {pdf["pages"]} pages</a>' if pdf else "")
        chips = toc + [("on-sleeper", "On Sleeper")] + ([("editions", "Editions")] if editions else [])
        parts.append(f'<section class="bookhead"><span class="eyebrow">Rules</span>'
                     f'<h1>{e(book["title"] or cfg["league"]["name"] + " Rules")}</h1><p class="lede">{lede}</p></section>'
                     '<nav class="jump booktoc" aria-label="Contents">'
                     + "".join(f'<a href="#{slug}">{e(label)}</a>' for slug, label in chips) + "</nav>"
                     f'<article class="rulebook">{body}</article>')
    elif editions:
        latest = editions[-1]
        parts.append("<section>" + sechead("Rules", ordinal(latest["number"]) + " Edition, " + latest["month"])
                     + f'<p><a href="{e(latest["href"])}">The rulebook, as a PDF</a>. Save its Word file into '
                     "<code>assets/rules/</code> and it is set out here in full.</p></section>")
    parts.append(sleeper_section(current))
    if editions:
        parts.append(editions_section(editions))
    if others:
        parts.append("<section>" + sechead("Other documents") + '<div class="docs">'
                     + "".join(doc_card(it) for it in others) + "</div></section>")
    return "".join(parts)


def season_setup(cfg, current):
    """
    The shape of the season now on. Sleeper knows when the playoffs start and
    how many teams are in them, so those come from the league itself and
    league.config.json is only the fallback. The year comes from the league too:
    the site follows Sleeper from one season to the next without being told.
    """
    shape = dict(cfg["season"])
    settings = current.get("settings") or {}
    start = settings.get("playoff_week_start") or shape["playoff_start_week"]
    teams = settings.get("playoff_teams") or shape["playoff_teams"]
    rounds = max(1, (teams - 1).bit_length())
    shape.update(year=int(current.get("season") or shape["year"]),
                 playoff_start_week=start,
                 regular_season_weeks=start - 1,
                 playoff_teams=teams,
                 championship_week=start + rounds - 1)
    return shape


def season_phase(current, season, state, today=None):
    """
    Where the league is in its year, from the games rather than Sleeper's clock:

      "over"       every placement game is done, so the season is settled and
                   there is nothing left to play;
      "season"     games are being played, or the season is as good as here;
      "preseason"  the new season is up on Sleeper but has not started - the
                   back half of the off-season.

    The season starts on **1 September**, not at kickoff: that is the roster
    deadline on Matt's calendar, and the day he wants the site back in season
    mode, a week or so before a ball is kicked.

    `current` is the season as fetched, `season` is it indexed.
    """
    if season["final"]:
        return "over"
    if any((m.get("points") or 0) for entries in (current.get("matchups") or {}).values()
           for m in entries):
        return "season"
    today = today or datetime.now(timezone.utc).date()
    year = int(current.get("season") or 0)
    return "season" if year and today >= date(year, 9, 1) else "preseason"


def conference_titles(cfg, indexed, teams):
    """
    Championships won by the managers in each conference now - what the stars on
    the crests and the league logo are counting. They move when someone changes
    conference and grow when someone wins, so they go stale on their own.
    """
    champions = Counter()
    for season in indexed:
        uid = placed(season, 1)
        if uid:
            champions[uid] += 1
    stars = {}
    for division, conf in cfg["conferences"].items():
        members = [t["user_id"] for t in teams.values() if t["division"] == division]
        stars[conf.get("short") or division] = sum(champions[uid] for uid in members)
    return stars


def season_todo(cfg, current, indexed, teams, phase):
    """
    The jobs a settled season leaves Matt, which are easy to forget because they
    only come round once a year. Printed at the end of every build, so the
    workflow can put them where he will see them. Empty while the season is on.
    """
    if phase == "season":
        return []
    settled = max((s for s in indexed if s["final"]), key=lambda s: s["season"], default=None)
    if not settled:
        return []
    year = settled["season"]
    jobs = []
    if not record_media(year, "champion"):
        jobs.append(f"No {year} champion loop in assets/records. Put the GIF through "
                    f"scripts/prepare_media.py.")
    if not record_media(year, "loser"):
        jobs.append(f"No {year} Loser of All Losers picture in assets/records. Put it through "
                    f"scripts/prepare_media.py.")
    cups = (cfg.get("side_competitions") or {}).get("consolation_by_season") or {}
    if not (cups.get(str(year + 1)) or "").strip():
        jobs.append(f"The {year + 1} consolation trophy has no name in league.config.json. "
                    f"Until it does, 7th place shows as \"Consolation bracket\".")
    stars = conference_titles(cfg, indexed, teams)
    jobs.append("Championships by conference are now "
                + ", ".join(f"{short} {n}" for short, n in sorted(stars.items()))
                + ". The crests in assets/conferences and the league logo are pictures, so "
                  "check they still show that many stars.")
    return jobs


def last_complete_week(state, season):
    """
    The last week of `season` whose games are all over, by Sleeper's clock, or
    None when the whole season is. A week still in progress is not a result yet.
    """
    if not state:
        return None
    here, now = int(season or 0), int(state.get("season") or 0)
    if now > here or state.get("season_type") == "off":
        return None
    if now < here or state.get("season_type") == "pre":
        return 0
    return max(0, int(state.get("week") or 1) - 1)


def main():
    cfg = json.loads((ROOT / "league.config.json").read_text(encoding="utf-8"))
    current = load("current.json")
    if not current:
        raise SystemExit("data/current.json missing - run scripts/fetch_data.py first")
    state = load("state.json", {}) or {}
    players = load("players.json", {}) or {}
    history = load("history.json", []) or []

    # The season now on, its year and its shape, all from Sleeper. Nothing in
    # league.config.json has to change when the league rolls over.
    cfg["season"] = season_setup(cfg, current)

    conference_from = int(cfg.get("eras", {}).get("conference_from", 2022))
    all_seasons = [current] + history
    # A week still being played is not a result yet, so the current season only
    # counts as far as its last finished week.
    through = last_complete_week(state, current.get("season"))
    indexed = [S.index_season(s, conference_from, through if s is current else None)
               for s in all_seasons]
    transactions = [s.get("transactions") for s in all_seasons]
    names = {uid: conf.get("name") for uid, conf in (cfg.get("managers") or {}).items()}

    # Every trade: Sleeper's, and the draft-day ones done by hand that it never recorded.
    manual = S.manual_trades((cfg.get("manual_trades") or {}).get("trades") or [],
                             {name: uid for uid, name in names.items() if name}, players)
    trade_log = S.trade_log(all_seasons, manual, state)
    trade_table = S.trade_table(trade_log)
    board = S.draft_board(all_seasons)
    ends = S.trade_loose_ends(all_seasons, trade_log, board)
    career = S.all_time(indexed, {uid: row["trades"] for uid, row in trade_table.items()})

    teams = manager_lookup(cfg, current.get("users", []), current.get("rosters", []))
    results = weekly_results(current, players)

    # Where the league is in its year. Between the final and kickoff there are
    # no fixtures to show, so the Scoreboard becomes an off-season page instead
    # of going on showing the last week played.
    phase = season_phase(current, indexed[0], state)

    week = int(state.get("week") or 1)
    if str(state.get("season")) != str(current.get("season")):
        week = cfg["season"]["regular_season_weeks"]
    week = max(1, min(week, cfg["season"]["championship_week"]))

    # Power rankings: fixed at noon UK on the Wednesday before each week's games
    # and kept as they were fixed, so the page shows the week that stands.
    projections = load("projections.json")
    power = None
    if phase == "season":
        power = power_table(power_store(cfg, current, indexed[0], projections, players, state),
                            teams)

    # Last season's conference tables, which is what the divisional-week billings
    # are drawn from. Absent in the first conference year, when there is no
    # conference table to look back on.
    last_season = max((s for s in indexed if s["season"] < int(current["season"])
                       and s["era"] == "conference"), key=lambda s: s["season"], default=None)
    prev_finish = S.conference_finish(last_season) if last_season else {}

    DOCS.mkdir(parents=True, exist_ok=True)
    if ASSETS.exists():
        shutil.copytree(ASSETS, DOCS / "assets", dirs_exist_ok=True)
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")

    # Playoff odds, while the regular season still has games to play.
    odds = None
    if cfg["site"].get("show_playoff_odds") and phase == "season":
        odds = S.playoff_odds(current, indexed[0], indexed[1:], projections, players,
                              cfg["season"]["regular_season_weeks"])

    # The Pro Bowl sits straight after the week's fixtures, from the moment the
    # first picks land until the end of the season.
    game = pro_bowl(cfg, current, teams, players, projections, prev_finish, state)

    if phase == "season":
        home = (scoreboard(cfg, teams, results, week, career, prev_finish, odds)
                + pro_bowl_section(cfg, game, names)
                + odds_section(cfg, teams, odds) + power_section(cfg, power))
    else:
        home = offseason_home(cfg, phase, current, indexed, names, trade_log, board,
                              players, teams, state)
    home += honours_section(cfg, indexed, names)
    (DOCS / "index.html").write_text(page(cfg, "Scoreboard", "Scoreboard", home), encoding="utf-8")

    (DOCS / "standings.html").write_text(
        page(cfg, "Standings", "Standings",
             standings_section(cfg, teams, str(cfg["season"]["year"]) + " Standings")), encoding="utf-8")

    (DOCS / "teams.html").write_text(
        page(cfg, "Teams", "Teams", teams_index(cfg, teams, power, career)), encoding="utf-8")

    (DOCS / "calendar.html").write_text(
        page(cfg, "Calendar", "Calendar", calendar_page(cfg, current, state)), encoding="utf-8")

    won, best_weeks = S.honours(indexed), S.best_managers(indexed, players)
    for team in teams.values():
        (DOCS / ("team-" + team["slug"] + ".html")).write_text(
            team_page(cfg, team, career, names, won, best_weeks, players), encoding="utf-8")

    history_body = (honours_section(cfg, indexed, names)
                    + "<section>" + sechead("The two eras") + era_note(cfg) + "</section>"
                    + history_sections(cfg, indexed, names))
    (DOCS / "history.html").write_text(page(cfg, "History", "History", history_body), encoding="utf-8")

    waiver = S.waiver_record(transactions, indexed, players)
    (DOCS / "records.html").write_text(
        page(cfg, "Records", "Records", records_page(cfg, indexed, career, names, waiver, players)), encoding="utf-8")

    (DOCS / "trades.html").write_text(
        page(cfg, "Trade Centre", "Trade Centre",
             trade_centre(cfg, trade_log, trade_table, board, ends, names, players, teams, state)), encoding="utf-8")

    # The documents: files saved into assets/, found where they sit (documents.py).
    covers = DOCS / "assets" / "covers"
    updates = D.commissioner_updates(ASSETS / "updates", ASSETS, covers)
    (DOCS / "updates.html").write_text(
        page(cfg, "Commissioner Updates", "Commissioner Updates", updates_page(cfg, updates)), encoding="utf-8")
    book = D.current_rulebook(ASSETS / "rules")
    editions, others = D.rule_editions(ASSETS / "rules", ASSETS, covers)
    (DOCS / "rules.html").write_text(
        page(cfg, "Rules", "Rules", rules_page(cfg, current, book, editions, others)), encoding="utf-8")
    D.prune_covers(covers, {it["cover"] for it in others + [i for items in updates.values() for i in items]
                            if it["cover"]})

    where = "week " + str(week) if phase == "season" else phase
    print("Built docs/ for " + str(current.get("season")) + " " + where + ": "
          + str(len(teams)) + " teams, " + str(len(indexed)) + " seasons, "
          + str(len(career)) + " managers with career records, " + str(len(trade_log)) + " trades, "
          + str(sum(len(items) for items in updates.values())) + " commissioner updates, "
          + str(len(editions)) + " rule editions.")
    if D.pdfium is None:
        print("  pypdfium2 is not installed: no document covers, and no changes between rule editions.")
    for end in ends:
        print("  Trade Centre loose end: " + end["kind"] + " " + str(end.get("pick") or end.get("player_id")))
    # A Pro Bowl name nobody can be found for scores nothing, so say so loudly.
    for who in (game or {}).get("missing") or []:
        print('  Pro Bowl: no player found for "' + who + '". Add an alias in '
              "league.config.json -> pro_bowl.aliases.")
    # And one settled on the projection alone is worth a glance.
    for who in (game or {}).get("guessed") or []:
        print("  Pro Bowl: took " + who + " on this week's projection. Write the full name "
              "or add an alias if that is the wrong man.")

    # The jobs a settled season leaves, written where the workflow can pick them
    # up: they only come round once a year, which is what makes them easy to miss.
    jobs = season_todo(cfg, current, indexed, teams, phase)
    for job in (["\nEnd-of-season jobs:"] + ["  - " + j for j in jobs]) if jobs else []:
        print(job)
    # The workflow turns this into a GitHub issue, so the reminders reach Matt
    # rather than sitting in a build log. An empty file closes the issue.
    todo_file = os.environ.get("JADL_TODO_FILE")
    if todo_file:
        Path(todo_file).write_text("".join("- [ ] " + job + "\n" for job in jobs),
                                   encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
