"""Retrieval parameters: top-k, similarity threshold, retrieval mode, reranker."""

from __future__ import annotations

import re
from collections import Counter

from .. import findings
from ..context import Context
from ..registry import Module, register

TOPK_QUERIES = [
    "What does the document say about {topic}?",
    "Explain {topic} in detail.",
    "{topic}",
    "Give me every detail you have about {topic} and anything related to it.",
    "Briefly: {topic}?",
    "List all requirements connected to {topic}.",
]

NONSENSE = "qwfhjkl zxcvbnmasd poiuytrewq lkjhgfdsa"


@register
class TopK(Module):
    name = "retrieval.topk"
    section = "retrieval"
    level = 2
    cost = 6
    value = 10
    requires = ("obs.source_field", "corpus.topic")
    provides = ("retrieval.top_k",)
    description = "Estimate how many passages are retrieved per query"

    def run(self, ctx: Context) -> None:
        topic = ctx.get("corpus.topic")
        counts: list[int] = []
        for template in TOPK_QUERIES:
            if ctx.transport.remaining <= 2:
                break
            probe = ctx.ask(template.format(topic=topic))
            if probe.source_count:
                counts.append(probe.source_count)

        if not counts:
            ctx.skip_fact("retrieval.top_k", status="not-applicable",
                          reason="no query returned a non-empty source list",
                          module=self)
            return

        unique = sorted(set(counts))
        mode = Counter(counts).most_common(1)[0][0]
        fixed = len(unique) == 1

        ctx.set_fact(
            "retrieval.top_k", "top-k", mode,
            display=f"{mode} (fixed)" if fixed else f"{mode} (varies {unique})",
            method="source-list length across differently shaped queries",
            evidence=f"{counts.count(mode)}/{len(counts)} queries returned {mode}",
            kind="direct" if fixed else "derived")

        if not fixed:
            ctx.note(f"Source count varied across queries ({unique}). That is "
                     f"dynamic retrieval, a similarity threshold trimming the "
                     f"list, or a reranker dropping candidates.")


@register
class Threshold(Module):
    name = "retrieval.threshold"
    section = "retrieval"
    level = 2
    cost = 6
    value = 8
    requires = ("obs.source_field", "corpus.topic", "corpus.absent_topic")
    provides = ("retrieval.threshold",)
    description = "Detect whether a similarity cut-off is applied"

    def run(self, ctx: Context) -> None:
        topic = ctx.get("corpus.topic")
        second = ctx.get("corpus.second_topic") or topic
        absent = ctx.get("corpus.absent_topic")

        ladder = [
            ("on topic", f"What does the document say about {topic}?"),
            ("related", f"What does the document say about {second}?"),
            ("off domain", f"What does the document say about {absent}?"),
            ("nonsense", NONSENSE),
        ]

        observed: list[tuple[str, int, list[float]]] = []
        for label, query in ladder:
            if ctx.transport.remaining <= 1:
                break
            probe = ctx.ask(query)
            observed.append((label, probe.source_count or 0, probe.scores))

        if not observed:
            ctx.skip_fact("retrieval.threshold", status="not-applicable",
                          reason="ladder could not be sent", module=self)
            return

        trace = ", ".join(f"{label}:{count}" for label, count, _ in observed)
        cutoff = next((label for label, count, _ in observed if count == 0), None)

        if cutoff is None:
            all_scores = [s for _, _, scores in observed for s in scores]
            floor = f", lowest score {min(all_scores):.3f}" if all_scores else ""
            ctx.set_fact(
                "retrieval.threshold", "threshold", None, display="none",
                method="relevance ladder from on-topic down to nonsense",
                evidence=f"passages returned at every step ({trace}){floor}",
                kind="derived")
            ctx.add_finding(findings.make(
                "RAGMAP-002",
                "nonsense and off-domain queries still return passages",
                evidence=trace, facts=("retrieval.threshold",)))
            return

        surviving = [s for _, _, scores in observed for s in scores]
        bound = f"above {min(surviving):.3f}" if surviving else "unknown value"
        ctx.set_fact(
            "retrieval.threshold", "threshold", cutoff,
            display=f"applied (cuts at '{cutoff}')",
            method="relevance ladder from on-topic down to nonsense",
            evidence=f"{trace}; lowest surviving score {bound}",
            kind="derived")


