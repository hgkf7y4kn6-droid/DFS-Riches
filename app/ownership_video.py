"""Actual contest ownership from a screen recording of DraftKings' GameCenter "Players" tab.

Each row on that screen reads

    RB   C. Hubbard   18.56%               22.10
         CAR 25 @ PHI 14 | FINAL
         $6,300

(position, abbreviated name, % drafted in the contest, the game, salary, and DK fantasy points on the right).
The recording is scrolled through the list; this module turns it into rows:

  1. frames   ffmpeg samples FRAMES_PER_SECOND frames, drops near-duplicates (a pause in scrolling), scales them
              to a fixed width, converts to grayscale and inverts (DraftKings draws white text on black), and
              blanks the headshot column, the dotted divider and the chevrons -- the text OCR misreads most. The
              points column is cut out of the same frame as its own image.
  2. OCR      tesseract reads each frame with word positions (TSV), and the points column as digits only.
  3. rows     a line "Name 12.34%" starts a row; the row's salary ($6,300) and game (CAR 25 @ PHI 14) are the
              lines below it, up to the next row, and its points the number in the points column at that height.
              A row cut off at the bottom of a frame keeps only its name and ownership -- the scroll shows it whole
              in another frame.
  4. merge    every frame's reading of a row is pooled and each field takes its most common value, so one bad
              frame doesn't win.
  5. match    rows are matched to the slate's players by last name + first initial, confirmed by salary (and
              team) -- "K. Allen" at $4,300 is Keenan Allen, not Josh Allen at $7,500. DSTs by team nickname.

Needs the ffmpeg and tesseract binaries (installed in the Docker image).
"""
from __future__ import annotations

import csv
import io
import os
import re
import shutil
import statistics
import struct
import subprocess
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.matching import normalize_name

FRAMES_PER_SECOND = 3
MAX_FRAMES = 360
WIDTH = 1200
# Blanked strips, as shares of the frame width: headshots (and the position label above them), the dotted divider
# left of the points, and the expand chevrons.
BLANK = ((0.0, 0.175), (0.725, 0.76), (0.905, 1.0))
POINTS_COL = (0.76, 0.905)  # the fantasy-points column, read separately as digits (its large bold numbers split
                            # into pieces when read with the rest of the row)
OCR_WORKERS = 2

ROW_RE = re.compile(r"^(?P<name>[A-Z][A-Za-z'.\- ]{1,40}?)\s+(?P<pct>\d{1,3}(?:[.,]\d{1,2})?)\s*%")
SALARY_RE = re.compile(r"\$\s?(\d{1,2})[,.]?(\d{3})\b")
GAME_RE = re.compile(r"\b([A-Z]{2,3})\s+(\d{1,2})\s*@\s*([A-Z]{2,3})\s+(\d{1,2})\b")
POINTS_RE = re.compile(r"^-?\d{1,3}[.,]\d{1,2}$")


def available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("tesseract"))


def _filter(sample: bool) -> str:
    boxes = ",".join(f"drawbox=x=iw*{a}:y=0:w=iw*{b - a:.3f}:h=ih:color=white:t=fill" for a, b in BLANK)
    a, b = POINTS_COL
    return ((f"fps={FRAMES_PER_SECOND},mpdecimate," if sample else "") + f"scale={WIDTH}:-2,format=gray,negate,split=2[t][p];"
            f"[t]{boxes}[text];[p]crop=iw*{b - a:.3f}:ih:iw*{a}:0[pts]")


def extract_frames(video: Path, out_dir: Path) -> list[tuple[Path, Path]]:
    """(frame, points column) PNG pairs: sampled, de-duplicated and preprocessed (a screenshot gives one pair)."""
    for sample in (True, False):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(video), "-filter_complex", _filter(sample),
                        "-map", "[text]", "-fps_mode", "vfr", "-frames:v", str(MAX_FRAMES), str(out_dir / "f%04d.png"),
                        "-map", "[pts]", "-fps_mode", "vfr", "-frames:v", str(MAX_FRAMES), str(out_dir / "p%04d.png")],
                       check=True, timeout=600)
        frames = sorted(out_dir.glob("f*.png"))
        if frames:
            return [(f, f.with_name("p" + f.name[1:])) for f in frames]
    return []


