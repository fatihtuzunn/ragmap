"""What the index itself gives away, from passages already collected.

Neither detector here sends a request. Both read the passages other probes
brought back, which means they are free and that running them is never a
reason to spend more of the target's allowance.

Two different things are measured.

**The identifier scheme.** A chunk id is not decoration. When ids are
sequential within a document, the ones you have seen bound the ones you
have not: having seen ``policy#c0``, ``#c1``, ``#c4`` says that document
has at least five chunks and that three of them are still unread. That
converts a pile of passages into a coverage figure - how much of this
corpus has actually been recovered - which is the number an operator wants
and the one no other detector produces. Ids also expose indexing defects:
the same id under two different documents means the store cannot tell them
apart, and a retrieval hit on one can serve the other.

**The quality of the cut.** Where the splitter lands is visible from the
passages themselves. A chunk that starts lowercase was cut mid-sentence; one
that ends without terminal punctuation was cut before its sentence
finished; one that opens with "However," has lost the clause it refers to.
Those are not style complaints. A retriever embeds what it was given, so a
corpus cut through the middle of its sentences answers worse than the same
corpus cut on paragraph boundaries, and the count of bad cuts is the
cheapest evidence that a pipeline needs re-chunking. The same pass finds
text that should not be in a text index at all - base64 payloads, encoded
attachments - and passages duplicated across documents, which quietly spend
a target's top-k on the same sentences twice.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict

from .. import findings, tokens
from ..context import Context
from ..registry import Module, register
from ..transport import strip_envelope

# A trailing integer is what makes an id countable. Everything before it is
# the scope: ``policy.md#c12`` scopes to one document, ``chunk_000412``
# scopes to the whole store.
TRAILING_NUMBER = re.compile(r"(\d+)\s*$")

# A uuid ends in hex, and hex sometimes ends in digits. Reading those as a
# sequence position turns "chunk 3 of this document" into "chunk 700", so
# identifiers of this shape are opaque by definition: random by design,
# and random ids say nothing about order or coverage.
UUID_LIKE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE)
HEX_BLOB = re.compile(r"^[0-9a-f]{16,}$", re.IGNORECASE)


def _is_opaque(chunk_id: str) -> bool:
    bare = chunk_id.strip()
    return bool(UUID_LIKE.match(bare) or HEX_BLOB.match(bare))

# An opening that refers to something the passage does not contain.
ORPHAN_OPENING = re.compile(
    r"^(\.{3}|…|however|but|and|so|therefore|furthermore|moreover|"
    r"additionally|otherwise|instead|in addition)\b[,\s]",
    re.IGNORECASE)

TERMINAL = set(".!?:;…\"')]}”")

# A structural line: a markdown heading, a numbered section, a list item.
# A passage that stops on one of these stopped at a boundary, even though
# the line carries no full stop. Without this the detector reads every
# cleanly cut markdown corpus as badly cut, because a separator-aware
# splitter lands on "## 4. Manual workarounds" all day long.
STRUCTURAL = re.compile(r"^(#{1,6}\s|\d+(\.\d+)*\.?\s+\S|[-*\u2022]\s)")


def ends_cleanly(text: str) -> bool:
    """True when the passage stops where a splitter would choose to stop."""
    text = text.rstrip()
    if not text:
        return True
    if text[-1] in TERMINAL:
        return True
    last_line = text.rsplit("\n", 1)[-1].strip()
    return (bool(last_line) and len(last_line) <= 90
            and bool(STRUCTURAL.match(last_line)))



def _split_id(chunk_id: str) -> tuple[str, int | None]:
    """Split ``policy#c12`` into its scope and its number."""
    match = TRAILING_NUMBER.search(chunk_id)
    if not match:
        return chunk_id, None
    return chunk_id[:match.start()], int(match.group(1))


