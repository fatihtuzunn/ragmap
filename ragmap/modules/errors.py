"""Error handling: what the target says when the request is wrong."""

from __future__ import annotations

import json
import re

from .. import findings
from ..context import Context
from ..registry import Module, register

FRAMEWORK_MARKERS = {
    "traceback (most recent call last)": "Python traceback",
    "traceback": "stack trace",
    "langchain": "LangChain",
    "llama_index": "LlamaIndex",
    "llamaindex": "LlamaIndex",
    "haystack": "Haystack",
    "pydantic": "pydantic",
    "fastapi": "FastAPI",
    "starlette": "Starlette",
    "werkzeug": "Werkzeug/Flask",
    "django": "Django",
    "express": "Express",
    "chromadb": "ChromaDB",
    "qdrant": "Qdrant",
    "weaviate": "Weaviate",
    "lancedb": "LanceDB",
    "pgvector": "pgvector",
    "psycopg": "psycopg/PostgreSQL",
    "sqlalchemy": "SQLAlchemy",
    "milvus": "Milvus",
    "openai.error": "OpenAI SDK",
    "site-packages": "server filesystem path",
    "/usr/local/lib": "server filesystem path",
}


@register
class ErrorVerbosity(Module):
    name = "errors.verbosity"
    section = "interface"
    level = 2
    cost = 3
    value = 2
    requires = ("iface.shape",)
    provides = ("errors.verbosity",)
    description = "Probe error responses for internal detail"

    def run(self, ctx: Context) -> None:
        observed: list[tuple[str, int | None, str]] = []

        # 1. Empty query - usually hits input validation.
        probe = ctx.ask("   ")
        observed.append(("empty query", probe.status, probe.raw_text))

        # 2. Wrong types in the expected field.
        if ctx.transport.remaining > 1 and ctx.shape and ctx.shape.body_template:
            broken = _break_template(ctx.shape.body_template)
            probe = ctx.transport.send("", body_template=broken)
            ctx.probes.append(probe)
            observed.append(("type-confused body", probe.status, probe.raw_text))

        # 3. Very long input.
        if ctx.transport.remaining > 1:
            probe = ctx.ask("A" * 20000)
            observed.append(("oversized query", probe.status, probe.raw_text))

        hits: list[str] = []
        example = ""
        for label, status, text in observed:
            # Only error responses count. A successful answer that happens to
            # contain the word "expressed" is not a framework disclosure, and
            # substring matching on corpus prose produces exactly that.
            if not _looks_like_error(status, text):
                continue
            low = (text or "").lower()
            for marker, name in FRAMEWORK_MARKERS.items():
                match = re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", low)
                if match and name not in hits:
                    hits.append(name)
                    if not example:
                        index = match.start()
                        example = " ".join(
                            (text[max(0, index - 40):index + 120]).split())

        statuses = ", ".join(f"{label}:{status}" for label, status, _ in observed)

        if not hits:
            ctx.set_fact("errors.verbosity", "error detail", False,
                         display="clean",
                         method="empty, type-confused and oversized inputs sent",
                         evidence=statuses, kind="direct")
            return

        ctx.set_fact("errors.verbosity", "error detail", hits,
                     display=", ".join(hits[:3]),
                     method="empty, type-confused and oversized inputs sent",
                     evidence=statuses, kind="direct")
        ctx.add_finding(findings.make(
            "RAGMAP-004",
            "error responses name internal components",
            evidence=example or ", ".join(hits),
            facts=("errors.verbosity",)))


def _looks_like_error(status: int | None, text: str) -> bool:
    """An error response, or a 200 carrying an error payload."""
    if status is not None and status >= 400:
        return True
    try:
        body = json.loads(text or "")
    except (ValueError, TypeError):
        return False
    return isinstance(body, dict) and bool(body.get("error") or body.get("detail"))


def _break_template(template: dict) -> dict:
    """Replace the query placeholder with a value of the wrong type."""
    def walk(node):
        if isinstance(node, str):
            return {"unexpected": "object"} if "{{QUERY}}" in node else node
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node
    return walk(template)
