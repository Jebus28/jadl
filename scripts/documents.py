#!/usr/bin/env python3
"""
The league's documents: the rulebook and the commissioner's updates. Both are
files saved into assets/ and found by where they sit, so there is nothing to add
to league.config.json.

    assets/rules/              every edition of the rulebook as a PDF, and the
                               Word file of the current one, which the Rules
                               page is drawn from
    assets/updates/<season>/   that season's previews, reviews and schedules as
                               PDFs, and anything too big for GitHub (the review
                               videos) as an internet shortcut to it on Drive

A document's title is its file name and its date is the one Word stamped on the
PDF when it was saved, so a new update needs nothing more than saving it into
the season's folder.

Covers, edition labels and what changed between editions need pypdfium2. Without
it the pages still build, only with no covers and no "what changed".
"""
from __future__ import annotations

import difflib
import hashlib
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlparse

try:
    import pypdfium2 as pdfium
except ImportError:
    pdfium = None

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
EDITION = re.compile(r"(\d+)\s*(?:st|nd|rd|th)\s+Edition\s*[–—-]\s*([A-Z][a-z]+\s+\d{4})")
COVER_WIDTH = 360      # pixels; shown at about half that, so sharp on a phone
CONTEXT = 8            # words either side of a change to the rulebook
LONGEST = 90           # words of a change shown before it is cut short

SMALL_WORDS = {"a", "an", "and", "at", "by", "for", "in", "of", "on", "or", "the", "to", "vs"}

# What a document is, from its title. The first match wins, so the more specific
# phrase comes first ("regular season review" before "season review").
KINDS = [
    ("draft preview", "Draft preview"), ("draft review", "Draft review"),
    ("schedule", "Schedule"), ("fixtures", "Schedule"),
    ("season preview", "Season preview"), ("third review", "Mid-season review"),
    ("regular season", "Regular season review"), ("dynasty review", "Dynasty review"),
    ("season review", "Season review"), ("proposed changes", "Rule changes"),
    ("auction", "Procedure"), ("agenda", "AGM"), ("minutes", "AGM"),
]


def title_of(stem: str) -> str:
    """A file name as a title: '2024 Rookie draft preview' -> '2024 Rookie Draft Preview'."""
    words = stem.split()
    for i, word in enumerate(words):
        if word.islower() and not (i and word in SMALL_WORDS):
            words[i] = word[:1].upper() + word[1:]
    return " ".join(words)


def kind_of(title: str) -> str:
    low = title.lower()
    return next((label for phrase, label in KINDS if phrase in low), "")


def site_path(path: Path, assets: Path) -> str:
    """Where a file in assets/ is served from, spaces and all."""
    return "assets/" + quote(path.relative_to(assets).as_posix())


# ---------- PDFs ----------

def pdf_created(data: bytes) -> datetime | None:
    """When the PDF was made, as Word stamped it."""
    m = re.search(rb"/CreationDate\s*\(D:(\d{8})(\d{4})?", data)
    if m:
        return datetime.strptime(m.group(1).decode() + (m.group(2) or b"0000").decode(), "%Y%m%d%H%M")
    m = re.search(rb"<xmp:CreateDate>(\d{4}-\d{2}-\d{2})", data)
    return datetime.fromisoformat(m.group(1).decode()) if m else None


def pdf_pages(path: Path, data: bytes) -> int | None:
    if pdfium is not None:
        doc = pdfium.PdfDocument(str(path))
        try:
            return len(doc)
        finally:
            doc.close()
    return len(re.findall(rb"/Type\s*/Page[^s]", data)) or None


def pdf_text(path: Path) -> list[str] | None:
    """The text of every page, or None without pypdfium2."""
    if pdfium is None:
        return None
    doc = pdfium.PdfDocument(str(path))
    try:
        # pdfium marks a hyphen that fell at the end of a line as U+FFFE.
        return [page.get_textpage().get_text_range().replace("￾", "-") for page in doc]
    finally:
        doc.close()


def cover(path: Path, data: bytes, covers: Path) -> str | None:
    """
    A picture of the first page, in docs/assets/covers. It is named for the file's
    contents, so each PDF is drawn once and a replaced PDF gets a new picture.
    """
    name = hashlib.sha1(data).hexdigest()[:16] + ".webp"
    dest = covers / name
    if not dest.exists():
        if pdfium is None:
            return None
        doc = pdfium.PdfDocument(str(path))
        try:
            page = doc[0]
            image = page.render(scale=COVER_WIDTH / page.get_width()).to_pil()
        finally:
            doc.close()
        covers.mkdir(parents=True, exist_ok=True)
        image.convert("RGB").save(dest, "WEBP", quality=78, method=6)
    return name


