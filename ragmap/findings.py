"""Finding catalogue.

A finding is a security-relevant conclusion, not a measurement. Severity
here describes exposure of the retrieval layer, not business impact - the
same disclosure matters very differently for a public FAQ bot and for an
HR knowledge base, and only the engagement can settle that.
"""

from __future__ import annotations

from .model import Finding

CATALOG: dict[str, tuple[str, str, str]] = {
    "RAGMAP-001": (
        "Verbatim chunk extraction", "high",
        "Source passages can be pulled out through the answer text itself, so "
        "withholding citation metadata does not keep the corpus private."),
    "RAGMAP-002": (
        "No similarity threshold", "medium",
        "Off-topic queries still retrieve passages, so any question returns "
        "corpus content to the caller."),
    "RAGMAP-003": (
        "Token counter exposed", "low",
        "Prompt token counts reveal the size of the assembled context, which "
        "leaks chunk size times top-k even when nothing else is visible."),
    "RAGMAP-004": (
        "Stack trace or framework disclosure", "low",
        "Malformed input returns internal error detail naming the framework "
        "or its components."),
    "RAGMAP-005": (
        "Source identifier disclosure", "low",
        "Responses carry document names, paths or page numbers, mapping the "
        "corpus structure for an attacker."),
    "RAGMAP-006": (
        "Chunk text exposed in API response", "medium",
        "Retrieved passages are returned as structured fields, so corpus "
        "content is readable without any extraction technique."),
    "RAGMAP-007": (
        "Semantic cache timing side channel", "low",
        "Repeated queries answer measurably faster, which discloses whether a "
        "question has been asked before."),
    "RAGMAP-008": (
        "Retrieval runs on every query", "info",
        "No routing layer gates retrieval, so every request reaches the vector "
        "store regardless of relevance."),
    "RAGMAP-009": (
        "Similarity scores exposed", "low",
        "Relevance scores are returned, giving direct feedback for tuning "
        "retrieval-manipulation attempts."),
    "RAGMAP-010": (
        "Unauthenticated chat endpoint", "high",
        "The endpoint answered without credentials."),
    "RAGMAP-011": (
        "Chunk identifier collision across documents", "medium",
        "One identifier is used by passages from different documents, so the "
        "store cannot tell them apart: a hit on one can return the other, and "
        "any per-document access rule keyed on that id is unenforceable."),
    "RAGMAP-012": (
        "Passages indexed under more than one document", "low",
        "The same text is stored several times, so one topic can fill the "
        "whole top-k with copies of itself and crowd out the rest of the "
        "corpus."),
    "RAGMAP-014": (
        "Vector store reachable without authentication", "high",
        "The vector database behind the chat endpoint answers anonymous "
        "requests on its own port. The corpus can be listed, read and "
        "written directly, which makes every restriction the chat API "
        "enforces - hidden passages, similarity thresholds, withheld "
        "scores - irrelevant to anyone who goes around it."),
    "RAGMAP-013": (
        "Encoded data in the retrieval index", "medium",
        "Passages that are base64 or similar encoded payloads rather than "
        "prose were retrieved, which means file content reached the index "
        "without being extracted and may carry material nobody reviewed."),
}


def make(finding_id: str, summary: str, *, evidence: str = "",
         facts: tuple[str, ...] = ()) -> Finding:
    title, severity, detail = CATALOG[finding_id]
    return Finding(id=finding_id, title=title, severity=severity,
                   summary=summary, detail=detail, evidence=evidence,
                   facts=list(facts))