def _height(png: Path) -> int:
    with open(png, "rb") as f:
        return struct.unpack(">II", f.read(24)[16:24])[1]


def ocr_words(png: Path, digits: bool = False) -> list[dict]:
    """Words with their boxes: {text, left, top, width, height, line} (line = tesseract's block/paragraph/line).
    digits: read only digits, '.' and '-' (the points column)."""
    cmd = ["tesseract", str(png), "-", "--psm", "6" if digits else "4"]
    if digits:
        cmd += ["-c", "tessedit_char_whitelist=0123456789.-"]
    out = subprocess.run(cmd + ["tsv"], capture_output=True, text=True, timeout=120, check=True,
                         env={**os.environ, "OMP_THREAD_LIMIT": "1"}).stdout   # threads within one frame only contend
    words = []
    for r in csv.DictReader(io.StringIO(out), delimiter="\t", quoting=csv.QUOTE_NONE):
        text = (r.get("text") or "").strip()
        if not text or r.get("level") != "5":
            continue
        words.append({"text": text, "left": int(r["left"]), "top": int(r["top"]), "width": int(r["width"]),
                      "height": int(r["height"]), "line": (r["block_num"], r["par_num"], r["line_num"])})
    return words


def _lines(words: list[dict]) -> list[dict]:
    by: dict[tuple, list[dict]] = {}
    for w in words:
        by.setdefault(w["line"], []).append(w)
    lines = []
    for ws in by.values():
        ws.sort(key=lambda w: w["left"])
        lines.append({"text": " ".join(w["text"] for w in ws), "words": ws, "top": min(w["top"] for w in ws),
                      "bottom": max(w["top"] + w["height"] for w in ws)})
    return sorted(lines, key=lambda ln: ln["top"])


def _clean(text: str) -> str:
    """OCR slips at the start of a row: a leading 'I.' read as '|.' or 'l.'."""
    return re.sub(r"^[|l1]\.\s?", "I. ", text)


def parse_frame(words: list[dict], points: list[dict] | None = None, width: int = WIDTH,
                height: int | None = None) -> list[dict]:
    """The player rows in one frame: {name, pct, salary, points, game}. points: words from the points column."""
    lines = _lines(words)
    for ln in lines:
        ln["text"] = _clean(ln["text"])
    height = height or max((ln["bottom"] for ln in lines), default=0)
    anchors = []
    for i, ln in enumerate(lines):
        m = ROW_RE.match(ln["text"])
        if m and ln["words"][0]["left"] < width * 0.5:
            anchors.append((i, m))
    if not anchors:
        return []
    gaps = [lines[b[0]]["top"] - lines[a[0]]["top"] for a, b in zip(anchors, anchors[1:])]
    row_h = statistics.median(gaps) if gaps else None
    rows = []
    for k, (i, m) in enumerate(anchors):
        top = lines[i]["top"]
        whole = k + 1 < len(anchors) or bool(row_h and top + row_h * 0.95 <= height)
        end = lines[anchors[k + 1][0]]["top"] if k + 1 < len(anchors) else top + (row_h or 0)
        block = [ln for ln in lines if top - 5 <= ln["top"] < end - 5]
        text = " ".join(ln["text"] for ln in block)
        sal = SALARY_RE.search(text)
        game = GAME_RE.search(text)
        if not whole and not sal:          # cut off at the bottom of the frame: trust only the name line
            sal = game = None
        pts = [w["text"] for w in points or [] if POINTS_RE.match(w["text"]) and top - 10 <= w["top"] < end - 10] \
            if (whole or sal) else []
        rows.append({
            "name": re.sub(r"\s+", " ", m.group("name")).strip(),
            "pct": float(m.group("pct").replace(",", ".")),
            "salary": int(sal.group(1) + sal.group(2)) if sal else None,
            "points": float(pts[0].replace(",", ".")) if pts else None,
            "game": f"{game.group(1)} {game.group(2)} @ {game.group(3)} {game.group(4)}" if game else None,
        })
    return rows