def prune_covers(covers: Path, keep: set[str]) -> None:
    """Drop the pictures of PDFs that have since been replaced or removed."""
    if covers.exists():
        for old in covers.glob("*.webp"):
            if old.name not in keep:
                old.unlink()


def pdf_item(path: Path, assets: Path, covers: Path) -> dict:
    data = path.read_bytes()
    title = title_of(path.stem)
    return {"title": title, "kind": kind_of(title), "href": site_path(path, assets),
            "date": pdf_created(data), "pages": pdf_pages(path, data),
            "cover": cover(path, data, covers), "link": ""}


def link_item(path: Path) -> dict | None:
    """
    An internet shortcut: what Windows makes when a link is dragged out of the
    browser into a folder. Anything too big for GitHub - the videos - lives on
    Drive and is linked like this. An optional 'Date=YYYY-MM-DD' line dates it;
    without one it counts as just added and goes to the top of its season.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    url = re.search(r"^URL=(https?://\S+)", text, re.M)
    if not url:
        return None
    date = re.search(r"^Date=(\d{4}-\d{2}-\d{2})", text, re.M)
    host = urlparse(url.group(1)).netloc.lower()
    where = ("Google Drive" if "drive.google" in host else "YouTube" if "youtu" in host
             else host.removeprefix("www."))
    title = title_of(path.stem)
    return {"title": title, "kind": kind_of(title), "href": url.group(1),
            "date": datetime.fromisoformat(date.group(1)) if date else None,
            "pages": None, "cover": None, "link": where}


def commissioner_updates(root: Path, assets: Path, covers: Path) -> dict[int, list[dict]]:
    """Season -> its documents, newest first."""
    seasons = {}
    if not root.exists():
        return seasons
    for folder in root.iterdir():
        if not (folder.is_dir() and folder.name.isdigit()):
            continue
        items = []
        for f in folder.iterdir():
            if f.suffix.lower() == ".pdf":
                items.append(pdf_item(f, assets, covers))
            elif f.suffix.lower() == ".url":
                link = link_item(f)
                if link:
                    items.append(link)
        # Undated means just added, so it leads.
        items.sort(key=lambda it: (it["date"] or datetime.max, it["title"]), reverse=True)
        if items:
            seasons[int(folder.name)] = items
    return seasons


# ---------- the rulebook, from Word ----------

def _style(p) -> str:
    node = p.find(f"{W}pPr/{W}pStyle")
    return node.get(W + "val") if node is not None else ""


def _text(p) -> str:
    out = []
    for node in p.iter():
        if node.tag == W + "t":
            out.append(node.text or "")
        elif node.tag == W + "tab":
            out.append(" ")
        elif node.tag in (W + "br", W + "cr"):
            out.append("\n")
        elif node.tag == W + "noBreakHyphen":
            out.append("-")
    lines = (re.sub(r"[ \t ]+", " ", line).strip() for line in "".join(out).split("\n"))
    return "\n".join(line for line in lines if line)


def _bold(p) -> bool:
    runs = [r for r in p.iter(W + "r") if "".join(t.text or "" for t in r.iter(W + "t")).strip()]

    def on(r):
        b = r.find(f"{W}rPr/{W}b")
        return b is not None and b.get(W + "val") not in ("0", "false")
    return bool(runs) and all(on(r) for r in runs)


def _numbering(z: zipfile.ZipFile) -> dict:
    """numId -> {level: (start, format, text)}, from word/numbering.xml."""
    try:
        root = ET.fromstring(z.read("word/numbering.xml"))
    except KeyError:
        return {}
    abstract = {}
    for a in root.findall(W + "abstractNum"):
        levels = {}
        for lvl in a.findall(W + "lvl"):
            start, fmt, text = lvl.find(W + "start"), lvl.find(W + "numFmt"), lvl.find(W + "lvlText")
            levels[int(lvl.get(W + "ilvl"))] = (
                int(start.get(W + "val")) if start is not None else 1,
                fmt.get(W + "val") if fmt is not None else "decimal",
                text.get(W + "val") if text is not None else "")
        abstract[a.get(W + "abstractNumId")] = levels
    nums = {}
    for n in root.findall(W + "num"):
        ref = n.find(W + "abstractNumId")
        levels = dict(abstract.get(ref.get(W + "val") if ref is not None else "", {}))
        for override in n.findall(W + "lvlOverride"):
            level, start = int(override.get(W + "ilvl")), override.find(W + "startOverride")
            if start is not None and level in levels:
                levels[level] = (int(start.get(W + "val")),) + levels[level][1:]
        nums[n.get(W + "numId")] = levels
    return nums


def _roman(n: int) -> str:
    out = ""
    for value, digits in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
                          (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= value:
            out, n = out + digits, n - value
    return out


def _format(n: int, fmt: str) -> str:
    if fmt == "lowerLetter":
        return chr(96 + (n - 1) % 26 + 1)
    if fmt == "upperLetter":
        return chr(64 + (n - 1) % 26 + 1)
    if fmt == "lowerRoman":
        return _roman(n)
    if fmt == "upperRoman":
        return _roman(n).upper()
    if fmt == "bullet":
        return "•"
    if fmt == "none":
        return ""
    return str(n)


def _count(counters: dict, numbering: dict, num_id: str, level: int) -> str:
    """Advance Word's counter for this list and level, and spell out the number."""
    levels = numbering.get(num_id, {})
    counts = counters.setdefault(num_id, [None] * 9)
    start = levels.get(level, (1, "decimal", ""))[0]
    counts[level] = start if counts[level] is None else counts[level] + 1
    for deeper in range(level + 1, 9):
        counts[deeper] = None
    template = levels.get(level, (1, "decimal", ""))[2] or f"%{level + 1}."

    def spell(m):
        at = int(m.group(1)) - 1
        start_at, fmt, _ = levels.get(at, (1, "decimal", ""))
        return _format(counts[at] if counts[at] is not None else start_at, fmt)
    return re.sub(r"%(\d)", spell, template)


