"""Level 2 - derive probe values from the target's own corpus."""

from __future__ import annotations

from .. import discovery as discovery_mod
from .. import findings
from ..context import Context
from ..registry import Module, register


@register
class CorpusDiscovery(Module):
    name = "corpus.discover"
    section = "corpus"
    level = 2
    cost = 14
    value = 6
    requires = ("iface.shape",)
    provides = ("corpus.topic", "corpus.second_topic", "corpus.absent_topic",
                "corpus.rare_token", "corpus.topics")
    description = "Derive in-corpus and off-corpus probe values"

    def run(self, ctx: Context) -> None:
        # Spend no more than the cost this module declares: the planner
        # bought it at that price and the rest of the scan is counting on
        # the change.
        budget = max(6, min(self.cost, ctx.transport.remaining // 2))
        result = discovery_mod.run(ctx, budget=budget)
        ctx.discovery = result

        for note in result.notes:
            ctx.note(note)

        self._topic_fact(ctx, "corpus.topic", "topic", result.topic,
                         result.evidence.get("topic"))
        self._topic_fact(ctx, "corpus.second_topic", "second topic",
                         result.second_topic, result.evidence.get("second_topic"))
        self._topic_fact(ctx, "corpus.absent_topic", "off-corpus topic",
                         result.absent_topic, result.evidence.get("absent_topic"))
        self._topic_fact(ctx, "corpus.rare_token", "rare token",
                         result.rare_token, result.evidence.get("rare_token"))

        if result.topics_seen:
            ctx.set_fact("corpus.topics", "topics", result.topics_seen,
                         display=", ".join(result.topics_seen[:3]) + (
                             f" (+{len(result.topics_seen) - 3})"
                             if len(result.topics_seen) > 3 else ""),
                         method="extracted from meta-query answers and source labels",
                         kind="heuristic")
        else:
            ctx.skip_fact("corpus.topics", status="not-applicable",
                          reason="no topic candidates could be extracted",
                          module=self)

    def _topic_fact(self, ctx: Context, key: str, label: str,
                    value: str | None, evidence: dict | None) -> None:
        if not value:
            ctx.skip_fact(key, status="not-applicable",
                          reason="could not be confirmed against the target",
                          module=self)
            return
        bits = ""
        if evidence:
            parts = []
            if "signal" in evidence:
                parts.append(f"signal {evidence['signal']}")
            if evidence.get("source_count") is not None:
                parts.append(f"{evidence['source_count']} sources")
            if evidence.get("refused"):
                parts.append("refused")
            bits = ", ".join(parts)
        ctx.set_fact(key, label, value, display=value,
                     method="candidate put to the target and confirmed",
                     evidence=bits, kind="derived")


@register
class CorpusObserved(Module):
    """What the target named, counted over the whole scan.

    This used to be part of corpus discovery, which meant the inventory was
    a snapshot of the first dozen exchanges. Against a live AnythingLLM the
    report then said "2 visible ids" above a passage list naming five
    documents. An inventory is a summary of everything seen, so it costs no
    requests and is recomputed once the scan is done.
    """
    name = "corpus.observed"
    section = "corpus"
    # Level 1: it sends nothing, and the identifier disclosure it reports is
    # exactly what a first look at a target should surface.
    level = 1
    cost = 0
    value = 3
    resettle = True
    requires = ("iface.shape",)
    provides = ("corpus.documents", "corpus.identifiers")
    description = "Inventory the documents and identifiers the target revealed"

    def run(self, ctx: Context) -> None:
        labels: list[str] = []
        for chunk in ctx.chunks.items:
            for value in (chunk.doc_id, chunk.title):
                if value:
                    labels.append(str(value))
        documents = discovery_mod._dedupe(labels)[:50]

        if documents:
            ctx.set_fact("corpus.documents", "documents", documents,
                         display=f"{len(documents)} visible ids",
                         method="distinct identifiers returned in source fields "
                                "across the whole scan",
                         evidence=", ".join(documents[:3]), kind="direct")
            ctx.add_finding(findings.make(
                "RAGMAP-005",
                f"{len(documents)} document identifiers visible",
                evidence=", ".join(documents[:5]),
                facts=("corpus.documents",)))
        else:
            ctx.skip_fact("corpus.documents", status="not-applicable",
                          reason="no document identifiers were returned",
                          module=self)

        texts = [c.text for c in ctx.chunks.items if c.text][:80]
        texts += [p.answer for p in ctx.probes if p.answer][:60]
        found = discovery_mod.extract_candidates(texts)
        merged = discovery_mod._dedupe(found["identifiers"][:20]
                                       + found["filenames"][:20])

        if merged:
            ctx.set_fact("corpus.identifiers", "identifiers", merged,
                         display=", ".join(merged[:4]),
                         method="identifier-shaped literals seen in passages "
                                "and answers",
                         kind="heuristic")
        else:
            ctx.skip_fact("corpus.identifiers", status="not-applicable",
                          reason="no identifier-shaped literals observed",
                          module=self)
