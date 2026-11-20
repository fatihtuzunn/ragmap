"""How loud this scan is, measured rather than assumed.

A tool that thinks about detection usually offers a stealth mode: slower
pacing, softer wording, a warning when the operator types something
obvious. ragmap does those things too. But a mode is a promise, and a
promise about detection is exactly the kind of claim this tool refuses to
make anywhere else. The confidence beside a measured value comes from a
calibration run; the token spend comes from the target's own counters. The
footprint should come from the same place: the traffic actually sent.

So this is a meter, not a mode. Every query the scan sends is matched
against the patterns in ``data/opsec.json``, and the report ends with the
count per category - next to the request count and the token count. "This
scan sent five questions a corpus-enumeration rule would flag" is
something an operator can hand to a client, argue with, or design around.
"Stealth mode: on" is not.

Three things follow from building it this way.

The patterns are derived from ragmap's own captured traffic rather than
from a general list of prompt attacks, so the categories describe what a
read-only scanner really sends: corpus questions, repeated topic probes,
quotation requests, malformed inputs. Two categories cover text ragmap
never generates; they exist because ``--topic`` and ``--seed-queries``
carry the operator's words to the target, and those are worth checking.

A pattern with a ``burst`` threshold counts only once that rate is
reached. One "what does the document say about X" is a user; twenty inside
a minute is a sweep. A rule that fired on the first would be useless to
its owner, so modelling it that way would overstate our own noise.

Operator-supplied text is checked before the scan starts and warned about
immediately, because by the time it appears in a tally it has been sent.
"""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parent / "data" / "opsec.json"

# A rule fires on a rate, so matches are counted inside a sliding window.
BURST_WINDOW = 60.0

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def compile_trigger(pattern: str) -> re.Pattern:
    """Turn ``what * documents`` into a regex that matches whole words.

    ``*`` stands for any run of characters. Everything else is literal and
    anchored on word boundaries, which is what keeps "token" out of
    "tokenisation" and "pto" out of "optometrist" - the kind of match that
    would quietly inflate a footprint figure nobody can audit.
    """
    parts = []
    for fragment in pattern.split("*"):
        fragment = fragment.strip()
        if not fragment:
            continue
        escaped = re.escape(fragment)
        if fragment[0].isalnum():
            escaped = r"\b" + escaped
        if fragment[-1].isalnum():
            escaped = escaped + r"\b"
        parts.append(escaped)
    if not parts:
        # A pattern of nothing but stars would match every query ever sent.
        return re.compile(r"(?!x)x")
    return re.compile(r".*?".join(parts), re.IGNORECASE | re.DOTALL)


@dataclass
class Category:
    name: str
    description: str = ""
    severity: str = "medium"
    advice: str = ""
    burst: int = 0
    operator_supplied: bool = False
    patterns: list[tuple[str, re.Pattern]] = field(default_factory=list)

    def match(self, text: str) -> str | None:
        for source, regex in self.patterns:
            if regex.search(text):
                return source
        return None


@dataclass
class Meter:
    """Counts what the scan's own traffic would trip."""
    categories: dict[str, Category] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    examples: dict[str, str] = field(default_factory=dict)
    seen: int = 0
    _window: dict[str, list[float]] = field(
        default_factory=lambda: defaultdict(list))

    # -- observation -----------------------------------------------------
    def observe(self, query: str, *, now: float | None = None) -> list[str]:
        """Record one outgoing query; return the categories it trips."""
        if not query:
            return []
        self.seen += 1
        moment = time.monotonic() if now is None else now
        tripped: list[str] = []

        for category in self.categories.values():
            hit = category.match(query)
            if hit is None:
                continue

            if category.burst:
                stamps = self._window[category.name]
                stamps.append(moment)
                stamps[:] = [s for s in stamps if moment - s < BURST_WINDOW]
                if len(stamps) < category.burst:
                    # Below the rate its owner set, the rule does not fire,
                    # and counting it would overstate our own noise.
                    continue

            self.counts[category.name] += 1
            self.examples.setdefault(category.name, query[:90])
            tripped.append(category.name)

        return tripped

    # -- reporting -------------------------------------------------------
    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def ranked(self) -> list[tuple[Category, int]]:
        rows = [(self.categories[name], count)
                for name, count in self.counts.items()
                if name in self.categories]
        rows.sort(key=lambda row: (SEVERITY_ORDER.get(row[0].severity, 9),
                                   -row[1]))
        return rows

    def summary(self) -> str:
        rows = self.ranked()
        if not rows:
            return f"nothing flagged in {self.seen} queries"
        shown = ", ".join(f"{cat.name} x{count}" for cat, count in rows[:3])
        more = f" (+{len(rows) - 3})" if len(rows) > 3 else ""
        return f"{self.total} of {self.seen} queries flagged: {shown}{more}"

    def check(self, text: str) -> list[Category]:
        """Match without recording - for text that has not been sent yet."""
        return [category for category in self.categories.values()
                if category.match(text or "") is not None]


def load(overlay: Path | None = None) -> Meter:
    """Build a meter from the shipped rules, plus the operator's own."""
    meter = Meter()
    _merge(meter, _read(RULES_PATH))
    if overlay is not None:
        if not overlay.is_file():
            raise SystemExit(f"opsec rules not found: {overlay}")
        _merge(meter, _read(overlay))
    return meter


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"could not read opsec rules {path}: {exc}") from exc


def _merge(meter: Meter, data: dict) -> None:
    for name, raw in (data.get("categories") or {}).items():
        if not isinstance(raw, dict):
            continue
        patterns = [(str(t), compile_trigger(str(t)))
                    for t in raw.get("triggers", ())]
        existing = meter.categories.get(name)
        if existing is None:
            meter.categories[name] = Category(
                name=name,
                description=str(raw.get("description", "")),
                severity=str(raw.get("severity", "medium")),
                advice=str(raw.get("advice", "")),
                burst=int(raw.get("burst", 0) or 0),
                operator_supplied=bool(raw.get("operator_supplied", False)),
                patterns=patterns)
            continue
        # An overlay of the same name extends rather than replaces, so an
        # operator adds what their client's rules look for without losing
        # the patterns everyone's rules look for.
        existing.patterns = existing.patterns + patterns
        for text_field in ("description", "severity", "advice"):
            if raw.get(text_field):
                setattr(existing, text_field, str(raw[text_field]))
        if raw.get("burst"):
            existing.burst = int(raw["burst"])
        if raw.get("operator_supplied") is not None:
            existing.operator_supplied = bool(raw.get(
                "operator_supplied", existing.operator_supplied))