SUFFIX_RE = re.compile(r"^(?:[il1|]{2,3}|iv|v|jr|sr)$")      # II / III as OCR reads them (Ill, IIl, lll...), Jr., Sr.


def _key(name: str) -> str:
    """'C. Hubbard' -> 'c hubbard'; 'K. Walker Ill' (OCR of III) -> 'k walker'."""
    toks = normalize_name(name).split()
    return " ".join(t for i, t in enumerate(toks) if not (i > 1 and SUFFIX_RE.match(t)))


def merge(frames: list[list[dict]]) -> list[dict]:
    """Pool every frame's reading of each row; each field takes its most common value."""
    pooled: dict[str, dict[str, Counter]] = {}
    seen: dict[str, int] = {}
    for rows in frames:
        for r in rows:
            k = _key(r["name"])
            if not k:
                continue
            d = pooled.setdefault(k, {f: Counter() for f in ("name", "pct", "salary", "points", "game")})
            seen[k] = seen.get(k, 0) + 1
            for f in d:
                if r.get(f) is not None:
                    d[f][r[f]] += 1
    out = []
    for k, d in pooled.items():
        out.append({f: (c.most_common(1)[0][0] if c else None) for f, c in d.items()} | {"frames": seen[k]})
    return out


def _last_and_initial(name: str) -> tuple[str, str]:
    toks = _key(name).split()
    if not toks:
        return "", ""
    return toks[-1], toks[0][0] if len(toks) > 1 else ""


def match(rows: list[dict], players: list[dict]) -> tuple[list[dict], list[str]]:
    """Attach each row to a slate player ({key, name, team, position, salary}). Returns (matched, unmatched names)."""
    matched, unmatched = [], []
    for r in rows:
        last, initial = _last_and_initial(r["name"])
        teams = set(r["game"].replace("@", " ").split()[0::2]) if r.get("game") else set()
        cands = []
        for p in players:
            if p["position"] == "DST":
                nick = normalize_name(p["name"]).split()
                if nick and _key(r["name"]).split() and _key(r["name"]).split()[-1] == nick[-1]:
                    cands.append(p)
                continue
            toks = _key(p["name"]).split()
            if toks and toks[-1] == last and (not initial or toks[0][0] == initial):
                cands.append(p)
        if len(cands) > 1 and r.get("salary"):
            cands = [p for p in cands if p.get("salary") == r["salary"]] or cands
        if len(cands) > 1 and teams:
            cands = [p for p in cands if p["team"] in teams] or cands
        keys = {p["key"] for p in cands}
        if len(keys) == 1:
            matched.append({**r, "player": cands[0]})
        else:
            unmatched.append(r["name"])
    return matched, unmatched


def read_video(video: Path) -> dict:
    """{"rows": merged rows, "frames": frames read}."""
    with tempfile.TemporaryDirectory() as tmp:
        frames = extract_frames(video, Path(tmp))
        if not frames:
            raise ValueError("No frames could be read from that file")
        with ThreadPoolExecutor(OCR_WORKERS) as ex:
            words = list(ex.map(ocr_words, [f for f, _ in frames]))
            pts = list(ex.map(lambda p: ocr_words(p, digits=True), [p for _, p in frames]))
        heights = [_height(f) for f, _ in frames]
    return {"rows": merge([parse_frame(w, p, WIDTH, h) for w, p, h in zip(words, pts, heights)]), "frames": len(frames)}
