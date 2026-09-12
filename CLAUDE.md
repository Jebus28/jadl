# JADL — project context

Read this first. It carries the decisions and league knowledge that aren't obvious
from the code, and that took a long conversation to establish.

## What this is

A self-updating website for the **Jessica Alba Dynasty League (JADL)**, a ten-team
superflex dynasty NFL fantasy league run by Matt Redmond (@Jebus28), commissioner
since 2020.

It replaces a Google Site at `sites.google.com/view/ja-dynasty-league` that Matt
maintained by hand — copying numbers out of Sleeper into Excel and Google Sheets,
then retyping them into web pages, weekly in season and ad hoc out of it.

**The goal is that Matt never types a number again.** Anything derivable from
Sleeper must be computed, not stored. If you find yourself adding a hand-entered
statistic, you have almost certainly taken a wrong turn.

The old site is still live and is the reference for what the new one should cover.
It is worth reading before making changes.

## How it runs

```
python scripts/fetch_data.py    # Sleeper  -> data/*.json
python scripts/build_site.py    # data/ + league.config.json -> docs/*.html
```

`.github/workflows/refresh.yml` runs both on a schedule — every two hours on
Sundays, Mondays and Thursdays, daily at 07:30 UTC otherwise, and on every push —
then commits `data/` and `docs/` back to `main`. GitHub Pages serves `docs/` at
<https://jebus28.github.io/jadl/>.

Sleeper's read API needs no key and no account. Base URL `https://api.sleeper.app/v1`.

### Layout

| Path | What it is |
|---|---|
| `league.config.json` | **The only file Matt should ever need to edit**, and even the season and league ID look after themselves now (see "The off-season, and rolling into a new season"). Conferences, managers, divisional-week names, consolation trophy names, and the draft-day trades Sleeper never recorded (`manual_trades`). Champions are *not* in it — they come from the brackets. |
| `scripts/fetch_data.py` | Works out which league is the current one (walking *forward* from the config), then pulls league, users, rosters, matchups, brackets, trades, completed waiver claims, cross-team commissioner moves and the rookie drafts for every season, walking `previous_league_id` back to 2020. Also Sleeper's player projections for the regular-season weeks still to play (`data/projections.json`), for the playoff odds. |
| `scripts/stats.py` | All-time maths: career records, era splits, head-to-head, trades, season tables, team honours. |
| `scripts/build_site.py` | Renders the HTML. |
| `scripts/prepare_media.py` | Turns a champion GIF or loser photo into `assets/records/<season>-<champion\|loser>.*` — GIFs become silent looping WebPs under 2.5MB, photos are straightened and shrunk. |
| `assets/records/` | One champion loop and one Loser of All Losers picture per season, found by filename. No config entry. |
| `scripts/documents.py` | Reads the two document tabs' files: PDF dates, covers and text, `.url` shortcuts, the rulebook's Word file, and the changes between editions. |
| `assets/updates/<season>/` | The Commissioner Updates: PDFs, and `.url` shortcuts to the videos on Drive. Found by folder. No config entry. |
| `assets/rules/` | Every edition of the rulebook as a PDF, the Word file of the current one, and the auction procedure. |
| `docs/assets/covers/` | First-page pictures of the PDFs, drawn by the build and named by content hash so each is drawn once. |
| `assets/site.css` | One stylesheet, themed light and dark via CSS custom properties. |
| `assets/league/` | `league-logo.jpg`, the league logo exactly as Matt made it, named by `league.logo` in the config. |
| `assets/teams/` | `<manager>.jpg`, the AI pictures, shown whole on the Scoreboard; `<manager>-crest.jpg` square crops, now only a fallback; and `<manager>-logo.*`, team logos that override Sleeper's. |
| `data/` | Fetched JSON. Committed so builds are reproducible; regenerated every run. The exception is `data/power_rankings.json`, which the build writes and never rewrites: a week's power ranking is fixed at noon on Wednesday and has to survive later builds. |
| `docs/` | Generated output. **Never edit by hand** — it is overwritten. |

## League knowledge

This is the part you cannot infer from the data. Get it wrong and the site is wrong.

### The two eras

The league has **two** eras, not three:

- **BCE** — Before the Conference Era. Seasons one and two, **2020 and 2021**.
  No conferences; everyone played everyone.
- **The Conference Era** — **2022 onward**, when the league split into the
  **Lombardi (LFC)** and **Madden (MFC)** conferences.

`league.config.json` → `eras.conference_from` is `2022`.

