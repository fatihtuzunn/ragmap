"""Scan context: the shared state every module reads and writes."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, TYPE_CHECKING

from . import confidence as confidence_mod
from .config import ScanConfig
from .model import Chunk, ChunkStore, Confidence, Fact, Finding, ModuleOutcome
from .transport import Probe, Transport

if TYPE_CHECKING:
    from .registry import Module


class Context:
    def __init__(self, config: ScanConfig, transport: Transport):
        self.config = config
        self.transport = transport
        self.facts: dict[str, Fact] = {}
        self.findings: list[Finding] = []
        self.chunks = ChunkStore()
        self.outcomes: list[ModuleOutcome] = []
        self.notes: list[str] = []
        self.probes: list[Probe] = []
        self.shape: Any = None            # ragmap.shapes.Shape
        self.discovery: Any = None        # ragmap.discovery.Discovery
        self._current: "Module | None" = None
        # Detectors overlap: half a dozen of them want to see what the
        # target returns for the corpus topic, and before this they each
        # bought their own copy. An answered question is kept and handed to
        # the next module that asks it. Detectors for which repetition IS
        # the measurement - caching, determinism - ask with fresh=True.
        self._answered: dict[tuple, Probe] = {}
        self.reused = 0
        self.reused_by: dict[str, int] = {}

    # -- module lifecycle ------------------------------------------------
    def begin(self, module: "Module") -> None:
        self._current = module

    def end(self) -> None:
        self._current = None

    def record_outcome(self, outcome: ModuleOutcome) -> None:
        self.outcomes.append(outcome)

    # -- probing ---------------------------------------------------------
    def ask(self, query: str, *, fresh: bool = False, **kwargs) -> Probe:
        """Send one query and harvest any passages it returns.

        Unless ``fresh`` is set, a question this scan has already put to the
        target is answered from the earlier exchange instead of being bought
        again. Only clean exchanges are kept: replaying a rate-limited reply
        would turn one upstream failure into evidence for every detector
        that happened to ask the same thing.

        Pass ``fresh=True`` wherever asking twice is the measurement - a
        cache shows itself in the second reply's latency, determinism in the
        second reply's wording - or wherever a stale latency would be read
        as this module's own timing sample.
        """
        key = self._ask_key(query, kwargs)
        if not fresh:
            earlier = self._answered.get(key)
            if earlier is not None:
                self.reused += 1
                owner = self._current.name if self._current else "scan"
                self.reused_by[owner] = self.reused_by.get(owner, 0) + 1
                return replace(earlier, cached=True)

        probe = self.transport.send(query, **kwargs)
        self.probes.append(probe)
        self.harvest(probe)
        if probe.ok and (probe.answer or probe.sources):
            self._answered.setdefault(key, probe)
        return probe

    @staticmethod
    def _ask_key(query: str, kwargs: dict) -> tuple:
        """Two asks match only if the whole request would have matched."""
        extras = tuple(sorted(
            (name, json.dumps(value, sort_keys=True, default=str))
            for name, value in kwargs.items() if value is not None))
        return (query, extras)

    def harvest(self, probe: Probe) -> None:
        for entry in probe.sources:
            if entry.text:
                self.chunks.add(Chunk(
                    text=entry.text, query=probe.query, doc_id=entry.doc_id,
                    title=entry.title, page=entry.page, score=entry.score))

    # -- facts -----------------------------------------------------------
    def set_fact(self, key: str, label: str, value: Any = None, *,
                 display: str = "", method: str = "", evidence: str = "",
                 section: str | None = None,
                 kind: str = "heuristic") -> Fact:
        note = confidence_mod.note_for(key, self.get("obs.level"))
        fact = Fact(
            key=key, label=label, value=value,
            display=display or ("" if value is None else str(value)),
            method=method, evidence=evidence,
            section=section or (self._current.section if self._current else "misc"),
            confidence=Confidence(kind=kind, calibration=note),
        )
        self.facts[key] = fact
        return fact

    def skip_fact(self, key: str, *, status: str, reason: str,
                  module: "Module | None" = None) -> None:
        """Placeholder for a fact a module could not measure."""
        if key in self.facts and self.facts[key].ok:
            return
        owner = module or self._current
        self.facts[key] = Fact(
            key=key, label=_default_label(key),
            section=owner.section if owner else "misc",
            status=status, reason=reason,
        )

    def get(self, key: str, default: Any = None) -> Any:
        fact = self.facts.get(key)
        return fact.value if fact is not None and fact.ok else default

    def satisfied(self, key: str) -> bool:
        fact = self.facts.get(key)
        return bool(fact and fact.ok and fact.value not in (None, False, "", [], {}))

    # -- findings --------------------------------------------------------
    def add_finding(self, finding: Finding) -> None:
        if any(existing.id == finding.id for existing in self.findings):
            return
        self.findings.append(finding)

    def note(self, text: str) -> None:
        if text and text not in self.notes:
            self.notes.append(text)


def _default_label(key: str) -> str:
    return key.split(".")[-1].replace("_", " ")