@register
class RetrievalMode(Module):
    name = "retrieval.mode"
    section = "retrieval"
    level = 3
    cost = 6
    value = 6
    requires = ("obs.source_field", "corpus.topic")
    provides = ("retrieval.mode",)
    description = "Separate dense from lexical/hybrid retrieval"

    def run(self, ctx: Context) -> None:
        rare = ctx.get("corpus.rare_token")
        topic = ctx.get("corpus.topic")
        scores_visible = ctx.satisfied("obs.scores")
        gated = ctx.get("retrieval.threshold") is not None

        # Without a similarity threshold every query comes back full, so
        # "did it retrieve something" answers nothing. What still separates
        # the two families is how *strongly* a query matches: a lexical index
        # scores an exact rare literal near the top, a dense encoder buries
        # it. So compare scores when they are visible, and fall back to the
        # retrieve/miss test only when a threshold makes it meaningful.
        baseline_top = None
        if scores_visible:
            probe = ctx.ask(f"What does the document say about {topic}?")
            baseline_top = max(probe.scores, default=None)

        lexical: bool | None = None
        if rare:
            probe = ctx.ask(rare)
            top = max(probe.scores, default=None)
            if scores_visible and baseline_top and top is not None:
                lexical = top >= baseline_top * 0.8
                rare_note = (f"rare literal scored {top:.3f} vs baseline "
                             f"{baseline_top:.3f}")
            elif gated:
                lexical = bool(probe.source_count)
                rare_note = (f"rare literal "
                             f"{'passed' if lexical else 'failed'} the threshold")
            else:
                rare_note = "rare literal inconclusive (no scores, no threshold)"
        else:
            rare_note = "no confirmed rare literal"

        typo_query, typo_word = _typo_variant(topic)
        dense: bool | None = None
        if typo_query:
            probe = ctx.ask(typo_query)
            top = max(probe.scores, default=None)
            if scores_visible and baseline_top and top is not None:
                dense = top >= baseline_top * 0.5
                typo_note = (f"misspelling scored {top:.3f} vs baseline "
                             f"{baseline_top:.3f}")
            elif gated:
                dense = bool(probe.source_count)
                typo_note = (f"misspelling "
                             f"{'passed' if dense else 'failed'} the threshold")
            else:
                typo_note = "misspelling inconclusive (no scores, no threshold)"
        else:
            typo_note = "no word long enough to misspell"

        if lexical is None and dense is None:
            ctx.skip_fact("retrieval.mode", status="not-applicable",
                          reason="neither discriminator could be sent",
                          module=self)
            return

        # Say which discriminator actually ran. Calling a system "dense"
        # when the lexical test never happened is the kind of unearned
        # certainty this tool exists to avoid.
        if lexical and dense:
            value, display = "hybrid", "hybrid (lexical + dense)"
        elif lexical and dense is False:
            value, display = "lexical", "lexical / sparse"
        elif dense and lexical is False:
            value, display = "dense", "dense"
        elif dense and lexical is None:
            value, display = "dense", "dense (lexical untested)"
        elif lexical and dense is None:
            value, display = "lexical", "lexical (dense untested)"
        else:
            value, display = "unclear", "unclear (both discriminators missed)"

        ctx.set_fact("retrieval.mode", "retrieval mode", value, display=display,
                     method="exact rare literal vs misspelled corpus term",
                     evidence=f"{rare_note}; {typo_note}", kind="derived")


def _typo_variant(topic: str | None) -> tuple[str | None, str | None]:
    """Swap two inner characters of the longest word in the topic."""
    if not topic:
        return None, None
    words = [w for w in re.split(r"\W+", topic) if len(w) >= 6]
    if not words:
        return None, None
    word = max(words, key=len)
    i = len(word) // 2
    typo = word[:i - 1] + word[i] + word[i - 1] + word[i + 1:]
    return f"What does the document say about {topic.replace(word, typo)}?", typo


@register
class Reranker(Module):
    name = "retrieval.reranker"
    section = "retrieval"
    level = 4
    cost = 2
    value = 4
    requires = ("obs.scores",)
    provides = ("retrieval.reranker",)
    description = "Look for evidence of a reranking stage"

    SCORE_NAMES = ("score", "similarity", "similarity_score", "relevance",
                   "relevance_score", "distance", "_distance", "rerank_score",
                   "reranking_score")

    @staticmethod
    def _same_signal(ctx: Context, names: set[str]) -> bool:
        """True when the score fields are one quantity written two ways.

        A vector store commonly returns both a distance and a similarity
        derived from it (score = 1 - distance). Two numeric fields then look
        like a retrieval score plus a rerank score, but nothing was reranked.
        A real reranking stage reorders the passages, so the two fields
        disagree about which passage is best; a transform never does.
        """
        ordered = sorted(names)
        for probe in ctx.probes:
            rows = [e.raw for e in probe.sources if isinstance(e.raw, dict)]
            series: list[list[float]] = []
            for key in ordered:
                values = []
                for row in rows:
                    try:
                        values.append(float(row[key]))
                    except (KeyError, TypeError, ValueError):
                        values = []
                        break
                if values:
                    series.append(values)
            if len(series) < 2 or len(series[0]) < 3:
                continue
            ranks = [sorted(range(len(s)), key=lambda i, s=s: s[i])
                     for s in series]
            if ranks[0] != ranks[1] and ranks[0] != list(reversed(ranks[1])):
                return False
            return True
        return False

    def run(self, ctx: Context) -> None:
        names: set[str] = set()
        monotonic = True
        checked = 0

        for probe in ctx.probes:
            for entry in probe.sources:
                if isinstance(entry.raw, dict):
                    for key in entry.raw:
                        if key.lower() in self.SCORE_NAMES:
                            names.add(key)
            scores = probe.scores
            if len(scores) >= 2:
                checked += 1
                descending = all(a >= b for a, b in zip(scores, scores[1:]))
                ascending = all(a <= b for a, b in zip(scores, scores[1:]))
                if not (descending or ascending):
                    monotonic = False

        if len(names) >= 2 and not self._same_signal(ctx, names):
            ctx.set_fact("retrieval.reranker", "reranker", True,
                         display="present",
                         method="two distinct score fields per passage",
                         evidence=", ".join(sorted(names)), kind="direct")
            return

        if len(names) >= 2:
            ctx.set_fact(
                "retrieval.reranker", "reranker", False, display="not detected",
                method="two score fields per passage, tested for independence",
                evidence=(f"{', '.join(sorted(names))} rank every passage "
                          "identically, so they are one measurement expressed "
                          "twice, not a retrieval score plus a rerank score"),
                kind="derived")
            return

        if checked and not monotonic:
            ctx.set_fact("retrieval.reranker", "reranker", True,
                         display="likely",
                         method="returned order does not follow the score field",
                         evidence=f"non-monotonic ordering in {checked} responses",
                         kind="heuristic")
            return

        ctx.set_fact("retrieval.reranker", "reranker", False,
                     display="not detected",
                     method="single score field, ordering follows it",
                     evidence=f"{checked} multi-passage responses examined",
                     kind="heuristic")
