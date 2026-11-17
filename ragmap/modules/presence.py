"""Level 1 - is there a retrieval layer at all?

Three kinds of evidence, in descending strength:

1. The response carries retrieved passages. Conclusive.
2. Answers contain specifics no general model could know, while a plainly
   general question is answered too. Suggestive.
3. Corpus-shaped questions are measurably slower than general-knowledge
   ones. A retrieval round trip costs time; a plain model call does not.

Timing alone is never enough - network noise and model warm-up produce the
same shape - so it is used only to support, never to decide on its own.
"""

from __future__ import annotations

from statistics import median

from ..context import Context
from ..registry import Module, register

GENERAL_QUERIES = [
    "What is the capital of France?",
    "What is 17 multiplied by 4?",
    "Who wrote Pride and Prejudice?",
]

CORPUS_QUERIES = [
    "What do your internal documents say about required procedures?",
    "Summarise the obligations described in your documentation.",
    "What policies are described in the documents you can access?",
]


@register
class RagPresence(Module):
    name = "presence.rag"
    section = "retrieval"
    level = 1
    cost = 6
    value = 4
    requires = ("iface.shape",)
    provides = ("rag.present", "timing.general_ms", "timing.corpus_ms")
    description = "Decide whether a retrieval layer exists"

    def run(self, ctx: Context) -> None:
        if ctx.satisfied("obs.source_field"):
            field = ctx.get("obs.source_field")
            ctx.set_fact("rag.present", "rag present", True, display="yes",
                         method="retrieved passages present in the response",
                         evidence=f"source field '{field}'", kind="direct")
            self._timings(ctx, measure=False)
            return

        general, corpus = self._timings(ctx, measure=True)
        if general is None or corpus is None:
            ctx.set_fact("rag.present", "rag present", None, display="unconfirmed",
                         method="no structured sources and timing unavailable",
                         kind="heuristic")
            return

        delta = corpus - general
        # A retrieval round trip is rarely cheaper than 80ms end to end.
        likely = delta > 80
        ctx.set_fact(
            "rag.present", "rag present", likely,
            display="likely" if likely else "not detected",
            method="median latency of corpus-shaped vs general-knowledge queries",
            evidence=f"{delta:+.0f}ms delta ({corpus:.0f}ms vs {general:.0f}ms)",
            kind="heuristic")
        if not likely:
            ctx.note("No structured sources and no latency separation. The "
                     "target may be a plain model endpoint rather than RAG; "
                     "retrieval parameters below will read as not applicable.")

    @staticmethod
    def _timings(ctx: Context, measure: bool):
        general_times: list[float] = []
        corpus_times: list[float] = []

        if measure:
            for query in GENERAL_QUERIES:
                if ctx.transport.remaining <= 3:
                    break
                probe = ctx.ask(query, fresh=True)
                if probe.ok:
                    general_times.append(probe.latency_ms)
            for query in CORPUS_QUERIES:
                if ctx.transport.remaining <= 1:
                    break
                probe = ctx.ask(query, fresh=True)
                if probe.ok:
                    corpus_times.append(probe.latency_ms)

        general = median(general_times) if general_times else None
        corpus = median(corpus_times) if corpus_times else None

        if general is not None:
            ctx.set_fact("timing.general_ms", "general query latency", general,
                         display=f"{general:.0f} ms",
                         method=f"median of {len(general_times)} requests",
                         kind="direct")
        if corpus is not None:
            ctx.set_fact("timing.corpus_ms", "corpus query latency", corpus,
                         display=f"{corpus:.0f} ms",
                         method=f"median of {len(corpus_times)} requests",
                         kind="direct")
        return general, corpus
