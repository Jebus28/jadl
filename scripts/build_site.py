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
from datetime import datetime, timezone
from pathlib import Path

import stats as S

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DOCS = ROOT / "docs"
ASSETS = ROOT / "assets"

SLOT_ELIGIBILITY = {
    "QB": {"QB"}, "RB": {"RB"}, "WR": {"WR"}, "TE": {"TE"}, "K": {"K"}, "DEF": {"DEF"},
    "FLEX": {"RB", "WR", "TE"},
    "WRRB_FLEX": {"RB", "WR"},
    "REC_FLEX": {"WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}


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


def optimal_points(entry, roster_positions, players):
    scores = entry.get("players_points") or {}
    if not scores:
        return 0.0
    pool = []
    for pid, score in scores.items():
        pos = (players.get(pid) or {}).get("position")
        if pos:
            pool.append((pid, pos, float(score or 0)))
    pool.sort(key=lambda row: row[2], reverse=True)
    slots = sorted((s for s in roster_positions if s in SLOT_ELIGIBILITY),
                   key=lambda s: len(SLOT_ELIGIBILITY[s]))
    used, total = set(), 0.0
    for slot in slots:
        for pid, pos, score in pool:
            if pid not in used and pos in SLOT_ELIGIBILITY[slot]:
                used.add(pid)
                total += score
                break
    return round(total, 2)


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
            "image": conf.get("image"), "portrait": conf.get("portrait"),
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
                         "optimal": optimal_points(a, positions, players)},
                "away": {"roster_id": b["roster_id"], "points": round(float(b.get("points") or 0), 2),
                         "optimal": optimal_points(b, positions, players)},
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


NAV = [("index.html", "Scoreboard"), ("standings.html", "Standings"),
       ("teams.html", "Teams"), ("history.html", "History")]


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


def honours_section(cfg):
    champs = cfg.get("champions", {})
    consolation = (cfg.get("side_competitions") or {}).get("consolation_by_season", {})
    year = str(cfg["season"]["year"])
    note = "Every champion since " + str(cfg["league"]["established"]) + "."
    cards = []
    for season in sorted(set(list(champs) + [year])):
        winner = champs.get(season)
        trophy = consolation.get(season) or ""
        current = season == year and not winner
        cap = "In progress" if current else "Champion"
        extra = '<span class="trophy">' + e(trophy) + "</span>" if trophy else ""
        cards.append(f"""
      <div class="yr{' current' if current else ''}">
        <span class="season">{e(season)}</span>
        <span class="winner">{e(winner) if winner else "&mdash;"}</span>
        <span class="cap">{cap}</span>{extra}
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


def team_page(cfg, team, career, names):
    s = career.get(team["user_id"])
    conf = cfg["conferences"].get(team["division"], {})
    portrait = ('<img class="hero" src="assets/teams/' + e(team["portrait"])
                + '" alt="' + e(team["manager"]) + '" loading="lazy">') if team.get("portrait") else ""

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
        ("Playoffs", str(s["playoff_appearances"]) + " apps, " + rec(s["playoffs"])),
        ("Trades", str(s["trades"])),
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
    {portrait}
    <div class="teamtitle">
      <span class="eyebrow">{e(conf.get('name',''))}</span>
      <h1>{e(team['team'])}</h1>
      <p class="lede">{e(team['manager'])} &middot; {rec(s['career'])} all-time &middot; {len(s['seasons_played'])} seasons</p>
    </div>
  </section>

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
        portrait = ('<img class="portrait" src="assets/teams/' + e(t["portrait"])
                    + '" alt="" loading="lazy">') if t.get("portrait") else ""
        cards.append(f"""
      <a class="teamcard" href="team-{e(t['slug'])}.html">
        {portrait}
        <div class="who">
          <div class="team">{e(t['team'])}</div>
          <div class="mgr">{e(t['manager'])} &middot; {e(conf.get('name',''))}</div>
        </div>
        <dl class="teamstats">
          <div><dt>This year</dt><dd class="num">{t['wins']}&ndash;{t['losses']}</dd></div>
          <div><dt>All-time</dt><dd class="num">{alltime}</dd></div>
          <div><dt>Power</dt><dd class="num">{rank_by.get(t['roster_id'], '&mdash;')}</dd></div>
        </dl>
      </a>""")
    return ("<section>" + sechead("Teams", "Ten franchises, two conferences.")
            + '<div class="teamgrid">' + "".join(cards) + "</div></section>")


def history_sections(cfg, indexed, names):
    side = cfg.get("side_competitions") or {}
    consolation = side.get("consolation_by_season", {})
    spoon = side.get("wooden_spoon", "Loser of All Losers")
    blocks = []
    for season in sorted(indexed, key=lambda s: s["season"], reverse=True):
        table = S.season_table(season)
        if not table:
            continue
        era_key = "bce" if season["era"] == "bce" else "conference"
        era = cfg["eras"].get(era_key, {})
        rows = []
        for row in table:
            conf = cfg["conferences"].get(row["division"], {})
            badge = ""
            if row["place"] == 10:
                badge = '<span class="badge spoon">' + e(spoon) + "</span>"
            elif row["place"] == 7 and consolation.get(str(season["season"])):
                badge = '<span class="badge trophy">' + e(consolation[str(season["season"])]) + "</span>"
            conf_cell = e(conf.get("short", "")) if season["era"] != "bce" else "&mdash;"
            rows.append(f"""<tr>
              <td class="num">{row['place']}</td>
              <td><div class="tm"><span class="nm">{e(names.get(row['owner_id']) or 'Unknown')}</span>{badge}</div></td>
              <td>{conf_cell}</td>
              <td class="num">{row['wins']}&ndash;{row['losses']}</td>
              <td class="num">{row['fpts']:,.2f}</td>
              <td class="num">{row['max_points']:,.2f}</td>
            </tr>""")
        blocks.append(f"""
  <section>
    {sechead(str(season['season']) + " Season", era.get('label',''))}
    <div class="tablewrap"><table>
      <thead><tr><th>#</th><th>Manager</th><th>Conf</th><th>W&ndash;L</th><th>PF</th><th>Max PF</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table></div>
  </section>""")
    return "".join(blocks)


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
    indexed = [S.index_season(s, conference_from) for s in all_seasons]
    trades = S.count_trades([s.get("transactions") for s in all_seasons], indexed)
    career = S.all_time(indexed, trades)

    teams = manager_lookup(cfg, current.get("users", []), current.get("rosters", []))
    names = {uid: conf.get("name") for uid, conf in (cfg.get("managers") or {}).items()}
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
            + power_section(cfg, rankings) + honours_section(cfg))
    (DOCS / "index.html").write_text(page(cfg, "Scoreboard", "Scoreboard", home), encoding="utf-8")

    (DOCS / "standings.html").write_text(
        page(cfg, "Standings", "Standings",
             standings_section(cfg, teams, str(cfg["season"]["year"]) + " Standings")), encoding="utf-8")

    (DOCS / "teams.html").write_text(
        page(cfg, "Teams", "Teams", teams_index(cfg, teams, rankings, career)), encoding="utf-8")

    for team in teams.values():
        (DOCS / ("team-" + team["slug"] + ".html")).write_text(
            team_page(cfg, team, career, names), encoding="utf-8")

    history_body = (honours_section(cfg)
                    + "<section>" + sechead("The two eras") + era_note(cfg) + "</section>"
                    + history_sections(cfg, indexed, names))
    (DOCS / "history.html").write_text(page(cfg, "History", "History", history_body), encoding="utf-8")

    print("Built docs/ for " + str(current.get("season")) + " week " + str(week) + ": "
          + str(len(teams)) + " teams, " + str(len(indexed)) + " seasons, "
          + str(len(career)) + " managers with career records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
