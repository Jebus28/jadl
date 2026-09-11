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

import stats as S

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DOCS = ROOT / "docs"
ASSETS = ROOT / "assets"
RECORDS = ASSETS / "records"

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
       ("teams.html", "Teams"), ("history.html", "History"), ("records.html", "Records")]


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
    trades = S.count_trades(transactions, indexed)
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
            + power_section(cfg, rankings) + honours_section(cfg, indexed, names))
    (DOCS / "index.html").write_text(page(cfg, "Scoreboard", "Scoreboard", home), encoding="utf-8")

    (DOCS / "standings.html").write_text(
        page(cfg, "Standings", "Standings",
             standings_section(cfg, teams, str(cfg["season"]["year"]) + " Standings")), encoding="utf-8")

    (DOCS / "teams.html").write_text(
        page(cfg, "Teams", "Teams", teams_index(cfg, teams, rankings, career)), encoding="utf-8")

    for team in teams.values():
        (DOCS / ("team-" + team["slug"] + ".html")).write_text(
            team_page(cfg, team, career, names), encoding="utf-8")

    history_body = (honours_section(cfg, indexed, names)
                    + "<section>" + sechead("The two eras") + era_note(cfg) + "</section>"
                    + history_sections(cfg, indexed, names))
    (DOCS / "history.html").write_text(page(cfg, "History", "History", history_body), encoding="utf-8")

    waiver = S.waiver_record(transactions, indexed, players)
    (DOCS / "records.html").write_text(
        page(cfg, "Records", "Records", records_page(cfg, indexed, career, names, waiver, players)), encoding="utf-8")

    print("Built docs/ for " + str(current.get("season")) + " week " + str(week) + ": "
          + str(len(teams)) + " teams, " + str(len(indexed)) + " seasons, "
          + str(len(career)) + " managers with career records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