Head-to-head records are shown **three ways** because of this, which is not the
same as three eras: against your own conference, against the other conference
(both conference-era, regular season only), and BCE. Matt corrected this
explicitly — say "two eras, three tables".

**Playoff and toilet bowl records span all of history** and are not split by era.

### Terminology — use Matt's words

- The losers bracket is the **toilet bowl**, never "consolation".
- Conferences are **LFC** and **MFC** in record books (the old site's page names
  use LC/MC, but the stats blocks say LFC/MFC).
- 10th place is always **Loser of All Losers**.
- 7th place wins the **consolation bracket** and takes the **1.01 pick**. The
  trophy is renamed every year after the leading college prospect:
  2020 Trevor Trophy (Trevor Lawrence), 2021 Corral Cup, 2022 Bijan Bowl,
  2023 Caleb Cup, 2024 Shedeur Bowl, 2025 Mendoza Marathon (Chris's old team
  page called it the Love Bowl; Matt confirmed Mendoza Marathon). 2026 is TBC —
  candidates were Arch Manning and Jeremiah Smith. A blank name shows as
  "Consolation bracket" — 7th is still an honour.

### Two sets of finishes

Matt's rule: a season has **two** sets of finishes and they are held separately.

- **Regular season** — on record (then points for), within each conference in
  the conference era. Its only honour is **conference winner** (LFC and MFC).
- **Final standings** — settled in the playoffs and the toilet bowl, read from
  the bracket placement games (`stats.final_places`). Winners bracket p=1/3/5
  give 1st–6th; the losers bracket advances its winners, so its p=1 game is for
  **7th** (the 1.01) and the loser of its p=3 game is **10th**, Loser of All Losers.

The only honours are those four: conference winners, champion, 7th and 10th.
Topping the table does not make you champion and finishing bottom of it does not
make you Loser of All Losers. The first history page got this wrong — it badged
the regular-season 10th and 7th — which misnamed three Losers of All Losers
(2021, 2022, 2025) and gave the 2022 Bijan Bowl to a playoff team.

Regular-season honours (conference titles) belong on the **team pages**, not
History — Matt asked for that in September 2026, and they are there now, in the
Honours cabinet below.

### Team honours (team-*.html)

Rebuilt in September 2026 from the Honours block on the old team pages. All
computed, in `stats.honours` and `stats.best_managers`, and each honour appears
only once it is settled:

- From the brackets, once every placement game is played: **champion** (with
  the final's score), the **consolation bracket** (7th and the 1.01, under that
  year's cup name) and **Loser of All Losers**.
- From the finished regular season: the **regular-season winner**, each
  conference's in the conference era and the whole league's in BCE, with its
  record; and the **top scorer**, on Sleeper's own season total.
- From the finished season, every game counting as in the record books: the
  **weekly high score**, the **weekly low score** and the **player high score**
  (starters only).
- **Best Manager** is weekly: the regular-season week's highest score as a
  share of max points. That is the rule in Matt's 2025 and 2026 workbooks (the
  Awards sheet's Manager Best, from each Week sheet's PF/MPF). Max points is
  worked out as Sleeper does it: the best lineup from every rostered player's
  score, a player filling his position or any position he was started at that
  season. Sleeper now files Travis Hunter as a DB, though he played WR in 2025.
- A gold star beside the team name for each championship, as the old pages had.

Checked against all ten old pages in September 2026. Every honour they list
matches, and they had missed several since: the 2023 and 2024 Losers of All
Losers, the Caleb Cup and Shedeur Bowl winners, Alex's 2024 LFC title, Lee's
2023 top score, Ross's 2024 player high and Gareth's 2024 low. Two differences,
both the old pages':

- Neil's 2021 weekly low, 64.70, was in week **12**, not 11.
- **Best Manager in 2020 and 2024.** Matt picked those two seasons on fewest
  points missed rather than share of max points; 2021–23 and 2025 match exactly.
  The site applies one rule to every season, so seven managers' 2020 counts
  change (Chris 2→1, Dave 0→1, Gareth 0→1, Mike 3→1, Neil 3→2, Rich 1→2,
  Ross 1→2) and two in 2024 (Chris 2→1, Neil 0→1). Matt confirmed this in September 2026: one rule, share of max
  points, for every season. Do not bring back the old 2020 and 2024 counts.

Max points summed over a season match Sleeper's own total (roster `ppts`) for
all but a few team-seasons: Mike 2020 (+31.94) and 2021 (+23.12), Gareth 2023
(+12.48) and 2024 (+22.18), and four more by a point or two. Not traced. It
changes no Best Manager in the seasons that could be checked.