def _blocks(parent):
    """Paragraphs and tables in reading order, skipping the table of contents."""
    for el in parent:
        if el.tag in (W + "p", W + "tbl"):
            yield el
        elif el.tag == W + "sdt":
            gallery = el.find(f"{W}sdtPr/{W}docPartObj/{W}docPartGallery")
            if gallery is not None and "Contents" in (gallery.get(W + "val") or ""):
                continue
            content = el.find(W + "sdtContent")
            if content is not None:
                yield from _blocks(content)


def _table(tbl) -> list[dict]:
    rows = []
    for tr in tbl.findall(W + "tr"):
        cells = []
        for tc in tr.findall(W + "tc"):
            span = tc.find(f"{W}tcPr/{W}gridSpan")
            paras = [p for p in tc.iter(W + "p") if _text(p)]
            cells.append({"span": int(span.get(W + "val")) if span is not None else 1,
                          "lines": [_text(p) for p in paras],
                          "bold": bool(paras) and all(_bold(p) for p in paras)})
        rows.append({"cells": cells, "header": tr.find(f"{W}trPr/{W}tblHeader") is not None})
    # A row with nothing in its first cell carries on the one above, as the lines
    # of the rulebook's summary do.
    merged = []
    for row in rows:
        cells = row["cells"]
        if merged and len(cells) > 1 and not cells[0]["lines"] and len(cells) == len(merged[-1]["cells"]):
            for mine, more in zip(merged[-1]["cells"], cells):
                mine["lines"] += more["lines"]
        else:
            merged.append(row)
    if merged and not merged[0]["header"]:
        first = [c for c in merged[0]["cells"] if c["lines"]]
        merged[0]["header"] = len(merged) > 2 and len(first) > 1 and all(c["bold"] for c in first)
    return merged


def rulebook(path: Path) -> dict:
    """
    The rulebook's Word file as headings, numbered paragraphs and tables. The
    paragraph numbers are Word's own, worked out the way Word does, because the
    rules refer to each other by them ("subject to para 40").
    """
    with zipfile.ZipFile(path) as z:
        body = ET.fromstring(z.read("word/document.xml")).find(W + "body")
        numbering = _numbering(z)
    title, edition, blocks, counters, started = "", "", [], {}, False
    for el in _blocks(body):
        if el.tag == W + "tbl":
            if started:
                blocks.append({"type": "table", "rows": _table(el)})
            continue
        style, text = _style(el), _text(el)
        if not text or style.startswith("TOC"):
            continue
        if style.startswith("Heading"):
            started = True
            blocks.append({"type": "h1" if style == "Heading1" else "h2", "text": text})
            continue
        if not started:
            # The cover: the book's title and its edition.
            if EDITION.search(text):
                edition = text
            elif not title:
                title = text
            continue
        num, label = None, ""
        num_pr = el.find(f"{W}pPr/{W}numPr")
        if num_pr is not None:
            num_id, level = num_pr.find(W + "numId"), num_pr.find(W + "ilvl")
            num_id = num_id.get(W + "val") if num_id is not None else None
            if num_id and num_id != "0" and num_id in numbering:
                num = (num_id, int(level.get(W + "val")) if level is not None else 0)
                label = _count(counters, numbering, *num)
        blocks.append({"type": "p", "text": text, "num": num, "label": label,
                       "list": style.startswith("List")})
    # The longest run of top-level numbers is the rule numbering.
    tally = Counter(b["num"][0] for b in blocks if b["type"] == "p" and b["num"] and b["num"][1] == 0)
    main = tally.most_common(1)[0][0] if tally else None
    for b in blocks:
        if b["type"] == "p":
            b["rule"] = bool(b["label"]) and b["num"] == (main, 0)
    m = EDITION.search(edition)
    return {"title": title, "edition": edition, "number": int(m.group(1)) if m else 0,
            "blocks": blocks, "path": path}


