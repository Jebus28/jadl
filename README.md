# JADL — Jessica Alba Dynasty League

The league site. It builds itself.

**Live site:** https://jebus28.github.io/jadl/

## How it works

1. `scripts/fetch_data.py` pulls everything from Sleeper's free read API into `data/`.
2. `scripts/build_site.py` turns `data/` plus `league.config.json` into the pages in `docs/`.
3. GitHub Pages serves `docs/`.
4. An Action re-runs steps 1 and 2: every 15 minutes while games are on, at
   noon UK every Wednesday, and once a day otherwise. The timetable is kept on
   **cron-job.org**, not GitHub, because GitHub stopped running its own
   schedule on time in October 2026. See "The refresh timetable" below.

Nothing is typed in by hand.

## The refresh timetable (cron-job.org)

Five jobs on cron-job.org (Matt's account, UK time) each ask GitHub to run the
refresh. GitHub's own schedule in `.github/workflows/refresh.yml` is still there
as a backup, but it runs hours late.

| Job | When (UK time) |
|---|---|
| JADL – Wednesday noon | Wednesdays 12:01 |
| JADL – Sunday games | Sundays, every 15 minutes, 13:00–23:45 |
| JADL – late games | Sun, Mon, Tue, Fri, every 15 minutes, 00:00–05:45 |
| JADL – Thanksgiving & December Saturdays | Thu, Fri, Sat, every 15 minutes, 17:00–23:45 |
| JADL – daily | Every day 07:30 |

Each job sends a `POST` to
`https://api.github.com/repos/Jebus28/jadl/actions/workflows/refresh.yml/dispatches`
with the body `{"ref":"main"}` and three headers: `Accept: application/vnd.github+json`,
`X-GitHub-Api-Version: 2022-11-28`, and `Authorization: Bearer <token>`.

### Renewing the token — due by 1 August 2027

The token lets cron-job.org start the refresh. It **expires on 1 August 2027**,
and after that every job fails and the site stops refreshing (cron-job.org
emails you when a job fails). Renew it in July:

1. **Make a new token on GitHub.** Your picture (top right) → **Settings** →
   **Developer settings** → **Personal access tokens** → **Fine-grained tokens**.
   Either open the old `cron-job.org JADL refresh` token and press
   **Regenerate token**, or press **Generate new token** and set it up as:
   - **Expiration:** Custom, **1 August** of the following year
   - **Repository access:** Only select repositories → **Jebus28/jadl**
   - **Repository permissions:** **Actions → Read and write** (nothing else)
2. **Copy the token.** GitHub shows it once only. Don't paste it anywhere else.
3. **Put it in all five jobs on cron-job.org.** Open each job → **Advanced** →
   the `Authorization` header → replace the value with `Bearer ` (the word,
   then one space) followed by the new token → **Save**.
4. **Test one.** Press **Test run** on any job. **204 No Content** means it
   worked. 401 means the token was pasted wrongly (check the space after
   `Bearer`); 403 or 404 means the token is missing the repository or the
   Actions permission.
5. **Check GitHub.** On the repository's **Actions** tab, a new run marked
   `workflow_dispatch` should appear within a minute.
6. **Delete the old token** on GitHub, if you made a new one rather than
   regenerating it.
7. **Set a calendar reminder** for next July.

If the site ever stops updating, look at the Actions tab first: no recent
`workflow_dispatch` runs means cron-job.org has stopped (most likely the token);
runs that fail mean the problem is in the build.

## Changing things each season

Edit **`league.config.json`** and nothing else. The season year, the league ID
and the playoff setup look after themselves: when you create next season's
league on Sleeper, the site finds it and follows it. The file holds:

- conference names and colours
- manager names and their image filenames
- the name of each year's consolation trophy
- any trade done by hand on draft day that Sleeper never recorded (`manual_trades`)
  — the Trade Centre lists a loose end if one is missing

Champions, the 1.01 winner and Loser of All Losers are read from the Sleeper
brackets, so there is no list of them to keep.

Team images live in `assets/teams/`. Drop new ones in and point `league.config.json` at them.

Each season's champion GIF and Loser of All Losers picture go in `assets/records/`.
This shrinks them and names them so the history page finds them on its own:

```
python scripts/prepare_media.py 2026 champion "path/to/the.gif"
python scripts/prepare_media.py 2026 loser "path/to/the-photo.jpg"
```

## Commissioner updates and the rules

Both tabs are drawn from files in `assets/`, found by where they sit — nothing to
add to `league.config.json`.

- **A new update:** save the PDF into `assets/updates/<season>/`. Its file name is
  its title and the date Word stamped on it puts it in order, newest first.
- **A video**, or anything else too big for GitHub: leave it on Google Drive, drag
  its link from the browser into the season folder, and rename the shortcut that
  makes. Add a line `Date=2027-01-20` to the shortcut to put it in order; without
  one it goes to the top of its season.
- **A new edition of the rules:** save the Word file and its PDF into
  `assets/rules/`. The Rules page is set out from the newest Word file, and what
  changed from the last edition is worked out from the PDFs.

The covers and the changes between editions need two Python packages. The
Action installs them; to build locally with them too:

```
python -m pip install pypdfium2 pillow
```

## Running it yourself

```
python scripts/fetch_data.py
python scripts/build_site.py
```

Then open `docs/index.html`.