### The record books (Records tab)

Rebuilt from the Google Sheets embedded on the old History page — Record Low
Scores, Low Scores – 2 Flex, Season High Scores, Dominator, Loser-minator, Mind
the Gap, Streakers — plus the hand-typed waiver record and Sleeper's all-time
standings (a screenshot on the old page). All computed, in `stats.py`'s record
book functions. The rules, as Matt's sheets use them:

- Single-week scores, margins and streaks count **every game**: regular season,
  playoffs and toilet bowl. Season tables are regular season only.
- **Points per player per game** divide by the starting slots less DEF (a team,
  not a player): 9 in the one-flex years 2020–22, 10 from 2023. Dominators rank
  on win %, then that; Loser-minators the other way up.
- Streaks carry across seasons. A playoff bye is no game.
- **Best player weeks** are starters only (Sleeper's `starters_points`, kept per
  side in `index_season` as `lineups`), in games that count. Bench points and
  playoff-week games outside both brackets won nothing, so they set no record.
- Season totals are Sleeper's own figure (roster `fpts`), as on History and
  Standings. Summing the games can differ — by a point where a stat correction
  landed late (Lee 2023: 2,065.96 official, 2,066.96 summed; the sheet has the
  official one) or by a hundredth of rounding (Mike 2025: 2,095.99 official,
  2,096.00 summed; the sheet has the sum). Career PF/PA, as on the team pages,
  are summed from the games.

