# JADL — Jessica Alba Dynasty League

The league site. It builds itself.

**Live site:** https://jebus28.github.io/jadl/

## How it works

1. `scripts/fetch_data.py` pulls everything from Sleeper's free read API into `data/`.
2. `scripts/build_site.py` turns `data/` plus `league.config.json` into the pages in `docs/`.
3. GitHub Pages serves `docs/`.
4. A scheduled Action re-runs steps 1 and 2 — every couple of hours on game days, once a day otherwise.

Nothing is typed in by hand.

## Changing things each season

Edit **`league.config.json`** and nothing else. It holds:

- the season year, how many regular-season weeks, when the playoffs start
- the current Sleeper league ID (change it when you roll over to a new season)
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