@register
class IndexIdentifiers(Module):
    name = "chunking.index"
    section = "corpus"
    # Level 2: it sends nothing, and knowing how much of a corpus is still
    # unread belongs in the same report as knowing which documents exist.
    level = 2
    cost = 0
    value = 7
    # An inventory: more passages can only sharpen it, never contradict it.
    resettle = True
    requires = ("obs.source_field",)
    provides = ("chunk.id_scheme", "chunk.coverage", "chunk.collisions")
    description = "Read the chunk identifier scheme and corpus coverage"

    def run(self, ctx: Context) -> None:
        labelled = [c for c in ctx.chunks.items if c.chunk_id]
        if not labelled:
            for key in self.provides:
                ctx.skip_fact(key, status="not-applicable",
                              reason="no chunk identifiers are returned",
                              module=self)
            return

        # Random identifiers carry no order, so nothing downstream of a
        # sequence number can be measured from them. Say that once, rather
        # than letting each sub-detector invent a number from noise.
        opaque = sum(1 for c in labelled if _is_opaque(c.chunk_id))
        if opaque >= len(labelled) / 2:
            ctx.set_fact(
                "chunk.id_scheme", "id scheme", "opaque",
                display="opaque (random identifiers)", section="corpus",
                method=f"{opaque} of {len(labelled)} identifiers are uuids "
                       f"or hex blobs",
                evidence=labelled[0].chunk_id[:46], kind="direct")
            for key in ("chunk.coverage",):
                ctx.skip_fact(key, status="not-applicable",
                              reason="identifiers are random, so nothing "
                                     "about order or coverage follows from "
                                     "them",
                              module=self)
            self._collisions(ctx, labelled)
            return

        self._scheme(ctx, labelled)
        self._coverage(ctx, labelled)
        self._collisions(ctx, labelled)

    # -- the scheme ------------------------------------------------------
    def _scheme(self, ctx: Context, labelled: list) -> None:
        numbered = [(c, _split_id(c.chunk_id)) for c in labelled]
        with_number = [(c, scope, n) for c, (scope, n) in numbered
                       if n is not None]

        if not with_number:
            ctx.set_fact("chunk.id_scheme", "id scheme", "opaque",
                         display="opaque", section="corpus",
                         method="no trailing number in any identifier",
                         evidence=labelled[0].chunk_id[:60], kind="direct")
            return

        # Scoped per document when each document's ids carry their own
        # prefix and the numbering restarts; global when one run of numbers
        # spans everything.
        scopes = {scope for _, scope, _ in with_number}
        by_doc: dict[str, list[int]] = defaultdict(list)
        for chunk, _scope, number in with_number:
            by_doc[chunk.source_label].append(number)

        starts = [min(values) for values in by_doc.values()]
        restarts = len(by_doc) > 1 and len(set(starts)) == 1
        scoping = "per document" if (restarts or len(scopes) > 1) else "global"
        base = min(starts) if starts else 0

        parts = [f"{scoping}, {base}-based"]
        widths = {len(str(n)) for _, _, n in with_number}
        padded = any(str(n) != c.chunk_id[-len(str(n)):]
                     for c, _s, n in with_number[:1])          # cheap probe
        if len(widths) == 1 and padded:
            parts.append("zero-padded")

        ctx.set_fact(
            "chunk.id_scheme", "id scheme", scoping,
            display=", ".join(parts), section="corpus",
            method="trailing number and prefix of every identifier seen",
            evidence=", ".join(sorted({c.chunk_id for c in labelled})[:3]),
            kind="direct")

    # -- coverage --------------------------------------------------------
    def _coverage(self, ctx: Context, labelled: list) -> None:
        """How much of what the target indexed has actually been seen.

        Sequential ids make this measurable rather than guessable: the
        highest number seen in a document is a floor on that document's
        chunk count, and the numbers missing below it are passages the scan
        never retrieved. It is a lower bound in both directions - there may
        be more chunks above the highest id seen - so it is reported as one.
        """
        by_doc: dict[str, set[int]] = defaultdict(set)
        for chunk in labelled:
            _scope, number = _split_id(chunk.chunk_id)
            if number is not None:
                by_doc[chunk.source_label].add(number)

        if not by_doc:
            ctx.skip_fact("chunk.coverage", status="not-applicable",
                          reason="identifiers carry no sequence number",
                          module=self)
            return

        seen = sum(len(values) for values in by_doc.values())
        implied = 0
        gaps: list[str] = []
        for label, values in sorted(by_doc.items()):
            low, high = min(values), max(values)
            implied += high - low + 1
            missing = sorted(set(range(low, high + 1)) - values)
            if missing:
                shown = ", ".join(str(m) for m in missing[:6])
                more = f" (+{len(missing) - 6})" if len(missing) > 6 else ""
                gaps.append(f"{label}: {shown}{more}")

        # A real sequence is dense: a scan sees a decent share of the range
        # its own ids span. When the numbers are scattered across a range
        # many times larger than the count, they are not positions in a
        # sequence - they are digits that happened to be there - and the
        # honest answer is that coverage cannot be read from them.
        if implied > 3 * max(seen, 1):
            ctx.skip_fact(
                "chunk.coverage", status="not-applicable",
                reason=f"the {seen} identifiers seen span a range of "
                       f"{implied}, too sparse to be sequence positions",
                module=self)
            return

        unseen = implied - seen
        # "37 of 38" reads like near-complete coverage. The floor is the
        # point: the ids prove at least this many exist, and chunks
        # numbered above the highest one seen leave no gap to notice.
        display = (f"{seen} seen, >= {implied} exist"
                   + (f" ({unseen} never retrieved)" if unseen
                      else " (no gaps below the highest id)"))

        ctx.set_fact(
            "chunk.coverage", "coverage", seen, display=display,
            section="corpus",
            method="sequence numbers present and absent across the documents "
                   "seen; a floor, since chunks above the highest id seen "
                   "would not show as a gap",
            evidence="; ".join(gaps[:3]) if gaps else
                     f"{len(by_doc)} document(s), contiguous",
            kind="derived")

    # -- collisions ------------------------------------------------------
    def _collisions(self, ctx: Context, labelled: list) -> None:
        owners: dict[str, set[str]] = defaultdict(set)
        for chunk in labelled:
            owners[chunk.chunk_id].add(chunk.source_label)
        clashing = sorted(cid for cid, docs in owners.items() if len(docs) > 1)

        if not clashing:
            ctx.set_fact("chunk.collisions", "id collisions", 0,
                         display="none", section="corpus",
                         method=f"{len(owners)} distinct identifiers, each "
                                f"seen under one document",
                         kind="direct")
            return

        ctx.set_fact(
            "chunk.collisions", "id collisions", clashing,
            display=f"{len(clashing)} shared by 2+ documents",
            section="corpus",
            method="the same identifier returned under more than one "
                   "document title",
            evidence=", ".join(clashing[:4]), kind="direct")
        ctx.add_finding(findings.make(
            "RAGMAP-011",
            f"{len(clashing)} chunk identifier(s) are shared by more than "
            f"one document",
            evidence=", ".join(clashing[:5]),
            facts=("chunk.collisions",)))


