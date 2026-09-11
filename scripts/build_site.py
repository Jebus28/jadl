#!/usr/bin/env python3
"""
Turn data/ + league.config.json into the published site in docs/.

Everything a human might want to change from season to season lives in
league.config.json. Nothing in here needs editing year to year.
"""
from __future__ import annotations

import html
import json
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import documents as D
import stats as S

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DOCS = ROOT / "docs"
ASSETS = ROOT / "assets"
RECORDS = ASSETS / "records"


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
    The team logo as Sleeper shows it: the team's own logo in this league. Where
    a team has none, the logo named for that manager in league.config.json (a
    file in assets/teams/), and failing that the manager's Sleeper picture.
    Sleeper's are linked, not copied, so a logo uploaded there is on the site at
    the next refresh and takes over from the config one.
    """
    meta = user.get("metadata") or {}
    if meta.get("avatar"):
        return meta["avatar"]
    if own and (ASSETS / "teams" / own).exists():
        return "assets/teams/" + own
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
            # The AI crest is for the Scoreboard only; everywhere else has Sleeper's logo.
            "image": conf.get("image"), "logo": sleeper_logo(user, conf.get("logo")),
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


def power_rankings(teams, results, upto):
    tally = {rid: {"score": 0.0, "weeks": 0, "wins": 0} for rid in teams}
    for wk in sorted(results):
        if wk > upto:
            break
        for fx in results[wk]:
            if fx["home"]["points"] == 0 and fx["away"]["points"] == 0:
                continue
            for side, other in (("home", "away"), ("away", "home")):
                rid = fx[side]["roster_id"]
                if rid not in tally:
                    continue
                mine, theirs = fx[side]["points"], fx[other]["points"]
                if mine > theirs:
                    tally[rid]["wins"] += 1
                tally[rid]["score"] += ((tally[rid]["wins"] + mine) / 2) - theirs
                tally[rid]["weeks"] += 1
    rows = [dict(teams[rid], power=round(t["score"] / max(t["weeks"], 1), 2), played=t["weeks"])
            for rid, t in tally.items()]
    rows.sort(key=lambda r: r["power"], reverse=True)
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows


NAV = [("index.html", "Scoreboard"), ("standings.html", "Standings"), ("teams.html", "Teams"),
       ("updates.html", "Commissioner Updates"), ("trades.html", "Trade Centre"),
       ("history.html", "History"), ("records.html", "Records"), ("rules.html", "Rules")]


def page(cfg, title, active, body):
    league, season = cfg["league"], cfg["season"]
    stamp = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    bits = []
    for href, label in NAV:
        attr = ' aria-current="page"' if label == active else ""
        bits.append('<a href="' + href + '"' + attr + '>' + label + "</a>")
    return f"""<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} &middot; {e(league['short_name'])}</title>
<meta name="description" content="{e(league['name'])} &mdash; {e(cfg['site']['tagline'])}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&family=Public+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<link rel="stylesheet" href="assets/site.css">
</head>
<body>
<header class="masthead">
  <div class="wrap">
    <div class="brand">
      <a class="mark" href="index.html">{e(league['short_name'])}</a>
      <span class="full">{e(league['name'])} &middot; est. {e(league['established'])}</span>
    </div>
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


def crest(team, cfg):
    conf = cfg["conferences"].get(team["division"], {})
    cls = "lc" if team["division"] == "1" else "mc"
    if team.get("image"):
        return '<img class="crest img" src="assets/teams/' + e(team["image"]) + '" alt="" loading="lazy">'
    return '<div class="crest ' + cls + '">' + e(conf.get("short", "")) + "</div>"


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


def scoreboard(cfg, teams, results, week, career, prev_finish):
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
          {crest(home, cfg)}
          <div class="who">
            <div class="team"><a href="team-{e(home['slug'])}.html">{e(home['team'])}</a></div>
            <div class="mgr">{e(home['manager'])} &middot; {home['wins']}&ndash;{home['losses']} &middot; {e(places.get(home['roster_id'], ''))}</div>
          </div>
          <div class="score {'lead' if hp >= ap else 'trail'}">{hp:.2f}</div>
        </div>
        <div class="vs">vs{h2h}</div>
        <div class="side away">
          {crest(away, cfg)}
          <div class="who">
            <div class="team"><a href="team-{e(away['slug'])}.html">{e(away['team'])}</a></div>
            <div class="mgr">{e(away['manager'])} &middot; {away['wins']}&ndash;{away['losses']} &middot; {e(places.get(away['roster_id'], ''))}</div>
          </div>
          <div class="score {'lead' if ap >= hp else 'trail'}">{ap:.2f}</div>
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


