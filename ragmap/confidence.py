"""Calibrated confidence.

A detector's confidence should say how often it has been *right*, not how
tidy its inputs looked. This module reads ``data/calibration.json``, which is
produced by running the scanner against a grid of targets whose true
configuration is known (see ``mockrag/``), and renders a short note such as::

    cal 24/24, MAE 0

When a detector has no calibration entry yet, nothing is printed rather than
an invented label. Silence is more honest than "high".
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent / "data" / "calibration.json"


@lru_cache(maxsize=1)
def _table() -> dict:
    try:
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def note_for(fact_key: str, observability: str | None = None) -> str:
    """Short calibration note for a fact, conditioned on observability level."""
    table = _table().get("facts", {})
    entry = table.get(fact_key)
    if not entry:
        return ""

    scoped = None
    if observability and isinstance(entry.get("by_observability"), dict):
        scoped = entry["by_observability"].get(observability)
    stats = scoped or entry.get("overall")
    if not isinstance(stats, dict):
        return ""

    hits, total = stats.get("hits"), stats.get("total")
    parts = []
    if isinstance(hits, int) and isinstance(total, int) and total:
        parts.append(f"cal {hits}/{total}")
    mae = stats.get("mae")
    if isinstance(mae, (int, float)):
        parts.append(f"MAE {mae:g}")
    return ", ".join(parts)


def generated_at() -> str:
    return _table().get("generated_at", "")