def current_rulebook(root: Path) -> dict | None:
    """The newest edition among the Word files in assets/rules."""
    books = [rulebook(p) for p in root.glob("*.docx") if not p.name.startswith("~$")] if root.exists() else []
    return max(books, key=lambda b: (b["number"], b["path"].stat().st_mtime), default=None)


# ---------- editions, and what changed between them ----------

RUNNING_HEAD = re.compile(r"^(Jessica Alba (Fantasy|Dynasty) League Rules|Page \d+|\d+)$")


def _rule_words(pages: list[str]) -> list[str]:
    """
    An edition's wording as a run of words, with everything that moves without the
    rules changing taken out: the contents page, the running heads and page
    numbers, and the paragraph numbers, which shift whenever a rule is added.
    """
    text = "\n".join(pages)
    m = EDITION.search(text)
    if m:
        text = text[m.end():]
    words = []
    for line in text.splitlines():
        line = line.strip()
        if not line or RUNNING_HEAD.match(line):
            continue
        line = re.sub(r"^(\d{1,3}|[ivx]{1,4}|[a-z])\.\s+", "", line)
        words.extend(line.split())
    # Superscript ordinals come out as two words, sometimes on two lines: "2 nd".
    joined = []
    for word in words:
        if joined and joined[-1].isdigit() and re.fullmatch(r"(st|nd|rd|th)\W*", word):
            joined[-1] += word
        else:
            joined.append(word)
    return joined


def _squash(words: list[str]) -> str:
    return re.sub(r"[^0-9a-z£$%]", "", " ".join(words).lower())


def _clip(words: list[str]) -> str:
    return " ".join(words) if len(words) <= LONGEST else " ".join(words[:LONGEST]) + " …"


def changes(before: list[str], after: list[str]) -> list[list[tuple[str, str]]]:
    """
    Each change from one edition's wording to the next, as runs of ('same' | 'old'
    | 'new', text) with a few words either side. Changes a few words apart are
    shown as one; changes of punctuation, case or hyphenation are left out.
    """
    ops = difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes()
    groups = []
    for k, (tag, i1, _i2, _j1, _j2) in enumerate(ops):
        if tag == "equal":
            continue
        if groups and i1 - ops[groups[-1][-1]][2] <= 3:
            groups[-1].append(k)
        else:
            groups.append([k])
    out = []
    for group in groups:
        first, last = ops[group[0]], ops[group[-1]]
        if _squash(before[first[1]:last[2]]) == _squash(after[first[3]:last[4]]):
            continue
        runs = [("same", " ".join(before[max(0, first[1] - CONTEXT):first[1]]))]
        for tag, i1, i2, j1, j2 in ops[group[0]:group[-1] + 1]:
            if tag == "equal":
                runs.append(("same", " ".join(before[i1:i2])))
                continue
            if i2 > i1:
                runs.append(("old", _clip(before[i1:i2])))
            if j2 > j1:
                runs.append(("new", _clip(after[j1:j2])))
        runs.append(("same", " ".join(before[last[2]:last[2] + CONTEXT])))
        out.append([run for run in runs if run[1]])
    return out


def rule_editions(root: Path, assets: Path, covers: Path) -> tuple[list[dict], list[dict]]:
    """
    Every edition of the rulebook, oldest first, each with what changed from the
    one before; and any other PDF in assets/rules (the auction procedure).
    """
    editions, others = [], []
    for path in sorted(root.glob("*.pdf")) if root.exists() else []:
        pages = pdf_text(path)
        m = EDITION.search(" ".join(pages[:3])) if pages else None
        if not m:
            others.append(pdf_item(path, assets, covers))
            continue
        data = path.read_bytes()
        editions.append({"number": int(m.group(1)), "month": m.group(2), "date": pdf_created(data),
                         "pages": len(pages), "href": site_path(path, assets), "words": _rule_words(pages)})
    editions.sort(key=lambda ed: (ed["number"], ed["date"] or datetime.min))
    for before, after in zip(editions, editions[1:]):
        after["changes"] = changes(before["words"], after["words"])
        after["previous"] = before["number"]
    others.sort(key=lambda it: it["title"])
    return editions, others