@register
class IndexQuality(Module):
    name = "chunking.quality"
    section = "corpus"
    level = 3
    cost = 0
    value = 6
    resettle = True
    requires = ("obs.chunk_text",)
    provides = ("chunk.tokens", "chunk.splitter", "chunk.duplicates")
    description = "Measure passage length in tokens and how cleanly text was cut"

    def run(self, ctx: Context) -> None:
        bodies = [(c, strip_envelope(c.text)) for c in ctx.chunks.items
                  if c.text]
        bodies = [(c, body) for c, body in bodies if body.strip()]
        if len(bodies) < 2:
            for key in self.provides:
                ctx.skip_fact(key, status="not-applicable",
                              reason="too few passages were returned to "
                                     "measure anything",
                              module=self)
            return

        self._tokens(ctx, bodies)
        self._cuts(ctx, bodies)
        self._duplicates(ctx, bodies)

    # -- length in the units the chunker was configured in ---------------
    def _tokens(self, ctx: Context, bodies: list) -> None:
        counts = sorted(tokens.count(body) for _c, body in bodies)
        median = int(statistics.median(counts))
        p95 = counts[min(len(counts) - 1, int(0.95 * (len(counts) - 1)))]
        widest = counts[-1]

        measured = tokens.available()
        note = "" if measured else " (estimated)"
        if not measured:
            ctx.note("Passage lengths in tokens are estimated at four "
                     "characters each. Install the optional tokeniser for "
                     "real counts: pip install 'ragmap[tokens]'.")
        window = min((limit for limit in tokens.EMBEDDING_WINDOWS.values()
                      if limit >= widest), default=None)

        ctx.set_fact(
            "chunk.tokens", "chunk tokens", widest,
            display=f"median {median}, p95 {p95}, max {widest}{note}",
            section="corpus",
            method=f"{len(counts)} passage bodies counted with "
                   f"{tokens.encoding_name()}",
            evidence=(f"fits an encoder window of {window}" if window
                      else "wider than every embedding window ragmap knows"),
            kind="direct" if measured else "heuristic")

    # -- where the splitter landed ---------------------------------------
    def _cuts(self, ctx: Context, bodies: list) -> None:
        mid_start = mid_end = orphan = blob = 0
        samples: list[str] = []

        for chunk, body in bodies:
            text = body.strip()
            if not text:
                continue
            if text[0].isalpha() and text[0].islower():
                mid_start += 1
                if len(samples) < 3:
                    samples.append(text[:48])
            if len(text) > 50 and not ends_cleanly(text):
                mid_end += 1
            if ORPHAN_OPENING.match(text):
                orphan += 1
            if _looks_encoded(text):
                blob += 1

        cuts, examined = cut_ratio([body for _c, body in bodies])
        verdict, kind = classify_splitter(cuts, examined)

        detail = []
        if mid_start:
            detail.append(f"{mid_start} open mid-sentence, which the overlap "
                          f"explains")
        if orphan:
            detail.append(f"{orphan} orphaned continuation")
        if samples:
            detail.append("; ".join(f'"{s}..."' for s in samples))

        ctx.set_fact(
            "chunk.splitter", "splitter", verdict,
            display=f"{verdict} ({cuts}/{examined} cut mid-sentence)",
            section="corpus",
            method="where each passage stops: a fixed window lands "
                   "mid-sentence, a separator-aware splitter does not. Only "
                   "the end of a passage is evidence; where one starts is "
                   "set by the overlap step",
            evidence=" | ".join(detail),
            kind=kind)

        if blob:
            ctx.add_finding(findings.make(
                "RAGMAP-013",
                f"{blob} retrieved passage(s) are encoded data rather than "
                f"prose",
                evidence=f"{blob} of {len(bodies)} passages",
                facts=("chunk.splitter",)))

    # -- the same text, filed twice --------------------------------------
    def _duplicates(self, ctx: Context, bodies: list) -> None:
        by_text: dict[str, set[str]] = defaultdict(set)
        for chunk, body in bodies:
            key = " ".join(body.split())[:400]
            if len(key) >= 80:
                by_text[key].add(chunk.source_label)

        shared = {text: docs for text, docs in by_text.items()
                  if len(docs) > 1}
        repeats = Counter(" ".join(body.split())[:400] for _c, body in bodies)
        within = sum(1 for text, n in repeats.items() if n > 1 and
                     text not in shared)

        if not shared:
            ctx.set_fact(
                "chunk.duplicates", "duplicates", 0,
                display="none across documents", section="corpus",
                method=f"{len(by_text)} distinct passage bodies compared",
                evidence=(f"{within} passage(s) returned more than once "
                          f"from the same document" if within else ""),
                kind="direct")
            return

        example = next(iter(shared))
        ctx.set_fact(
            "chunk.duplicates", "duplicates", len(shared),
            display=f"{len(shared)} passage(s) in 2+ documents",
            section="corpus",
            method="identical passage bodies returned under different "
                   "document titles",
            evidence=f'"{example[:60]}..."', kind="direct")
        ctx.add_finding(findings.make(
            "RAGMAP-012",
            f"{len(shared)} passage(s) are indexed under more than one "
            f"document",
            evidence=", ".join(sorted(next(iter(shared.values())))[:3]),
            facts=("chunk.duplicates",)))