Checked line by line in September 2026. Every row matched except these, where
the data shows the sheet is wrong: Alex's 57.36 and Gareth's 64.46 were 2022
week **9**, not 10; the two-flex low-score sheet misses Alex's 69.60 in 2023
week 3 (the losing side of Lee's 120.60 win, #2 in Mind the Gap); Ross's 2020
run is **7** wins — the sheet's 8 counts his week-14 bye; Chris's 10-game losing
run began in week 6, not 5; and Mike 2025 as above. The all-time standings
screenshot (through 2024) matched every W–L;
PF/PA differ by 1–3 points for five managers, most likely Sleeper stat
corrections since. The waiver record needs completed waiver claims, which
`fetch_data.py` now keeps (it used to keep trades only).

### The Trade Centre (trades.html)

Rebuilt from the old Trade Centre in September 2026: the **Trade League Table**
(a Google Sheet — trades, players in, picks in, players out, picks out, with LFC
and MFC totals) and every trade as a picture of Sleeper's trade card, grouped
into windows and numbered within each window oldest first. The new page keeps
all of that, computed, and resolves each traded pick to the player taken with
it once the draft is done (`stats.draft_board`, from the rookie drafts).

- **Windows**: each season, and the off-season before it ("2024/25 off-season").
  Sleeper files everything from a league's creation to the end of week one under
  leg 1, so a leg-1 trade is in-season only once kickoff day is over
  (`stats.kickoff`: Sleeper's own date for the current season, otherwise the
  Thursday after Labor Day). Two trades sit differently on the old page: the
  5 Sep 2021 Henderson–Jones swap (before kickoff, so 2020/21 off-season here)
  and one 2022 in-season trade the old page never posted.
- **Defences count as players** in the table. It matches the old sheet better.
- **Manual trades.** Some deals were done by hand on draft day — picks moved in
  the draft room, players by commissioner move — so Sleeper has no trade for
  them. There are eight, in `league.config.json` → `manual_trades`: Henderson for
  three picks in the 2022 draft, and seven in the 2024 draft (the old page's
  2023/24 section is one Sleeper trade and seven seesaw graphics of these). They
  were found in the data — a draft pick made by someone the trades never gave it
  to, and commissioner moves between two teams — then matched to Matt's graphics.
  `stats.trade_loose_ends` repeats that check on every build and the page lists
  anything unexplained, so a future draft-day deal shows up rather than going
  missing.
- **One loose end is known and deliberate**: 2024 pick 2.09 (Mike's original
  2nd, MarShawn Lloyd). Neil held it going into the draft, Chris made it, and no
  graphic covers it. Matt can't remember how, so it stays listed until he does.

Checked against the old sheet: it runs to the end of 2025 and counts the
draft-day trades. On that basis Dave, Jebus, Mike and Rich match on every
column; everyone else is within one or two on a column, which the sheet being
kept by hand explains.

Champion GIFs and loser pictures in `Website\Winners and Losers\` were matched to
seasons by file date and the brackets. As of September 2026 there is no 2025
loser picture; drop one in with `prepare_media.py` and the page picks it up.

### Commissioner Updates and Rules (updates.html, rules.html)

Rebuilt in September 2026. On the old site both were pages of Drive embeds: Rules
had the 5th to 8th editions of the rulebook, each with a one-line note on what
changed, plus the auction procedure; Commissioner Updates had a page a season of
PDFs and a few videos. Now both are files in `assets/`, read by
`scripts/documents.py`, with nothing in `league.config.json`.

- **Updates** live in `assets/updates/<season>/`. A PDF's title is its file name,
  title-cased, and its date is Word's creation stamp inside the PDF, which puts
  the season in order, newest first. The videos are 400–800MB, too big for
  GitHub, so they stay on Drive as `.url` shortcuts with a `Date=` line. A
  shortcut with no date goes to the top of its season, as just added.
- **One season at a time.** Matt found one long page of every season too much
  (September 2026), so the season chips are tabs. The page opens on the newest
  season, `updates.html#season-2023` opens 2023, and each season ends with a
  link to the one before. With no script every season shows.
- **What's in:** everything the old site posted, plus documents of the same
  kind it never got round to: the 2023 Season Preview, both 2025 mid-season
  reviews, the 2025 Regular Season Review, and the 2026 schedule, draft preview
  and season preview. **Left out**, pending Matt: the AGM agendas and minutes,
  and four Drive videos the old site never posted (the 2020 and 2021 season
  reviews, a January 2023 video and the 2023 hype video), since their Drive
  sharing is unknown.
- **The rulebook** is set out from its Word file (`assets/rules/*.docx`; the
  newest edition wins), numbered exactly as Word numbers it. The rules cite each
  other by paragraph ("subject to para 40"), so `rules.html#rule-40` is paragraph
  40 and those references are links. Checked against the 8th Edition PDF: all 99
  numbered paragraphs (92 rules, plus the tiebreakers and sanctions) match.
- **Editions come from the PDFs, not the Word files.** Matt's Word files were
  saved over: the 2023 file holds the 8th Edition, and the 2022 and 2022a files
  both say 6th. Only the PDFs are a true record. Each edition's label is read
  from its PDF, and what changed is a word diff with the contents page, running
  heads and paragraph numbers taken out. The 2022a PDF is a February 2023
  revision of the 6th Edition (a 26-man roster and the second flex), listed as
  revised. The diffs reproduce the old site's notes: the 7th Edition added
  sanctions and the 8th amended roster cuts.
- **On Sleeper** shows the lineup, bench, IR, taxi, FAAB, playoffs, draft rounds
  and every scoring setting, read from the league settings. As of September 2026
  the rulebook disagrees with Sleeper twice. It says **5** IR slots where Sleeper
  has **8** (the 2026 AGM agreed three more), and it never mentions the **0.5 TE
  premium**. The page shows each as it stands; the rulebook is Matt's to update.
- The workflow installs pypdfium2 and Pillow for the covers and the diffs.
  Without them the build still runs, with neither.

### Divisional weeks and the playoff rounds

Weeks **10 to 14** are divisional weeks. Four of the five games each week are
in-conference. The fifth is an inter-conference game between the two teams that
finished in **the same place in their own conference last season** — the two
fifth-placed teams meet in week 10, working up to the two conference winners in
week 14. Matt schedules all of this by hand in Sleeper months ahead, so the
fixtures are already in the data: the site **recognises** that pairing, it does
not compute it. Verified against 2023, 2024, 2025 and 2026 — it holds in every
one. Week 9 also carries a cross-conference game, but it is not rank-matched and
must not be billed.

Each of those five games has a name, in `league.config.json` →
`divisional_weeks.names`, keyed by last season's conference finishing position
rather than by week, so a name follows the teams if Matt ever reorders the weeks.
He named two of them; the rest are placeholders for him to overwrite.

In those weeks the scoreboard is **grouped**: the named inter-conference game
leads, then the LFC fixtures under a Lombardi header, then the MFC fixtures
under a Madden header. Every other week is a flat list. The headers are the
conference crests, `assets/conferences/{lfc,mfc}.png`, pointed at from
`conferences.*.crest`.

### The stars on the conference crests

**The stars are data, not decoration.** They count the championships won by the
managers *currently in that conference*, so they move when someone changes
conference and grow when someone wins. As of the 2026 season: LFC 2 (Dave 2021,
Mike 2025), MFC 4 (Jebus 2022–24, Ross 2020). That is total titles, not the
number of distinct winners — both conferences have two distinct winners.

The crests in `assets/conferences/` were cut from Matt's artwork in
`Website\League Logos\` (`LFC 2.png` and `MFC 4.JPG` — the filenames carry the
star count, and other files in there have the wrong number). **They are static,
so they will go stale the moment the count changes.** The right fix is to draw
the stars over a starless crest from the computed figure; `IMG_3384.PNG` in that
folder is a starless M and would be a starting point. Until that is done, check
the crests whenever a season ends.

The **league logo** carries the same stars, on its L and its M, so it goes stale
with them. Matt makes a new one after each final (`JADL 5.JPG` after 2024,
`JADL 6.jpg` after 2025, in the same folder); copy the newest over
`assets/league/league-logo.jpg` unchanged.

Playoffs run **in conference** until the final and the toilet bowl itself:
week 15 is the **Divisional Round**, week 16 the **Conference Championships**,
week 17 **The Championship**. These are in `playoff_rounds`, keyed by week.

Head-to-head shown on a fixture is **conference-era regular season only**
(2022 onward), not all-time. Matt asked for this explicitly.

### The managers

Ten managers, stable since 2020. Sleeper display names bear little relation to
real names, so `league.config.json` maps them by `user_id`:

| Manager | Sleeper | 2026 team |
|---|---|---|
| Jebus | Gebus | Raiders of the Lost Yard |
| Lee | LACol | J J F J |
| Alex | alnewbs | Toolsy Prospects |
| Dave | DJLan | breecetie boys |
| Mike | MikeJames42 | Tompa Bay Bucs |
| Chris | ChrisNewbrook | Falcons |
| Ross | Rossmatt1982 | The Rookies Nest |
| Neil | NeilMWelch | Canton Giants |
| Rich | dudders79 | Inch by inch |
| Gareth | SquirrelGman | Mandos |

Managers rename their teams most seasons, so **never key anything on team name** —
always `user_id`. Rich was previously listed as the manager name for dudders79 and
they are the same person.

### League format

10 teams, two conferences of five. Superflex. 0.5 PPR with a 0.5 TE premium.
K and DEF. 15 bench, 8 IR, 7 taxi. $1000 FAAB. Six playoff teams from Week 15.
Five-round rookie drafts. Seven seasons on Sleeper, 2020 through 2026, linked by
`previous_league_id`.

### Champions

2020 Ross, 2021 Dave, 2022–2024 Jebus (a three-peat), 2025 Mike. Computed from
the winners bracket; the hand-kept list in `league.config.json` was removed
once the computed one matched it.

### Power rankings (Scoreboard)

Rebuilt in September 2026 from the **Power Rankings tab of `Team Tracking 2026 -
altpr.xlsx`**, which had replaced the older cumulative formula. The site no
longer runs a season-long total up; it ranks the league afresh every week.

- **The formula**, read off the Week sheets' Score column (X) and ranked by
  column Y: `(the last two weeks you played + this week's projected points) / 3
  − your opponent's projected points that week`. Week 2 has only one week behind
  it, so it divides by 2. **Week 1 has none, so it is simply your projection
  less your opponent's** — the advantage the fixture gives you, highest first.
  One rule covers all fourteen weeks; `stats.power_rankings` is it.
- **Projected points** are Sleeper's projections for the best lineup a team can
  start (not IR, not taxi), the same feed the playoff odds use, scored with the
  league's own settings. The odds nudge that figure towards a team's real
  scoring; **the power rankings do not** — the workbook uses the raw projection.
- **A week is fixed at noon UK on the Wednesday before its games** and never
  moves again, however the projections shift afterwards. `stats.power_freeze`
  works the moment out: the Wednesday on or before Sleeper's own season start
  date (a Thursday most years, but **9 September in 2026**), plus seven days a
  week. `stats.uk_noon` handles BST without a `tzdata` dependency, so noon is
  11:00 UTC until the clocks go back and 12:00 after.
- **Each week is kept in `data/power_rankings.json`**, written by
  `build_site.power_store` on the first build past the freeze and left alone
  from then on. Sleeper only projects weeks still to come, so **a week missed at
  the time can never be filled in** — that is why `refresh.yml` has a
  `0 11,12 * * 3` cron. The file holds one season and starts itself again when
  the league rolls over.
- **Week 1 of 2026 is seeded** from Matt's workbook, since the site was not
  computing these yet. Recomputing it from the projections gives the same ten
  places in the same order, so the seed is belt and braces; leave it.
- **The page shows the week's ranking and the move on the week before, and
  nothing else** — Matt asked for exactly that in September 2026. The score is
  kept in the data file but not shown: every score is a large negative number
  (the opponent's whole projection is subtracted), which reads as nonsense. The
  old bar chart went with it.
- **The method stays off the site.** Matt asked in September 2026 that how the
  rankings are worked out is not published. The section note reads exactly
  "Week X — fixed at noon on Wednesday." and nothing more. This is the one
  place where the usual rule of explaining a computed figure on the page does
  not apply, so do not helpfully add the formula back.

### The off-season, and rolling into a new season

Built in September 2026. Three things used to need a human between one season
and the next; none of them does now.

**The league id finds itself.** `fetch_data.resolve_league` walks forward from
the `current_league_id` in `league.config.json`. Sleeper links each season back
to the one before but never forward, so the way on is
`/user/<user_id>/leagues/nfl/<season+1>`: whichever of a manager's leagues
points back at the one we hold. It only looks ahead once the league it holds is
`complete`, or the NFL has moved on a year, so an ordinary in-season refresh
costs one extra call. **Checked in September 2026 by walking from the 2020
league: it landed on 2026 through all six roll-overs.** So when Matt creates the
2027 league on Sleeper the site follows it by itself, and the id in the config
is only ever the starting point.

**The season's shape comes from Sleeper too.** `build_site.season_setup`
replaces `cfg["season"]` at the start of the build: the year from the league,
`playoff_start_week` and `playoff_teams` from its settings, the regular season
as the week before the playoffs and the championship week from the number of
rounds. The config values are the fallback and nothing more. Nothing in
`league.config.json` has to change from one season to the next.

**The Scoreboard knows where the year is.** `build_site.season_phase` reads it
off the games, not Sleeper's clock:

- `"over"` — every placement game is played, so the season is settled;
- `"season"` — games have been played, or kickoff has passed;
- `"preseason"` — the new league is up but nobody has played yet.

In `"season"` the front page is as it always was. In the other two it is
`offseason_home` instead: what is coming next (the rookie draft and kickoff,
with the days to each, or a line saying the next season is not on Sleeper yet),
the last settled season in review (the podium and the final standings), that
season's rookie draft pick by pick, and every trade in the off-season window.
Playoff odds and power rankings are not computed at all out of season. The
Honours cabinet stays on the bottom in every phase.

**The jobs a settled season leaves** are in `build_site.season_todo`, printed at
the end of every build and written to `$GITHUB_STEP_SUMMARY`, so they show on
the Actions run page. They are the ones that only come round once a year: the
champion's loop and the Loser of All Losers picture for
`scripts/prepare_media.py`, next year's consolation trophy name, and the
championships-by-conference count against the stars on the crests and the
league logo (see "The stars on the conference crests" — those are still
pictures, and still go stale). The list is empty while the season is on.

### Playoff odds (Scoreboard)

Built in September 2026 to replace the Dynasty Daddy screenshots Matt used to
paste in. Dynasty Daddy has no public API, so don't go looking for one. The
odds come from `stats.playoff_odds`. They show under each team on the fixtures
and as a table per conference, while regular-season games remain.
`site.show_playoff_odds` turns them off.

- **The simulation.** It plays the rest of the regular season (to week 14) out
  10,000 times on the real fixtures. Finished games count as they finished. A
  week in progress is played out in full, because live scores are not used.
  The seed is fixed, so a build is reproducible.
- **Expected score.** Sleeper's projected stats for each week, scored with the
  league's own settings (TE premium and all), taking the best lineup from the
  players a team can start (not IR, not taxi).
  - The projections come from `fetch_data.fetch_projections`, which reads
    `api.sleeper.app/projections/nfl/<season>/<week>`. That feed is not in
    Sleeper's documented API. It is saved in `data/projections.json` and
    refreshed at most every six hours, with the time kept inside the file.
  - The projection is nudged towards the team's actual scoring this season,
    by n/(n+8) of the gap after n games.
  - Where there is no projection for a week, the model uses this season's
    average, leaning on the league's. If the feed fails, the old file stays.
    If it's missing, every week falls back like that and the page says so.
- **Luck.** Every game gets the league's weekly swing, about 23 points. That
  is the spread of scores round each team-season's average, over the three
  seasons before. Every team in every run also gets a season-long drift,
  about 10 points a week. That is the year-on-year change in managers'
  averages, less the league-wide change, divided by √2.
- **Both figures are league-wide on purpose. Do not bring back per-team
  history.** Matt, September 2026: a team's own history is no guide to this
  year. His 2026 roster projects at about 104 a week against a 131 average
  last season. An earlier version used each team's own past swing and
  last season's average, and it was wrong for exactly that reason.
- **Places, rulebook paras 70–71.** Teams are ranked on wins, then total
  points; the later tiebreakers can't come into play in a simulation. The
  conference winners get the bye and second place is in. Third is in unless
  Rule 3 applies: a third-placed team below .500 while the other conference's
  fourth is above .500. Then that fourth takes the place.
- **Display.** Chances show as "<1%" and ">99%", never 0% or 100%, because a
  simulation is not a proof.
- **Checked in week 1 of 2026.** Every run hands out exactly six places and
  two byes, and 10,000 runs take half a second.

## Conventions

- **British English** throughout, in copy and in code comments.
- Everything that changes season to season lives in `league.config.json`. Matt
  regenerates team images every year and wants to do that himself without
  touching code. The season year, the league id and the playoff setup are no
  longer among them — Sleeper is the source for all three.
- **Team images: the AI pictures are for the Scoreboard only.** Matt asked for
  this in September 2026. The AI pictures (`portrait` in the config, the 1400px
  `<manager>.jpg` from his `Team AI` folder) are shown **whole and large** on
  every fixture: Matt spends a long time on them and wants the detail seen
  (September 2026). Never crop them. Each sits uncropped in a 3:2 frame, a
  portrait one over a blurred copy of itself (`build_site.shot`). The 320px
  square `<manager>-crest.jpg` crops (`image`) are only a fallback now.
- **Team logos** show everywhere else: the Teams cards, team pages and Trade
  Centre (`build_site.sleeper_logo`). They are always shown whole at their own
  shape, never cropped to a square. A `logo` file named for a manager in
  `league.config.json` (in `assets/teams/`) comes first. It is Matt's own
  artwork, for a team whose Sleeper logo is squared off or missing. Then the
  team's Sleeper logo (`user.metadata.avatar`, linked from Sleeper's CDN, so a
  new one shows at the next refresh), then the manager's Sleeper picture. As of
  September 2026 three teams have one:
  - **Jebus**: `jebus-logo.png`, a copy of `League Logos\ROTL 3.png`. Sleeper's
    square cut off half of "Raiders of the Lost Yard".
  - **Dave**: `dave-logo.jpg`, a copy of `Team Logos\72ca1498-….JPG`. Sleeper's
    square lost the caption.
  - **Neil**: `neil-logo.jpg`, from `Team Logos\IMG_9374.jpg`. He has no
    Sleeper logo.

  A config logo overrides Sleeper's, so when one of those teams gets a new
  logo, update the file too.
- The stylesheet defines a complete light palette on bare `:root`, then overrides
  tokens under `prefers-color-scheme: dark` and `[data-theme="dark"]`. Do not put
  a colour's only definition inside a media query.
- **The league logo is THE logo** (Matt, September 2026). It is shown exactly as
  he made it, white background and all, in light and dark mode. Never cut it
  out, recolour it or make a dark version. The masthead is a white band in both
  themes for that reason; the page only trims the empty white margin round the
  artwork with CSS (`.leaguelogo`), and the file is a byte-for-byte copy.
- **The palette comes from the logo** (September 2026). Red is the accent,
  from DYNASTY and the Lombardi L: the active tab's underline, links, the rule
  on each section heading. Navy is the NFL shield and the Madden M: the nav bar,
  and the whole of dark mode, which is NFL navy rather than black, as Matt asked.
  Gold (`--gold`) is for trophies only: champions, the 1.01, the title stars.
  Headings are Roboto Slab, after the slab lettering of DYNASTY.
- Power rankings reproduce the Power Rankings tab of Matt's Team Tracking
  workbook. See "Power rankings (Scoreboard)". The method is deliberately not
  published on the site.

## Validated against the old site

The generated breecetie boys page was checked line by line against Matt's
hand-maintained one. Exact matches: points for (11,143.20), vs LFC (19–13),
playoff record (5 appearances, 6–6), and **every** head-to-head line across all
five tables.

Two bugs were found and fixed this way, both in `stats.py`:

1. Record week only considered regular-season games, so it missed Dave's 204.86
   in 2024 Week 15 — a playoff week. Best and worst weeks now span every game.
2. An in-progress week with no points scored was recorded as an all-time low of
   0.00, which would have stuck permanently. Weeks where a team has scored zero
   are now skipped for those records.

Both regressed before September 2026 — the team pages showed 2026 week 1's
half-played scores as all-time lows, and record weeks were regular season only
again. Fixed properly this time: `build_site.last_complete_week` reads Sleeper's
state and the current season is indexed only up to the last finished week, so a
week in progress is neither a result nor a record anywhere on the site.

**When numbers disagree with the old site, check the live week first.** Records
shift mid-week while games are in flight and settle when they finish. The one
long-standing discrepancy, Dave's career trades (43 here, 41 on the old page),
was settled in September 2026. The old sheet stops at the end of 2025 and counts
his draft-day trade from 2024, which Sleeper never recorded. With that trade
and his three 2026 trades he is on 44.

## Where Matt's material lives

On his Windows machine, under `OneDrive\Documents\Fantasy Football\Dynasty`:

- `Website\Team AI\` — manager portraits, regenerated each season. `IMG_4167`
  through `IMG_4179` are the 2026 set.
- `Website\Team Logos\` — 36 logos, mostly retired team names from past seasons.
- `Website\Team Uniforms\`, `Trades\`, `Season Review\`, `Winners and Losers\`,
  `End of Year Awards\`, `Team Announcements\`, `Podcasts\` — the archive
  material, none of it yet on the new site.
- `Claude\Team Tracking 2026 - altpr.xlsx` — the weekly workbook. The Power
  Rankings tab is a collector: column B is week 1 typed by hand, C–O pull
  `'Week N'!Y`, and the formula itself is each Week sheet's Score column (X),
  ranked by `RANK.EQ` in Y. R–AE are the projected points it uses. Also the
  Awards and Finishes tabs.

Google Drive has the season review PDFs (2020–2026), schedules, rules PDFs,
records sheets and the Trade Log, in `FF/Website`.

## Backlog

Roughly in the order discussed with Matt, though he has not yet picked:

1. **Playoff odds.** Done in September 2026. See "Playoff odds (Scoreboard)".
   So are the **power rankings** and the **off-season and season roll-over**,
   the two Matt raised in September 2026; both have sections above.
2. **Conference crests with computed stars.** The colour scheme and identity
   were done in September 2026 (see Conventions). What is left of it is drawing
   the stars on the crests from the computed title count, so they stop going
   stale (see "The stars on the conference crests").
3. **Team uniforms.** The uniform images from the old team pages, the last thing
   they have that the new ones do not. (The honours were done in September 2026.)
4. **The archive.** Official team statements, Lee's Stat Corner. (The Trade
   Centre, Commissioner Updates and Rules were done in September 2026.)
5. **Conference landing pages** (LC/MC) and a **calendar**, both on the old site
   and not yet rebuilt.

## Gotchas

- `docs/` is generated. Edit the templates in `build_site.py`, never the output.
- The Action commits `data/` and `docs/` back to `main`, so **pull before you
  push** or you will collide with the bot.
- Playoff-week fixtures that appear in neither bracket are Sleeper pairing off
  eliminated teams. They are deliberately ignored — counting them would inflate
  records.
- `fetch_data.py` re-downloads the ~5MB player index at most once a day, keyed on
  the file's mtime. A fresh checkout has a new mtime, so CI downloads it each run.
- The site was built in an environment with no network access to `api.sleeper.app`
  or `github.com`, so nothing could be tested end to end locally — the first real
  run happened in CI. **On a normal machine both are reachable**, so run the two
  scripts locally before pushing. That was not possible before and is the main
  reason for moving to Claude Code. As of September 2026 this works on Matt's
  machine: Python 3.13 is installed but not on `PATH`, at
  `%LOCALAPPDATA%\Programs\Python\Python313\python.exe`, and `git` is not on
  `PATH` either — use the copy inside GitHub Desktop's `app-*\resources\app\git\cmd`.
  A local `build_site.py` run reproduces the committed `docs/` exactly apart from
  the "Last refreshed" timestamp, so a clean local build can be trusted.
- That command-line `git` has **no GitHub credentials**, so `git push` fails with
  "could not read Username". Commit locally and have Matt press **Push origin**
  in GitHub Desktop. Every push triggers the bot, which commits a refresh a few
  minutes later — fast-forward to it (`git pull --ff-only`) before the next
  commit. If local `docs/` edits block that, discard them with
  `git checkout -- docs/` and rebuild; they are generated anyway.
- pypdfium2 and Pillow are installed for that local Python with `pip --user`, so
  a local build draws covers and diffs as CI does. To preview the built site,
  the Browser pane's `jadl-site` entry in `.claude/launch.json` serves `docs/` on
  port 8765; opening the files directly loses the stylesheet.
