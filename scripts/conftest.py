"""Keep pytest from collecting analysis scripts whose optional dependencies are missing (e.g. CI has no pandas)."""
import importlib.util

collect_ignore = []
if importlib.util.find_spec("pandas") is None:
    collect_ignore.append("test_injury_years.py")
