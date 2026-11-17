"""Routing and caching behaviour."""

from __future__ import annotations

from statistics import median

from .. import findings
from ..context import Context
from ..registry import Module, register

GENERAL = [
    "What is the capital of France?",
    "What is 23 plus 19?",
    "Name three primary colours.",
]


@register
class Router(Module):
    name = "routing.router"
    section = "retrieval"
    level = 2
    cost = 6
    value = 2
    requires = ("corpus.topic",)
    provides = ("routing.router",)
    description = "Detect a gate that decides whether to retrieve"

    def run(self, ctx: Context) -> None:
        topic = ctx.get("corpus.topic")
        sources_visible = ctx.satisfied("obs.source_field")

        general_counts: list[int] = []
        general_times: list[float] = []
        general_lengths: list[int] = []
        for query in GENERAL:
            if ctx.transport.remaining <= 3:
                break
            # Timing only compares if both sides are measured now, under
            # the same pacing; a latency carried over from an earlier
            # module is not a sample of this experiment.
            probe = ctx.ask(query, fresh=True)
            if probe.ok:
                general_counts.append(probe.source_count or 0)
                general_times.append(probe.latency_ms)
                general_lengths.append(len(probe.answer or ''))

        topic_counts: list[int] = []
        topic_times: list[float] = []
        topic_lengths: list[int] = []
        for phrasing in (f"What does the document say about {topic}?",
                         f"Explain {topic}.",
                         f"Details on {topic}?"):
            if ctx.transport.remaining <= 1:
                break
            probe = ctx.ask(phrasing, fresh=True)
            if probe.ok:
                topic_counts.append(probe.source_count or 0)
                topic_times.append(probe.latency_ms)
                topic_lengths.append(len(probe.answer or ''))

        if not general_times or not topic_times:
            ctx.skip_fact("routing.router", status="not-applicable",
                          reason="comparison probes could not be sent",
                          module=self)
            return

        delta = median(topic_times) - median(general_times)

        # A similarity threshold already drops everything on an off-topic
        # question, so an empty result is no longer evidence of a routing
        # gate -- reading it as one reports two mechanisms where the target
        # has a single threshold. The latency gap survives: a router skips
        # retrieval and answers sooner, a threshold searches and then throws
        # the result away.
        threshold = ctx.get("retrieval.threshold")
        if sources_visible and threshold:
            # Generation time scales with the length of the answer. A
            # threshold that cuts every passage leaves the model with
            # nothing to say, so it returns a short refusal quickly - and
            # that gap is indistinguishable from a router skipping
            # retrieval. Only comparable answer lengths make the timing
            # usable.
            long_side = max(median(general_lengths or [0]),
                            median(topic_lengths or [0]))
            short_side = min(median(general_lengths or [0]),
                             median(topic_lengths or [0]))
            if long_side > 2 * max(short_side, 1):
                ctx.skip_fact(
                    "routing.router", status="not-applicable",
                    reason=(f"a threshold is applied, which voids the "
                            f"zero-source signal, and the answers differ too "
                            f"much in length ({short_side:.0f} vs "
                            f"{long_side:.0f} chars) for the {delta:+.0f}ms "
                            f"gap to mean anything"),
                    module=self)
                return
            present = delta > 80
            ctx.set_fact(
                "routing.router", "router", present,
                display="likely" if present else "not detected",
                method=("latency difference; the zero-source signal is void "
                        "because a threshold is applied"),
                evidence=(f"{delta:+.0f}ms between on-topic and general "
                          f"queries (floor 80ms); general {general_counts} "
                          f"vs on-topic {topic_counts}. A router that costs "
                          f"no measurable time is not separable from the "
                          f"threshold by this method."),
                kind="heuristic")
            return

        if sources_visible:
            skipped = all(c == 0 for c in general_counts)
            retrieved = any(c > 0 for c in topic_counts)
            present = skipped and retrieved
            ctx.set_fact(
                "routing.router", "router", present,
                display="present" if present else "none",
                method="source count on general-knowledge vs on-topic queries",
                evidence=(f"general {general_counts} vs on-topic {topic_counts}, "
                          f"{delta:+.0f}ms"),
                kind="direct")
            if not present and retrieved:
                ctx.add_finding(findings.make(
                    "RAGMAP-008",
                    "general-knowledge queries still hit the vector store",
                    evidence=f"general-knowledge source counts {general_counts}",
                    facts=("routing.router",)))
            return

        # No visible sources: timing is all we have, so say so.
        present = delta > 80
        ctx.set_fact(
            "routing.router", "router", present,
            display="likely" if present else "not detected",
            method="latency difference only (sources not exposed)",
            evidence=f"{delta:+.0f}ms between on-topic and general queries",
            kind="heuristic")


@register
class Cache(Module):
    name = "routing.cache"
    section = "retrieval"
    level = 3
    cost = 4
    value = 2
    requires = ("corpus.topic",)
    provides = ("routing.cache",)
    description = "Detect a semantic or response cache"

    def run(self, ctx: Context) -> None:
        topic = ctx.get("corpus.topic")
        query = f"What does the document say about {topic}?"

        times: list[float] = []
        headers_seen: list[str] = []
        for _ in range(4):
            if ctx.transport.remaining <= 1:
                break
            # A cache shows itself in the second reply, so each repeat has
            # to be a real request.
            probe = ctx.ask(query, fresh=True)
            if not probe.ok:
                continue
            times.append(probe.latency_ms)
            for key, value in probe.headers.items():
                if "cache" in key.lower():
                    marker = f"{key}: {value}"
                    if marker not in headers_seen:
                        headers_seen.append(marker)

        if len(times) < 2:
            ctx.skip_fact("routing.cache", status="not-applicable",
                          reason="not enough successful repeats", module=self)
            return

        first, rest = times[0], times[1:]
        ratio = first / (median(rest) or 1)
        cached = ratio > 2.0 or bool(headers_seen)

        evidence = f"first {first:.0f}ms vs later median {median(rest):.0f}ms"
        if headers_seen:
            evidence += "; " + ", ".join(headers_seen[:2])

        ctx.set_fact("routing.cache", "cache", cached,
                     display="present" if cached else "not detected",
                     method="identical query repeated, latency and headers compared",
                     evidence=evidence,
                     kind="direct" if headers_seen else "heuristic")

        if cached:
            ctx.add_finding(findings.make(
                "RAGMAP-007",
                f"repeat queries answer {ratio:.1f}x faster",
                evidence=evidence, facts=("routing.cache",)))
