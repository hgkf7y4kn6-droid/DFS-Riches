"""Mechanical fact check: every figure in the written report must exist in the dossier.

Pulls the numbers out of each section's text and looks for each one among
the dossier's own values (also as percentages and American prices). Small
counting numbers, years, weeks and dates are allowed. Anything else is
"unverified" -- the desk's guard against invented odds, injuries or ownership.
"""
from __future__ import annotations

import re

NUM = re.compile(r"(?<![\w.])[-−+]?\$?\d[\d,]*(?:\.\d+)?%?")
DATE = re.compile(r"\b\d{1,2}/\d{1,2}\b|\b\d{1,2}:\d{2}\b")


def known_values(obj, out: set | None = None) -> set[float]:
    out = set() if out is None else out
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        v = float(obj)
        out.update({round(v, 2), round(abs(v), 2)})
        if -1.0 <= v <= 1.0:
            out.update({round(v * 100, 1), round(abs(v) * 100, 1), float(round(v * 100)), float(round(abs(v) * 100))})
        return out
    if isinstance(obj, dict):
        for x in obj.values():
            known_values(x, out)
    elif isinstance(obj, (list, tuple)):
        for x in obj:
            known_values(x, out)
    elif isinstance(obj, str):
        for m in NUM.finditer(obj):
            v = _value(m.group())
            if v is not None:
                out.update({v, abs(v)})
    return out


def _value(token: str) -> float | None:
    t = token.replace("−", "-").replace("$", "").replace(",", "").rstrip("%").lstrip("+")
    try:
        return round(float(t), 2)
    except ValueError:
        return None


def _allowed(v: float, token: str) -> bool:
    a = abs(v)
    if a <= 12 and float(a).is_integer() and "%" not in token:
        return True                          # counts, ranks, section numbers, small whole numbers
    if 2000 <= a <= 2100 and float(a).is_integer():
        return True                          # years
    return False


def check(text: str, known: set[float]) -> list[str]:
    clean = DATE.sub(" ", text)
    bad = []
    for m in NUM.finditer(clean):
        tok = m.group()
        v = _value(tok)
        if v is None or _allowed(v, tok):
            continue
        a = abs(v)
        if any(abs(a - k) <= 0.051 for k in known if abs(k - a) <= 1):
            continue
        bad.append(tok)
    return sorted(set(bad))


def check_sections(sections: dict[int, str], dossier: dict, tables: dict) -> dict[int, list[str]]:
    known = known_values(dossier)
    known_values(tables, known)
    return {n: bad for n, text in sections.items() if (bad := check(text, known))}
