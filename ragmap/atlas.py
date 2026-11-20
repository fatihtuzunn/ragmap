"""MITRE ATLAS technique references for the findings this scanner reports.

ATLAS techniques describe what an *adversary does*. A ragmap finding
describes what a *system exposes*. They are not the same thing, and the
mapping below should be read in one direction only: this exposure makes
that technique available to someone who wants it. A report that says
"RAGMAP-005 enables AML.T0064" is making a claim about reachability, not
alleging that anybody has done it.

Several findings are deliberately left unmapped. A chunk identifier
collision and a duplicated passage are defects worth fixing, but no ATLAS
technique describes exploiting them, and inventing a reference to fill the
column would make the whole table less trustworthy.

Every id and name here was read from the current ATLAS release named in
VERSION below. The previous `dist/ATLAS.yaml` is deprecated and its names
are stale: the catalogue renamed "ML" to "AI" throughout, and some ids it
carried no longer exist. Anything not confirmed against the current file
is left out rather than guessed - a wrong technique id in a client report
is worse than an empty column, because the reader cannot tell it is wrong.

To re-verify, read dist/ATLAS-latest.yaml in mitre-atlas/atlas-data, which
points at the current release file.
"""

from __future__ import annotations

# The release these names were taken from. Printed with the mapping so a
# reader can tell how old it is.
VERSION = "ATLAS 2026.10 (2026-10-28)"

TECHNIQUES: dict[str, str] = {
    "AML.T0007": "Discover AI Artifacts",
    "AML.T0024": "Exfiltration via AI Inference API",
    "AML.T0025": "Exfiltration via Cyber Means",
    "AML.T0040": "AI Model Inference API Access",
    "AML.T0064": "Gather RAG-Indexed Targets",
    "AML.T0070": "RAG Poisoning",
    "AML.T0085.000": "RAG Databases",
}


def name(technique: str) -> str:
    return TECHNIQUES.get(technique, "")


def label(technique: str) -> str:
    """``AML.T0064 Gather RAG-Indexed Targets``, or the bare id."""
    title = TECHNIQUES.get(technique)
    return f"{technique} {title}" if title else technique


def unknown(ids) -> list[str]:
    """Ids with no entry here - a guard for the test, not for the scan."""
    return [t for t in ids if t not in TECHNIQUES]
