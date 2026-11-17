"""Corpus-free probe derivation.

Most retrieval measurements need to know something about the corpus: a topic
that is definitely in it, a topic that is definitely not, and a rare literal
string that appears exactly once. In a lab you know these because you loaded
the documents yourself. In an engagement the corpus belongs to the client,
you have never seen it, and you cannot upload your own - that is a write,
and it is out of scope.

So the values are derived from the target instead:

    topic          a subject confirmed to be in the corpus
    second_topic   another subject, preferably from a different document
    absent_topic   a subject measured to be missing from the corpus
    rare_token     an identifier-looking literal confirmed to retrieve

"Confirmed" and "measured" are load-bearing words. Every candidate is put to
the target before it is accepted. Scanners that ship a fixed query list pick
both the present and the absent topic wrong whenever the target's domain
differs from the author's assumptions, and every measurement downstream
inherits that error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .transport import Probe


META_QUERIES = [
    "What documents do you have access to? List their titles.",
    "What topics can you answer questions about? List them briefly.",
    "Summarise the main subjects covered in your knowledge base.",
    "List any reference codes, document numbers or policy identifiers that "
    "appear in your documents.",
]

# Candidates for "not in the corpus". None is assumed; the one that scores
# weakest against this target is chosen. They are drawn from unrelated
# domains so that a hit on all of them is itself informative.
ABSENT_CANDIDATES = [
    "deep sea mining permits",
    "medieval falconry training methods",
    "competitive origami scoring rules",
    "Antarctic penguin migration tagging",
    "seventeenth century harpsichord tuning",
]

REFUSAL_PATTERNS = [
    r"\bi (?:do not|don't) have\b",
    r"\bno (?:relevant )?information\b",
    r"\bnot (?:mentioned|covered|contained|found|available)\b",
    r"\b(?:could not|couldn't|cannot|can't) find\b",
    r"\bdoes not (?:contain|mention|include)\b",
    r"\bno documents?\b",
    r"\bunable to (?:find|locate|answer)\b",
    r"\bthere (?:is|are) (?:no|nothing)\b",
]

IDENTIFIER_RE = re.compile(r"\b[A-Z]{2,6}[-_][A-Z0-9]{2,10}(?:[-_][A-Z0-9]{2,10})*\b")
FILENAME_RE = re.compile(
    r"\b[\w\-]{3,60}\.(?:pdf|docx?|md|txt|pptx?|csv|html?|json)\b", re.IGNORECASE)
QUOTED_RE = re.compile(
    "[\"\u201c\u201d]([^\"\u201c\u201d]{6,70})[\"\u201c\u201d]")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.{4,80}?)\s*$", re.MULTILINE)
TITLECASE_RE = re.compile(
    r"\b([A-Z][a-z]{2,}(?:\s+(?:and|of|for|the|on|in|[A-Z][a-z]{2,})){1,6})\b")

GENERIC_WORDS = {
    "a", "an", "the", "and", "or", "for", "of", "on", "in", "to", "at", "by",
    "from", "with", "as", "is", "are", "was", "were", "be", "it", "its",
    "you", "your", "this", "that", "these", "those", "here", "there",
    "document", "documents", "documentation", "information", "knowledge",
    "base", "topics", "topic", "title", "titles", "section", "sections",
    "please", "note", "however", "based", "according", "sorry", "assistant",
    "help", "available", "provide", "provided", "answer", "list", "lists",
    "retrieved", "material", "context", "following", "below", "above",
    "include", "includes", "including", "such", "other", "more", "details",
    "detail", "summary", "overview", "general", "various", "related",
}

# A phrase has to carry real subject matter. Two distinctive words, or one
# long one, keeps fragments like "Based on the" or "in the following" out of
# the candidate pool. Junk here is expensive: every later measurement is
# taken against whatever topic is chosen.
MIN_DISTINCTIVE_WORDS = 2
MIN_SINGLE_WORD_LEN = 8


def refused(text: str) -> bool:
    low = (text or "").lower()
    return any(re.search(p, low) for p in REFUSAL_PATTERNS)


def retrieval_signal(probe: Probe) -> float:
    """Crude "is this subject in the corpus" score.

    Visible source count is the strongest evidence, absence of a refusal the
    next, answer length the weakest. None of them is conclusive alone, which
    is exactly why they are combined.
    """
    score = 0.0
    if probe.source_count:
        score += min(probe.source_count, 5) * 2.0
    if probe.answer and not refused(probe.answer):
        score += 2.0
        score += min(len(probe.answer) / 400.0, 2.0)
    if refused(probe.answer):
        score -= 3.0
    if probe.scores:
        score += min(max(probe.scores), 1.0) * 2.0
    return score


@dataclass
class Discovery:
    topic: str | None = None
    second_topic: str | None = None
    absent_topic: str | None = None
    rare_token: str | None = None
    evidence: dict = field(default_factory=dict)
    topics_seen: list[str] = field(default_factory=list)
    identifiers: list[str] = field(default_factory=list)
    filenames: list[str] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    requests: int = 0


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" .,:;---\"'()[]")


def _distinctive(phrase: str) -> list[str]:
    return [w for w in re.split(r"\W+", phrase.lower())
            if w and w not in GENERIC_WORDS and len(w) > 2]


def _usable(phrase: str) -> bool:
    if not (6 <= len(phrase) <= 80):
        return False
    words = [w for w in re.split(r"\W+", phrase.lower()) if w]
    if not words:
        return False
    # Leading or trailing filler ("Based on the ...") is a fragment, not a
    # subject, even when a content word appears later.
    if words[0] in GENERIC_WORDS and words[-1] in GENERIC_WORDS:
        return False
    distinctive = _distinctive(phrase)
    if len(distinctive) >= MIN_DISTINCTIVE_WORDS:
        return True
    return bool(distinctive) and len(distinctive[0]) >= MIN_SINGLE_WORD_LEN


def _specificity(phrase: str) -> int:
    """Tie-breaker: richer phrases make better probes than bare ones."""
    distinctive = _distinctive(phrase)
    capitals = sum(1 for w in phrase.split() if w[:1].isupper())
    return len(distinctive) * 2 + capitals


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def extract_candidates(texts: list[str]) -> dict[str, list[str]]:
    topics: list[str] = []
    identifiers: list[str] = []
    filenames: list[str] = []
    for text in texts:
        if not text:
            continue
        identifiers.extend(IDENTIFIER_RE.findall(text))
        filenames.extend(FILENAME_RE.findall(text))
        topics.extend(_clean(m) for m in LIST_ITEM_RE.findall(text))
        topics.extend(_clean(m) for m in QUOTED_RE.findall(text))
        topics.extend(_clean(m) for m in TITLECASE_RE.findall(text))
    return {
        "topics": _dedupe([t for t in topics if _usable(t)]),
        "identifiers": _dedupe(identifiers),
        "filenames": _dedupe(filenames),
    }


def run(ctx, budget: int = 40, verbose: bool = False) -> Discovery:
    """Derive probe values from the target. ``ctx`` is a ragmap Context."""
    result = Discovery()
    start_requests = ctx.transport.used
    cfg = ctx.config

    def spent() -> int:
        return ctx.transport.used - start_requests

    def left() -> int:
        return min(budget - spent(), ctx.transport.remaining)

    # --- operator-supplied values win outright ------------------------
    result.topic = cfg.topic
    result.second_topic = cfg.second_topic
    result.absent_topic = cfg.absent_topic
    result.rare_token = cfg.rare_token

    # The reserves below used to be fixed numbers - stop confirming topics
    # with ten requests left, stop looking for an absent topic with five.
    # They were sized for a forty-request discovery and starved the only
    # phase that matters when the budget is small: without a confirmed
    # topic, every retrieval detector downstream reports not-applicable.
    # Scaled to the budget, a ten-request discovery still finds a topic.
    reserve_rare = 2 if budget >= 12 else 0
    reserve_absent = 3 if budget >= 14 else (2 if budget >= 9 else 1)

    # --- 1. meta queries ----------------------------------------------
    texts: list[str] = []
    queries = cfg.seed_queries or META_QUERIES
    for query in queries[:max(2, budget // 4)]:
        if left() <= 0:
            break
        probe = ctx.ask(query)
        if probe.answer:
            texts.append(probe.answer)

    # Identifiers the system volunteered in structured source fields are the
    # most reliable candidates: it labelled them as sources itself.
    source_labels: list[str] = []
    for chunk in ctx.chunks.items:
        for value in (chunk.title, chunk.doc_id):
            if value:
                source_labels.append(str(value))
    result.documents = _dedupe(source_labels)[:50]

    # Passages already returned are a far richer source of identifier-shaped
    # literals than the model's prose: a document number buried in clause 6
    # reaches us intact in a chunk, while the model usually paraphrases it
    # away when asked to "list reference codes".
    passage_text = [c.text for c in ctx.chunks.items if c.text][:40]

    # On an opaque target the meta answers are all we get, and they are often
    # thin. Every answer already collected by earlier modules is free
    # material, so mine those too rather than spending requests to re-ask.
    prior_answers = [p.answer for p in ctx.probes if p.answer][:30]

    candidates = extract_candidates(texts + source_labels + passage_text
                                    + prior_answers)
    pool = _dedupe(extract_candidates(source_labels)["topics"]
                   + extract_candidates(texts)["topics"]
                   + extract_candidates(prior_answers)["topics"])
    result.topics_seen = pool[:25]
    result.identifiers = candidates["identifiers"][:15]
    result.filenames = candidates["filenames"][:15]

    if not pool and not result.topic:
        result.notes.append(
            "No topic candidates could be extracted from meta queries. The "
            "target refuses them or answers too tersely. Supply --topic to "
            "measure retrieval parameters.")

    # --- 2. confirm topics --------------------------------------------
    scored: list[tuple[float, str, Probe]] = []
    if not result.topic:
        affordable = left() - reserve_absent - reserve_rare
        shortlist = pool[:12]
        if affordable < len(shortlist):
            # Too few requests to try them all, so try the most specific
            # phrases: a generic one retrieves something on any corpus and
            # tells us least about this one.
            shortlist = sorted(pool, key=lambda t: -_specificity(t))[:12]
        for topic in shortlist:
            if left() <= reserve_absent + reserve_rare:
                result.notes.append("Topic confirmation truncated by budget.")
                break
            probe = ctx.ask(f"What does the document say about {topic}?")
            scored.append((retrieval_signal(probe), topic, probe))

        # Where no similarity threshold exists every candidate retrieves the
        # same number of passages, so the signal barely separates them. The
        # more specific phrase is then the better probe.
        confirmed = sorted([s for s in scored if s[0] > 0],
                           key=lambda t: (-t[0], -_specificity(t[1])))
        if confirmed:
            result.topic = confirmed[0][1]
            result.evidence["topic"] = {
                "signal": round(confirmed[0][0], 2),
                "source_count": confirmed[0][2].source_count,
            }
            first_words = set(re.split(r"\W+", confirmed[0][1].lower()))
            for signal, topic, probe in confirmed[1:]:
                if len(set(re.split(r"\W+", topic.lower())) & first_words) <= 1:
                    result.second_topic = topic
                    result.evidence["second_topic"] = {
                        "signal": round(signal, 2),
                        "source_count": probe.source_count,
                    }
                    break
            if not result.second_topic and len(confirmed) > 1:
                result.second_topic = confirmed[1][1]
        else:
            result.notes.append(
                "No topic candidate produced a positive retrieval signal. The "
                "target may not be a RAG system, or retrieval is closed to "
                "these queries.")

    # --- 3. measure an absent topic -----------------------------------
    if not result.absent_topic:
        absent: list[tuple[float, str, Probe]] = []
        for candidate in ABSENT_CANDIDATES:
            if left() <= reserve_rare:
                break
            probe = ctx.ask(f"What does the document say about {candidate}?")
            absent.append((retrieval_signal(probe), candidate, probe))
        if absent:
            absent.sort(key=lambda t: t[0])
            signal, chosen, probe = absent[0]
            result.absent_topic = chosen
            result.evidence["absent_topic"] = {
                "signal": round(signal, 2),
                "refused": refused(probe.answer),
                "source_count": probe.source_count,
                "candidates": {c: round(s, 2) for s, c, _ in absent},
            }
            if signal > 0:
                result.notes.append(
                    f"The weakest off-domain subject ({chosen}) still scored "
                    f"{signal:.1f}. Either no similarity threshold is applied, "
                    f"or the subject really is covered. Read the threshold "
                    f"result with that in mind.")

    # --- 4. rare token -------------------------------------------------
    if not result.rare_token:
        for token in (result.identifiers[:5] or result.filenames[:3]):
            if left() <= 0:
                break
            probe = ctx.ask(token)
            if retrieval_signal(probe) > 0:
                result.rare_token = token
                result.evidence["rare_token"] = {
                    "signal": round(retrieval_signal(probe), 2),
                    "source_count": probe.source_count,
                }
                break
        if not result.rare_token:
            result.notes.append(
                "No rare identifier could be confirmed. Lexical-vs-dense "
                "retrieval cannot be separated on this target; pass "
                "--rare-token to measure it.")

    result.requests = spent()
    return result
