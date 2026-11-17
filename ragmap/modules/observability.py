"""Level 1 - how much the system tells you about its own retrieval.

The observability level decides what every later detector can do. If chunk
text is on screen, chunk size is a direct measurement. If nothing is
structured, the same number can only be bounded from below, through the
answer text. Getting this wrong poisons everything downstream, which is why
it is measured first and measured conservatively.

    O3  passage text + similarity score + source count
    O2  source identifiers and count, no passage text
    O1  sources named only inside the answer prose
    O0  answer text only
"""

from __future__ import annotations

import re

from .. import findings
from ..context import Context
from ..registry import Module, register
from ..transport import BudgetExhausted

PASSAGE_MIN_CHARS = 180

# Narrative attribution: "according to the Data Retention Policy", "as stated
# in section 4 of the handbook", "Source: policy.pdf".
ATTRIBUTION_PATTERNS = [
    r"\baccording to\b",
    r"\bas (?:stated|described|set out|outlined) in\b",
    r"\bper the\b",
    r"\bbased on the\b[^.]{0,40}\b(?:policy|document|standard|plan|guide|handbook|manual|report)\b",
    r"\bthe\b[^.]{0,40}\b(?:policy|standard|procedure|handbook|plan)\b\s+(?:states|says|requires|specifies)\b",
    r"\bsources?\s*:",
    r"\[\s*(?:source|doc|ref)\s*\d+\s*\]",
    r"\b\w[\w\-]{2,40}\.(?:pdf|docx?|md|txt|pptx?)\b",
]

PROBE_QUERIES = [
    "What are the key policies or procedures described in your documents?",
    "Summarise the most important requirements in your knowledge base.",
]


@register
class Observability(Module):
    name = "observability.level"
    section = "retrieval"
    level = 1
    cost = 0
    value = 9
    requires = ("iface.shape",)
    provides = ("obs.level", "obs.source_field", "obs.chunk_text",
                "obs.scores")
    description = "Classify how much retrieval detail is exposed"

    def run(self, ctx: Context) -> None:
        # The extra probes only enrich what earlier modules already
        # collected. With no budget left -- or in replay, where there is none
        # by definition -- classification still runs on the recorded
        # exchanges.
        for query in PROBE_QUERIES:
            if ctx.transport.remaining <= 1:
                break
            try:
                ctx.ask(query)
            except BudgetExhausted:
                break

        # A rate-limited or crashed target still replies with a well-formed
        # body that simply has no sources in it. Counting those as evidence
        # reports an O3 system as O0, which is the worst failure this
        # scanner can produce: every later detector is gated on this answer.
        usable = [p for p in ctx.probes if p.ok and (p.answer or p.sources)]
        if not usable:
            failures = [p.error for p in ctx.probes if p.error]
            reason = failures[-1] if failures else "no exchange returned an answer"
            if len(reason) > 160:
                reason = reason[:157] + "..."
            for key in self.provides:
                ctx.skip_fact(key, status="error",
                              reason=f"no usable exchange: {reason}")
            ctx.note("observability could not be classified: "
                     f"{len(ctx.probes)} probes, none usable")
            return

        source_field = None
        has_text = False
        has_scores = False
        identifiers: list[str] = []
        longest = 0

        for probe in ctx.probes:
            if probe.source_field and source_field is None:
                source_field = probe.source_field
            for entry in probe.sources:
                if entry.text:
                    longest = max(longest, len(entry.text))
                    if len(entry.text) >= PASSAGE_MIN_CHARS:
                        has_text = True
                if entry.score is not None:
                    has_scores = True
                for value in (entry.title, entry.doc_id):
                    if value and str(value) not in identifiers:
                        identifiers.append(str(value))
                if entry.page not in (None, ""):
                    has_page = f"page={entry.page}"
                    if has_page not in identifiers:
                        identifiers.append(has_page)

        # --- source field -------------------------------------------------
        if source_field:
            ctx.set_fact("obs.source_field", "source field", source_field,
                         display=source_field,
                         method="structural search for a retrieved-passage list",
                         kind="direct")
        else:
            ctx.set_fact("obs.source_field", "source field", None,
                         display="none",
                         method="no list in the response looked like retrieval results",
                         kind="direct")

        # --- chunk text ---------------------------------------------------
        ctx.set_fact("obs.chunk_text", "chunk text", has_text,
                     display="exposed" if has_text else "not exposed",
                     method=f"longest passage field seen: {longest} chars",
                     kind="direct")

        ctx.set_fact("obs.scores", "scores", has_scores,
                     display="exposed" if has_scores else "not exposed",
                     method="numeric relevance field inside source entries",
                     kind="direct")

        # --- level --------------------------------------------------------
        if has_text:
            level, evidence = "O3", "passage text" + (
                " and scores exposed" if has_scores else " exposed, no scores")
        elif source_field or identifiers:
            level, evidence = "O2", "structured sources without passage text"
        else:
            narrative = self._narrative_attribution(ctx)
            if narrative:
                level, evidence = "O1", f"prose attribution: {narrative}"
            else:
                level, evidence = "O0", "no sources in fields or prose"

        ctx.set_fact("obs.level", "observability", level, display=level,
                     method="field inspection, then prose attribution",
                     evidence=evidence, kind="derived")

        # --- findings -----------------------------------------------------
        if has_text:
            ctx.add_finding(findings.make(
                "RAGMAP-006",
                f"passages returned in '{source_field}' (longest {longest} chars)",
                evidence=f"{longest} characters of corpus text in one field",
                facts=("obs.chunk_text", "obs.source_field")))
        if has_scores:
            ctx.add_finding(findings.make(
                "RAGMAP-009", "relevance scores returned with each passage",
                facts=("obs.scores",)))

    @staticmethod
    def _narrative_attribution(ctx: Context) -> str:
        for probe in ctx.probes:
            for pattern in ATTRIBUTION_PATTERNS:
                match = re.search(pattern, probe.answer or "", re.IGNORECASE)
                if match:
                    text = " ".join((probe.answer or "").split())
                    start = max(0, match.start() - 10)
                    return text[start:start + 60].strip()
        return ""
