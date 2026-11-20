"""Core data types shared by every module.

Three things come out of a scan:

  Fact      a measured property of the target (top-k is 4, chunk size is 1000)
  Finding   a security-relevant conclusion drawn from facts
  Chunk     a passage the target handed back while we were measuring

Facts carry how they were measured and how far that method can be trusted.
A fact whose precondition was not met is still emitted, with status
``not-applicable`` and a reason. A detector never disappears silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Severity = Literal["info", "low", "medium", "high"]

FactStatus = Literal[
    "measured",         # we have a value
    "not-applicable",   # precondition not met; reason says which
    "skipped-budget",   # dropped to stay under the request ceiling
    "skipped-level",    # needs a higher --level
    "error",            # the detector raised
]

SEVERITY_ORDER: dict[str, int] = {"high": 0, "medium": 1, "low": 2, "info": 3}


@dataclass
class Confidence:
    """How much the number deserves to be trusted.

    ``kind`` is the nature of the measurement:
      direct      read straight off the response (no inference)
      derived     computed from several direct observations
      heuristic   a judgement call that can be wrong

    ``calibration`` is filled from data/calibration.json when the detector
    has been measured against known ground truth. Unlike a hand-written
    "high"/"medium" label, it means something: hit rate and error on a grid
    of targets whose true configuration was known.
    """
    kind: Literal["direct", "derived", "heuristic"] = "heuristic"
    calibration: str = ""

    def render(self) -> str:
        return self.calibration or ""


@dataclass
class Fact:
    key: str                      # "retrieval.top_k"
    label: str                    # "top-k"
    section: str = "retrieval"    # output grouping
    value: Any = None
    display: str = ""             # "4 (fixed)"
    method: str = ""              # one line: how it was measured
    evidence: str = ""            # shown in brackets after the value
    status: FactStatus = "measured"
    reason: str = ""              # why not measured
    confidence: Confidence = field(default_factory=Confidence)

    @property
    def ok(self) -> bool:
        return self.status == "measured"

    def rendered(self) -> str:
        if self.ok:
            return self.display or ("-" if self.value is None else str(self.value))
        return {
            "not-applicable": "not applicable",
            "skipped-budget": "skipped (budget)",
            "skipped-level": "skipped (level)",
            "error": "error",
        }.get(self.status, self.status)


@dataclass
class Finding:
    id: str                       # "RAGMAP-001"
    title: str
    severity: Severity
    summary: str                  # one line shown next to the id
    detail: str = ""
    evidence: str = ""
    facts: list[str] = field(default_factory=list)


@dataclass
class Chunk:
    """A passage observed in a response.

    We never ask for passages we do not need; these are the ones the target
    returned while answering the probes the scan had to send anyway.
    """
    text: str
    query: str = ""
    doc_id: str | None = None
    # The identifier of the passage itself, not of its document. It was
    # already being read off the response and then dropped here, which cost
    # the scan everything a chunk id can say: how a corpus is indexed, how
    # much of a document has been seen, and whether two documents share an
    # id they should not.
    chunk_id: str | None = None
    title: str | None = None
    page: Any = None
    score: float | None = None

    @property
    def source_label(self) -> str:
        parts = [p for p in (self.title or self.doc_id,) if p]
        if self.page not in (None, ""):
            parts.append(f"p{self.page}")
        return "  ".join(parts) if parts else "(unidentified source)"

    @property
    def named_only(self) -> bool:
        """Named by the target but not shown: identifiers, no passage."""
        return not (self.text or "").strip()

    def fingerprint(self) -> str:
        # Fingerprint the passage body. A product that prefixes every chunk
        # with a constant metadata header would otherwise make all passages
        # of one document look like the same chunk, and they would be
        # deduplicated away before anything could measure them.
        from .transport import strip_envelope
        if self.named_only:
            # Nothing to fingerprint but the name, so the identifier is the
            # identity. Without this every hidden passage of one document
            # would collapse into one entry and the coverage bound would
            # read a corpus of hundreds as a corpus of five.
            return f"{self.doc_id or self.title or ''}|#{self.chunk_id or ''}"
        head = " ".join(strip_envelope(self.text).split())[:120]
        return f"{self.doc_id or self.title or ''}|{head}"


class ChunkStore:
    """Deduplicating collection of observed chunks, in order of first sight."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self.items: list[Chunk] = []

    def add(self, chunk: Chunk) -> bool:
        # A passage with neither text nor a name is nothing at all. One
        # with a name and no text is an O2 disclosure and is kept: what the
        # target refuses to show, it still agrees to count.
        if not (chunk.text or "").strip() and not (
                chunk.chunk_id or chunk.doc_id or chunk.title):
            return False
        key = chunk.fingerprint()
        if key in self._seen:
            return False
        self._seen.add(key)
        self.items.append(chunk)
        return True

    def __len__(self) -> int:
        return len(self.items)

    def by_document(self) -> dict[str, list[Chunk]]:
        grouped: dict[str, list[Chunk]] = {}
        for chunk in self.items:
            key = chunk.doc_id or chunk.title or "(unknown)"
            grouped.setdefault(key, []).append(chunk)
        return grouped


@dataclass
class ModuleOutcome:
    name: str
    status: str                   # "ran" | "not-applicable" | "skipped-..." | "error"
    reason: str = ""
    requests: int = 0
    seconds: float = 0.0


@dataclass
class ScanResult:
    target: str
    level: int
    started_at: str = ""
    finished_at: str = ""
    duration_s: float = 0.0
    requests_used: int = 0
    budget: int = 0
    spend: str = ""
    tokens_used: int = 0
    tokens_measured: bool = False
    token_budget: int = 0
    requests_saved: int = 0
    facts: dict[str, Fact] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    modules: list[ModuleOutcome] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    out_dir_label: str = ""

    def sorted_findings(self) -> list[Finding]:
        return sorted(self.findings,
                      key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.id))
