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
- the champions list

Team images live in `assets/teams/`. Drop new ones in and point `league.config.json` at them.

## Running it yourself

```
python scripts/fetch_data.py
python scripts/build_site.py
```

Then open `docs/index.html`.
