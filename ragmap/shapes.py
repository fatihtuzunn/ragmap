"""Request/response shape detection.

In an engagement you are handed a URL, maybe a token, and nothing else. The
field that carries the question and the path that holds the answer are
unknown, and they differ per product. This module finds them by trying
candidate request bodies until one comes back with a usable answer.

A 2xx alone is not acceptance: plenty of APIs answer 200 to a body they did
not understand and put an error string in the response. A shape counts as
working only when an answer can actually be extracted from the reply.
"""

from __future__ import annotations

from dataclasses import dataclass, field


from .transport import RATE_LIMIT_RE, Probe, Transport


# Specific shapes first. A generic {"query": ...} may well return 200 against
# a product with its own schema while silently filling the wrong field.
REQUEST_SHAPES: list[tuple[str, dict]] = [
    ("openai-compatible", {
        "model": "{{MODEL}}",
        "messages": [{"role": "user", "content": "{{QUERY}}"}],
        "stream": False,
    }),
    ("anythingllm", {"message": "{{QUERY}}", "mode": "query"}),
    ("dify", {
        "inputs": {},
        "query": "{{QUERY}}",
        "response_mode": "blocking",
        "user": "ragmap",
    }),
    ("flowise", {"question": "{{QUERY}}"}),
    ("generic-query", {"query": "{{QUERY}}"}),
    ("generic-question", {"question": "{{QUERY}}"}),
    ("generic-input", {"input": "{{QUERY}}"}),
    ("generic-prompt", {"prompt": "{{QUERY}}"}),
    ("generic-message", {"message": "{{QUERY}}"}),
    ("generic-text", {"text": "{{QUERY}}"}),
]

PRODUCT_HINTS = {
    "anythingllm": "AnythingLLM",
    "open-webui": "Open WebUI",
    "openwebui": "Open WebUI",
    "librechat": "LibreChat",
    "dify": "Dify",
    "ragflow": "RAGFlow",
    "flowise": "Flowise",
    "langserve": "LangServe",
    "danswer": "Onyx/Danswer",
    "onyx": "Onyx/Danswer",
    "verba": "Verba (Weaviate)",
    "khoj": "Khoj",
    "llamaindex": "LlamaIndex",
    "llama_index": "LlamaIndex",
    "langchain": "LangChain",
    "haystack": "Haystack",
    "chromadb": "ChromaDB",
    "qdrant": "Qdrant",
    "weaviate": "Weaviate",
    "lancedb": "LanceDB",
    "pgvector": "pgvector",
    "milvus": "Milvus",
    "pinecone": "Pinecone",
    "faiss": "FAISS",
}

DETECT_QUERY = "What topics can you help me with?"


@dataclass
class Shape:
    name: str | None = None
    body_template: dict | None = None
    answer_path: tuple | None = None
    requires_auth: bool = False
    status: int | None = None
    server_header: str | None = None
    model_name: str | None = None
    product_hints: list[str] = field(default_factory=list)
    probe: Probe | None = None
    blocked: str | None = None     # target failing, not a shape mismatch
    attempts: list[dict] = field(default_factory=list)

    @property
    def detected(self) -> bool:
        return self.body_template is not None and self.answer_path is not None

    @property
    def answer_path_str(self) -> str:
        if not self.answer_path:
            return ""
        out = ""
        for step in self.answer_path:
            if isinstance(step, int):
                out += f"[{step}]"
            else:
                out += ("." if out else "") + str(step)
        return out


def product_hints(text: str, headers: dict) -> list[str]:
    haystack = (text or "").lower()
    for key, value in (headers or {}).items():
        haystack += f" {key} {value} ".lower()
    return sorted({label for needle, label in PRODUCT_HINTS.items()
                   if needle in haystack})


def detect(transport: Transport, forced: str | None = None,
           query_field: str | None = None) -> Shape:
    """Try candidate shapes until one yields an extractable answer."""
    shape = Shape()

    candidates = list(REQUEST_SHAPES)
    if query_field:
        candidates.insert(0, (f"custom-{query_field}", {query_field: "{{QUERY}}"}))
    if forced:
        candidates = [c for c in candidates if c[0] == forced] or candidates

    for name, template in candidates:
        if transport.remaining <= 0:
            break
        probe = transport.send(DETECT_QUERY, body_template=template)
        attempt = {"shape": name, "status": probe.status,
                   "answer_found": bool(probe.answer)}
        if probe.error:
            attempt["error"] = probe.error
        shape.attempts.append(attempt)
        shape.status = probe.status

        # An upstream failure says nothing about whether this shape is the
        # right one, so there is no point trying the next candidate.
        if probe.error and (probe.status is None or probe.status >= 500
                            or RATE_LIMIT_RE.search(probe.error)):
            shape.blocked = probe.error
            break

        if probe.status in (401, 403):
            shape.requires_auth = True
            attempt["note"] = "authentication required"
            break
        if not probe.answer:
            continue

        shape.name = name
        shape.body_template = template
        shape.answer_path = probe.answer_path
        shape.probe = probe
        shape.server_header = probe.headers.get("Server")
        if isinstance(probe.body, dict):
            model = probe.body.get("model")
            shape.model_name = model if isinstance(model, str) else None
        shape.product_hints = product_hints(probe.raw_text, probe.headers)
        break

    return shape


def check_streaming(transport: Transport, shape: Shape) -> tuple[bool, str]:
    """Ask for a streamed reply and see whether the target obliges."""
    if not shape.detected:
        return False, "shape unknown"
    template = dict(shape.body_template)
    if "stream" in template or shape.name == "openai-compatible":
        template["stream"] = True
    elif shape.name == "dify":
        template["response_mode"] = "streaming"
    else:
        template["stream"] = True

    probe = transport.send(DETECT_QUERY, body_template=template)
    content_type = (probe.headers.get("Content-Type") or "").lower()
    if "event-stream" in content_type:
        return True, "Content-Type: text/event-stream"
    if probe.raw_text.lstrip().startswith("data:"):
        return True, "response body uses SSE framing"
    return False, f"Content-Type: {content_type or 'unknown'}"
