"""Bumps the app version's third number (1.0.4 -> 1.0.5) before an update is
pushed: mobile/app.json (what Settings shows), mobile/package.json and
mobile/package-lock.json stay in step.

    python -m scripts.bump_version          # bump and print the new version
    python -m scripts.bump_version --check  # print the current version
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MOBILE = Path(__file__).resolve().parent.parent / "mobile"
APP_JSON, PACKAGE_JSON, LOCK_JSON = MOBILE / "app.json", MOBILE / "package.json", MOBILE / "package-lock.json"


def current() -> str:
    return json.loads(APP_JSON.read_text())["expo"]["version"]


def next_version(version: str) -> str:
    major, minor, patch = (int(x) for x in version.split("."))
    return f"{major}.{minor}.{patch + 1}"


def _set_first_version(path: Path, old: str, new: str) -> None:
    # Edit in place (first "version" key only) so the rest of the file keeps its formatting.
    text = path.read_text()
    text, n = re.subn(rf'"version": "{re.escape(old)}"', f'"version": "{new}"', text, count=1)
    if not n:
        raise SystemExit(f"{path.name}: version {old} not found")
    path.write_text(text)


def bump() -> str:
    old = current()
    new = next_version(old)
    _set_first_version(APP_JSON, old, new)
    _set_first_version(PACKAGE_JSON, old, new)
    lock = json.loads(LOCK_JSON.read_text())
    lock["version"] = new
    lock["packages"][""]["version"] = new
    LOCK_JSON.write_text(json.dumps(lock, indent=2) + "\n")
    return new


if __name__ == "__main__":
    print(current() if "--check" in sys.argv else bump())