# Below this share of mid-sentence endings a splitter is respecting
# separators; above the other, it is cutting on a fixed window. Between
# them the evidence does not settle it, and the detector says so rather
# than rounding to the nearer story.
SEPARATOR_AWARE_BELOW = 0.25
FIXED_WIDTH_ABOVE = 0.60


def classify_splitter(cuts: int, examined: int) -> tuple[str, str]:
    """Name the splitter family, or decline. Returns (verdict, confidence)."""
    if examined < 4:
        return "unclear", "heuristic"
    share = cuts / examined
    if share >= FIXED_WIDTH_ABOVE:
        return "fixed-width", "direct"
    if share <= SEPARATOR_AWARE_BELOW:
        return "separator-aware", "direct"
    return "unclear", "heuristic"


def cut_ratio(bodies: list[str]) -> tuple[int, int]:
    """How many of these passages were cut through a sentence.

    Shared with the chunk-size detector, which uses it as independent
    evidence for whether a width is a hard setting or a ceiling. Counted
    once here so the two detectors cannot drift apart and disagree in the
    same report.
    """
    cuts = examined = 0
    for body in bodies:
        text = (body or "").strip()
        if len(text) < 40:
            continue
        examined += 1
        # Only the END is evidence. Where a passage starts is decided by
        # the overlap step - step back N characters from the previous cut
        # and you land mid-sentence whatever the splitter prefers - so a
        # lowercase opening says nothing about how the boundary was chosen.
        # Where a passage stops is the splitter's own decision.
        if not ends_cleanly(text):
            cuts += 1
    return cuts, examined


def _looks_encoded(text: str) -> bool:
    """A long unbroken run of base64-ish characters is not prose.

    The test is deliberately narrow. Long words exist, and so do URLs and
    hashes inside ordinary text; what does not happen in prose is a
    hundred-character run with no space in it that is also almost entirely
    base64's alphabet.
    """
    if len(text) < 120:
        return False
    longest = max((len(part) for part in text.split()), default=0)
    if longest < 120:
        return False
    run = max(text.split(), key=len)
    alphabet = sum(1 for ch in run if ch.isalnum() or ch in "+/=-_")
    return alphabet / len(run) > 0.97
