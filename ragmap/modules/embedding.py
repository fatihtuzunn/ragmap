"""Level 5 - embedding behaviour.

An honest limit first: without control of the corpus you cannot identify the
embedding model. Published fingerprinting work relies on inserting known
documents and reading back distances, which is a write, and writes are out of
scope for reconnaissance.

What *is* observable is behaviour. Whether retrieval survives a change of
language, of case, or of accents tells you something real about the encoder
and is useful when planning retrieval-manipulation attempts. No model name is
claimed from it.
"""

from __future__ import annotations

import unicodedata

from ..context import Context
from ..registry import Module, register


@register
class EmbeddingProperties(Module):
    name = "embedding.properties"
    section = "retrieval"
    level = 5
    cost = 4
    value = 4
    requires = ("obs.source_field", "corpus.topic")
    provides = ("embedding.properties",)
    description = "Probe encoder behaviour (language, case, accents)"

    def run(self, ctx: Context) -> None:
        topic = ctx.get("corpus.topic")
        baseline = ctx.ask(f"What does the document say about {topic}?")
        if not baseline.source_count:
            ctx.skip_fact("embedding.properties", status="not-applicable",
                          reason="baseline query returned no passages",
                          module=self)
            return

        properties: list[str] = []
        evidence: list[str] = []

        variants = [
            ("multilingual", f"Belgelerde {topic} hakkinda ne yaziyor?"),
            ("case-insensitive", f"WHAT DOES THE DOCUMENT SAY ABOUT {topic.upper()}?"),
            ("accent-tolerant",
             f"What does the document say about {_add_accents(topic)}?"),
        ]

        for label, query in variants:
            if ctx.transport.remaining <= 1:
                break
            probe = ctx.ask(query)
            retrieved = bool(probe.source_count)
            if retrieved:
                properties.append(label)
            evidence.append(f"{label}:{'hit' if retrieved else 'miss'}")

        ctx.set_fact(
            "embedding.properties", "embedding behaviour", properties,
            display=", ".join(properties) if properties else "none observed",
            method="baseline query re-sent in altered forms",
            evidence="; ".join(evidence), kind="heuristic")
        ctx.note("Embedding model identity is not inferable without writing "
                 "documents to the corpus; only behaviour was measured.")


def _add_accents(text: str) -> str:
    table = str.maketrans({"a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú"})
    swapped = text.translate(table)
    return unicodedata.normalize("NFC", swapped)