def power_section(cfg, rankings):
    if not rankings or all(r["played"] == 0 for r in rankings):
        return ""
    top = max((abs(r["power"]) for r in rankings), default=1) or 1
    rows = []
    for r in rankings:
        width = max(2, min(100, (r["power"] / top) * 100)) if r["power"] > 0 else 2
        rows.append(f"""
      <div class="prrow{' top' if r['rank'] == 1 else ''}">
        <div class="prrank num">{r['rank']}</div>
        <div class="prname"><a href="team-{e(r['slug'])}.html">{e(r['team'])}</a> <span class="hd">{e(r['manager'])}</span></div>
        <div class="bar"><span style="width:{width:.0f}%"></span></div>
        <div class="prpts">{r['power']:+.1f}</div>
      </div>""")
    return ("<section>" + sechead("Power Rankings", "Your workbook formula, computed on real results.")
            + '<div class="pr"><div class="prrow prhead"><div class="prrank">#</div><div class="prname">Team</div>'
            + '<div class="bar" style="border:0;background:none"></div><div class="prpts">Score</div></div>'
            + "".join(rows) + "</div></section>")


def placed(season, place):
    """Whoever finished in `place` once the placement games were played, or None."""
    return next((uid for uid, p in season["final"].items() if p == place), None)


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


def teams_index(cfg, teams, rankings, career):
    rank_by = {r["roster_id"]: r["rank"] for r in rankings}
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
    side = cfg.get("side_competitions") or {}
    consolation = side.get("consolation_by_season", {})
    spoon = side.get("wooden_spoon", "Loser of All Losers")
    blocks = []
    for season in sorted(indexed, key=lambda s: s["season"], reverse=True):
        table = S.season_table(season)
        if not table:
            continue
        year = season["season"]
        in_conferences = season["era"] == "conference"
        era = cfg["eras"].get(season["era"], {})
        division_of = {row["owner_id"]: row["division"] for row in table}
        cup = consolation.get(str(year)) or "Consolation bracket"
        first_loser = season["playoff_teams"] + 1
        last = len(season["final"])

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

        # Final standings: settled in the playoffs and the toilet bowl.
        fin_rows = []
        for uid, place in sorted(season["final"].items(), key=lambda kv: kv[1]):
            badge = ""
            if place == 1:
                badge = '<span class="badge trophy">Champion</span>'
            elif place == first_loser:
                badge = '<span class="badge trophy">' + e(cup) + "</span>"
            elif place == last:
                badge = '<span class="badge spoon">' + e(spoon) + "</span>"
            conf_cell = "<td>" + e(short(uid)) + "</td>" if in_conferences else ""
            fin_rows.append(f"""<tr>
              <td class="num">{ordinal(place)}</td>
              <td><div class="tm"><span class="nm">{e(who(uid))}</span>{badge}</div></td>{conf_cell}
            </tr>""")
        fin_card = finish_card("Final standings", "Settled in the playoffs and the toilet bowl.",
                               "<th>Pos</th><th>Manager</th>" + ("<th>Conf</th>" if in_conferences else ""),
                               fin_rows)

        # The honours: champion and Loser of All Losers with their pictures, then
        # the conference winners and the 1.01.
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

        blocks.append(f"""
  <section class="seasonblock">
    {sechead(str(year) + " Season", era.get('label', ''))}
    <div class="seasonhonours">{''.join(podium)}</div>
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

    week = int(state.get("week") or 1)
    if str(state.get("season")) != str(current.get("season")):
        week = cfg["season"]["regular_season_weeks"]
    week = max(1, min(week, cfg["season"]["championship_week"]))
    rankings = power_rankings(teams, results, week)

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

    home = (scoreboard(cfg, teams, results, week, career, prev_finish)
            + power_section(cfg, rankings) + honours_section(cfg, indexed, names))
    (DOCS / "index.html").write_text(page(cfg, "Scoreboard", "Scoreboard", home), encoding="utf-8")

    (DOCS / "standings.html").write_text(
        page(cfg, "Standings", "Standings",
             standings_section(cfg, teams, str(cfg["season"]["year"]) + " Standings")), encoding="utf-8")

    (DOCS / "teams.html").write_text(
        page(cfg, "Teams", "Teams", teams_index(cfg, teams, rankings, career)), encoding="utf-8")

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

    print("Built docs/ for " + str(current.get("season")) + " week " + str(week) + ": "
          + str(len(teams)) + " teams, " + str(len(indexed)) + " seasons, "
          + str(len(career)) + " managers with career records, " + str(len(trade_log)) + " trades, "
          + str(sum(len(items) for items in updates.values())) + " commissioner updates, "
          + str(len(editions)) + " rule editions.")
    if D.pdfium is None:
        print("  pypdfium2 is not installed: no document covers, and no changes between rule editions.")
    for end in ends:
        print("  Trade Centre loose end: " + end["kind"] + " " + str(end.get("pick") or end.get("player_id")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
