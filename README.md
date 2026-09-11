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

Champions, the 1.01 winner and Loser of All Losers are read from the Sleeper
brackets, so there is no list of them to keep.

Team images live in `assets/teams/`. Drop new ones in and point `league.config.json` at them.

Each season's champion GIF and Loser of All Losers picture go in `assets/records/`.
This shrinks them and names them so the history page finds them on its own:

```
python scripts/prepare_media.py 2026 champion "path/to/the.gif"
python scripts/prepare_media.py 2026 loser "path/to/the-photo.jpg"
```

## Running it yourself

```
python scripts/fetch_data.py
python scripts/build_site.py
```

Then open `docs/index.html`.
