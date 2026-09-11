#!/usr/bin/env python3
"""
Turn a champion GIF or a Loser of All Losers photo into something a web page can
carry, and put it where the history page looks for it.

    python scripts/prepare_media.py 2026 champion "path/to/gif.GIF"
    python scripts/prepare_media.py 2026 loser "path/to/photo.jpg"

GIFs become short silent looping WebPs, a tenth of the size or less. Photos are
turned the right way up (phones store that as a tag, not in the pixels) and
shrunk. Either kind may be a still: a champion photo works as well as a GIF.

The history page finds files by name - assets/records/<season>-<kind>.<ext> -
so there is nothing to add to league.config.json.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageOps, ImageSequence

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "records"
KINDS = ("champion", "loser")
LOOP_EDGE = 640      # longest side of a loop, in pixels
STILL_EDGE = 900
LOOP_BUDGET = 2_500_000  # bytes; above this, frames are thinned until it fits


def encode_loop(src: Image.Image, dest: Path) -> None:
    frames, durations = [], []
    for frame in ImageSequence.Iterator(src):
        durations.append(frame.info.get("duration") or 80)
        frame = frame.convert("RGB")
        frame.thumbnail((LOOP_EDGE, LOOP_EDGE), Image.LANCZOS)
        frames.append(frame)
    # Drop every other frame (doubling the survivors' time on screen) until the
    # file is small enough. The loop runs for the same length, only less smoothly.
    step = 1
    while True:
        kept = frames[::step]
        kept_durations = [sum(durations[i:i + step]) for i in range(0, len(durations), step)]
        kept[0].save(dest, save_all=True, append_images=kept[1:], duration=kept_durations,
                     loop=0, quality=50, method=6)
        if dest.stat().st_size <= LOOP_BUDGET or len(kept) <= 12:
            return
        step *= 2


def main(argv: list[str]) -> int:
    if len(argv) != 4 or argv[2] not in KINDS:
        print(__doc__)
        return 2
    season, kind, source = argv[1], argv[2], Path(argv[3])
    if not season.isdigit():
        print("Season should be a year, e.g. 2026.")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob(f"{season}-{kind}.*"):
        old.unlink()

    image = Image.open(source)
    # iPhone JPEGs can carry a second frame (a depth map or preview), so only
    # formats that genuinely animate count as loops.
    if image.format in ("GIF", "PNG", "WEBP") and getattr(image, "n_frames", 1) > 1:
        dest = OUT / f"{season}-{kind}.webp"
        encode_loop(image, dest)
    else:
        dest = OUT / f"{season}-{kind}.jpg"
        still = ImageOps.exif_transpose(image).convert("RGB")
        still.thumbnail((STILL_EDGE, STILL_EDGE), Image.LANCZOS)
        still.save(dest, quality=82, optimize=True, progressive=True)

    print(f"{source.name} -> {dest.relative_to(ROOT)} ({dest.stat().st_size / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
