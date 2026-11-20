"""Counting passages in tokens as well as characters.

A chunker is almost never configured in characters. `chunk_size=512` in a
LangChain, LlamaIndex or Haystack pipeline means 512 *tokens*, and the
embedding model behind it has a token window - 512 for the bge and e5
families, 8192 for the OpenAI and nomic ones - that silently truncates
anything longer. Measuring only in characters means reporting a number in
units the target does not use, and missing the one question that matters
about an oversized chunk: was the tail of it ever embedded at all?

`tiktoken` is an optional extra rather than a dependency. ragmap ships with
one dependency on purpose: it gets run from jump boxes and client laptops
where every extra package is something to justify. Without it, counts fall
back to the same four-characters-to-a-token estimate the token budget
already uses, and every figure says which it is - the same rule the scan
applies to its own token accounting.

    pip install ragmap[tokens]
"""

from __future__ import annotations

import functools

# tiktoken's BPE differs from a sentence-piece tokeniser, so a count taken
# here is right for OpenAI-family encoders and close for most others. It is
# a far better unit than characters either way.
DEFAULT_ENCODING = "o200k_base"

# Token windows of embedding models an operator is likely to meet. A chunk
# longer than its encoder's window is not a tuning preference, it is text
# that was dropped before it was ever indexed.
EMBEDDING_WINDOWS: dict[str, int] = {
    "text-embedding-3-small": 8192,
    "text-embedding-3-large": 8192,
    "text-embedding-ada-002": 8191,
    "bge-small-en-v1.5": 512,
    "bge-base-en-v1.5": 512,
    "bge-large-en-v1.5": 512,
    "bge-m3": 8192,
    "e5-small-v2": 512,
    "e5-base-v2": 512,
    "e5-large-v2": 512,
    "all-minilm-l6-v2": 256,
    "all-mpnet-base-v2": 384,
    "nomic-embed-text-v1": 8192,
    "nomic-embed-text-v1.5": 8192,
    "jina-embeddings-v2-base-en": 8192,
    "voyage-3": 32000,
    "cohere-embed-english-v3.0": 512,
    "cohere-embed-multilingual-v3.0": 512,
}


@functools.lru_cache(maxsize=1)
def _encoder():
    try:
        import tiktoken                                   # noqa: PLC0415
    except ImportError:
        return None
    try:
        return tiktoken.get_encoding(DEFAULT_ENCODING)
    except Exception:                                     # noqa: BLE001
        return None


def available() -> bool:
    """True when counts are real rather than estimated."""
    return _encoder() is not None


def encoding_name() -> str:
    return DEFAULT_ENCODING if available() else "4 chars/token estimate"


def count(text: str) -> int:
    if not text:
        return 0
    encoder = _encoder()
    if encoder is None:
        return max(1, len(text) // 4)
    return len(encoder.encode(text))


def window_for(model: str | None) -> int | None:
    """The token window of a named embedding model, if we know it."""
    if not model:
        return None
    return EMBEDDING_WINDOWS.get(model.strip().lower())
