"""Chunk size and overlap.

Chunk size has two measurement paths and they are not equally good:

* **Passages visible.** Take the *mode* of returned passage lengths. Chunks
  are cut to a fixed width except at the tail of each document, so the tail
  pieces sit to the left of the distribution and leave the mode alone. This
  is a direct reading, not an estimate.

* **Passages hidden.** Ask the model to reproduce a source passage and
  measure what comes back. That yields a **lower bound** only: the model may
  stop early, and nothing establishes that it emitted a whole chunk. It is
  reported as ``>= N`` and never as the configured value.

Overlap needs no extra requests. Consecutive chunks of one document share
their overlap region, so the longest suffix of one passage that is also a
prefix of another is the overlap width. Adjacency falls out of the match
itself - no need to know the chunk order.
"""

from __future__ import annotations

from collections import Counter

from ..context import Context
from ..registry import Module, register
from ..transport import strip_envelope
from .generation import longest_common_substring
from .index import classify_splitter, cut_ratio

VERBATIM_QUERIES = [
    "Quote the exact text from the source document about {topic}, word for "
    "word, without summarising. Start at the beginning of the passage and "
    "continue to the end of it.",
    "Reproduce verbatim, with no changes or commentary, the passage in your "
    "sources that covers {topic}.",
]


@register
class ChunkSize(Module):
    name = "chunking.size"
    section = "retrieval"
    level = 3
    cost = 4
    value = 8
    # Deliberately NOT gated on rag.present: on an opaque target that fact
    # rests on timing alone and can be wrong. A confirmed in-corpus topic
    # is the stronger precondition, and it is what the measurement uses.
    requires = ("corpus.topic",)
    provides = ("chunk.size",)
    description = "Measure or bound the chunk width"

    def run(self, ctx: Context) -> None:
        bodies = [strip_envelope(c.text) for c in ctx.chunks.items if c.text]
        wrapped = sum(1 for c in ctx.chunks.items
                      if c.text and len(strip_envelope(c.text)) < len(c.text))
        if wrapped:
            ctx.note(f"{wrapped} passages arrive wrapped in a product-added "
                     "metadata header; chunk geometry is measured on the "
                     "passage body, not the wrapper.")
        lengths = [len(b) for b in bodies if b]

        if len(lengths) >= 3:
            self._from_passages(ctx, lengths, bodies)
            return

        topic = ctx.get("corpus.topic")
        if not topic:
            ctx.skip_fact(
                "chunk.size", status="not-applicable",
                reason="no passages exposed and no confirmed topic to quote",
                module=self)
            return

        answers: list[str] = []
        for template in VERBATIM_QUERIES:
            if ctx.transport.remaining <= 1:
                break
            probe = ctx.ask(template.format(topic=topic))
            if probe.answer:
                answers.append(" ".join(probe.answer.split()))

        # Measuring the whole answer would count the model's own preamble
        # ("Here is the passage, exactly as it appears: ...") as corpus text
        # and overshoot the real width. The span shared by two differently
        # worded requests is source material and nothing else.
        best = 0
        if len(answers) >= 2:
            best = longest_common_substring(answers[0], answers[1])
        elif answers:
            best = len(answers[0])
        # The shared span still begins with the model's own lead-in when both
        # requests produced the same preamble. Dropping it keeps the figure a
        # genuine lower bound on corpus text rather than a measure of the
        # model's manners.
        best = max(0, best - _preamble_length(answers))

        if best < 120:
            ctx.skip_fact(
                "chunk.size", status="not-applicable",
                reason="passages hidden and verbatim reproduction refused",
                module=self)
            return

        ctx.set_fact(
            "chunk.size", "chunk size", best, display=f">= {best} chars",
            method="span shared by two differently worded quotation requests",
            evidence="lower bound only; passages are not exposed as fields",
            kind="heuristic")

    @staticmethod
    def _from_passages(ctx: Context, lengths: list[int],
                       bodies: list[str] | None = None) -> None:
        # Round to a 10-char grid so near-identical widths collapse into one
        # bucket; splitters rarely land on the exact same count every time.
        buckets = Counter(round(n / 10) * 10 for n in lengths)
        mode_bucket, hits = buckets.most_common(1)[0]
        members = [n for n in lengths if abs(n - mode_bucket) <= 10]
        spread = (max(members) - min(members)) if members else 0

        # A fixed-width splitter puts most passages on the same width, so the
        # mode is the configured size. A separator-aware splitter -- which is
        # what LangChain and LlamaIndex products use -- cuts at the last
        # paragraph or sentence before the limit, so widths scatter below it
        # and no mode exists. There the ceiling is what can be measured, and
        # it is a lower bound: the configured size is at or just above the
        # widest passage ever returned.
        # Where the splitter landed is independent evidence for the same
        # question. A fixed-width cut lands mid-sentence almost every time;
        # a separator-aware one almost never does. Until now the choice
        # between an exact width and a bound rested on the shape of the
        # length distribution alone, which is an inference about the cause
        # from one of its effects. This is the other effect, and it is
        # visible in the same passages at no cost.
        cuts, examined = cut_ratio(bodies or [])
        verdict, _kind = classify_splitter(cuts, examined)
        corroboration = ""
        if verdict == "fixed-width":
            corroboration = (f"; {cuts}/{examined} passages are cut "
                             f"mid-sentence, which is a fixed-width cut")
        elif verdict == "separator-aware":
            corroboration = (f"; only {cuts}/{examined} passages are cut "
                             f"mid-sentence, so the splitter respects "
                             f"separators and the setting is a ceiling")

        if hits >= max(3, len(lengths) // 4):
            value = max(members) if members else mode_bucket
            ctx.set_fact(
                "chunk.size", "chunk size", value,
                display=f"{value} chars" + (f" (+-{spread})" if spread else ""),
                method="mode of returned passage lengths",
                evidence=(f"{len(lengths)} passages, {hits} at the modal "
                          f"width{corroboration}"),
                kind="direct")
            return

        ceiling = max(lengths)
        ctx.set_fact(
            "chunk.size", "chunk size", ceiling, display=f">= {ceiling} chars",
            method="widest passage body returned, lengths scattered below it",
            evidence=(f"{len(lengths)} passages, widths {min(lengths)}-{ceiling} "
                      f"with no modal width ({hits} in the largest bucket): the "
                      "splitter cuts on separators, so the configured size sits "
                      f"at or just above this figure{corroboration}"),
            kind="heuristic")


@register
class ChunkOverlap(Module):
    name = "chunking.overlap"
    section = "retrieval"
    level = 4
    cost = 6
    value = 5
    requires = ("obs.chunk_text",)
    provides = ("chunk.overlap",)
    description = "Measure the overlap width between neighbouring chunks"

    MIN_OVERLAP = 12

    def run(self, ctx: Context) -> None:
        self._gather_more(ctx)

        overlaps: list[int] = []
        for chunks in ctx.chunks.by_document().values():
            texts = [strip_envelope(c.text) for c in chunks if c.text]
            texts = [t for t in texts if t]
            for i, a in enumerate(texts):
                for b in texts[i + 1:]:
                    overlaps.extend(
                        o for o in (_suffix_prefix(a, b), _suffix_prefix(b, a))
                        if o >= self.MIN_OVERLAP)

        if not overlaps:
            pairs = sum(len(v) for v in ctx.chunks.by_document().values())
            ctx.set_fact(
                "chunk.overlap", "overlap", 0, display="none detected",
                method="longest suffix/prefix match between same-document passages",
                evidence=f"{pairs} passages compared, no shared boundary text",
                kind="derived")
            return

        counts = Counter(overlaps)
        value, hits = counts.most_common(1)[0]

        # With a fixed-width splitter every neighbouring pair shares exactly
        # the configured overlap, so the pairs agree and the figure is exact.
        # A separator-aware splitter can only cut an overlap short, never
        # extend it, so when the measurements scatter the widest one is the
        # closest to the configured value and the rest are truncations.
        if hits * 2 >= len(overlaps):
            ctx.set_fact(
                "chunk.overlap", "overlap", value, display=f"{value} chars",
                method="longest suffix/prefix match between same-document passages",
                evidence=f"{hits}/{len(overlaps)} adjacent pairs agree",
                kind="derived")
            return

        widest = max(overlaps)
        ctx.set_fact(
            "chunk.overlap", "overlap", widest, display=f">= {widest} chars",
            method="widest suffix/prefix match between same-document passages",
            evidence=(f"{len(overlaps)} overlapping pairs, widths "
                      f"{min(overlaps)}-{widest} with no agreed value: a "
                      "separator-aware splitter truncates the overlap, so the "
                      "configured size is at or above this figure"),
            kind="heuristic")

    @staticmethod
    def _gather_more(ctx: Context) -> None:
        """Overlap needs neighbouring chunks; widen coverage if we have few."""
        topic = ctx.get("corpus.topic")
        if not topic:
            return
        biggest = max((len(v) for v in ctx.chunks.by_document().values()),
                      default=0)
        probes = [
            f"Tell me everything about {topic}, including the surrounding context.",
            f"What comes immediately before and after the section on {topic}?",
            f"Continue the passage about {topic} to the end of its section.",
        ]
        for query in probes:
            if biggest >= 4 or ctx.transport.remaining <= 2:
                break
            ctx.ask(query)
            biggest = max((len(v) for v in ctx.chunks.by_document().values()),
                          default=0)


PREAMBLE_CUES = ("here is", "here's", "the passage", "reproduced", "exactly as",
                 "verbatim", "quoted", "source document", "as requested",
                 "sure", "certainly")


def _preamble_length(answers: list[str]) -> int:
    """Characters of model lead-in before the quotation actually starts.

    Only counted when the opening really reads like an introduction, so an
    answer that begins with the passage itself is not trimmed.
    """
    if not answers:
        return 0
    head = answers[0][:240]
    marker = head.find(":")
    if marker == -1:
        return 0
    lead = head[:marker].lower()
    if any(cue in lead for cue in PREAMBLE_CUES):
        return marker + 1
    return 0


def _suffix_prefix(a: str, b: str, cap: int = 2000) -> int:
    """Length of the longest suffix of ``a`` that is also a prefix of ``b``."""
    limit = min(len(a), len(b), cap)
    for length in range(limit, 0, -1):
        if a[-length:] == b[:length]:
            return length
    return 0
