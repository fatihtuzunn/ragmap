"""Explicit response paths, for when structural detection is not enough.

ragmap finds the answer and the retrieved passages by the *shape* of the
response, which is what lets it read a product it has never seen. That is
the right default and it is usually right. But "usually" is not a word an
operator can act on at two in the morning against the one endpoint that
matters, and a scanner with no manual override forces them to stop and
patch the source.

So every field the structural search looks for can be named outright:

    --source-path "results[].doc" --text-path content --score-path relevance

The syntax is a dot path with ``[]`` marking an array to walk into:

    answer                      body["answer"]
    data.response.text          body["data"]["response"]["text"]
    results[].doc               [item["doc"] for item in body["results"]]
    choices[].message.content   the same, two levels down

An override is the operator stating a fact about the target. When it
resolves to nothing the scan says so rather than quietly falling back to
the structural search: a path that was supposed to hold the passages and
does not is itself worth knowing, and silently guessing again would hide
the operator's typo behind a plausible-looking report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def resolve(data: Any, path: str) -> Any:
    """Resolve a dot path with ``[]`` array iteration. None if absent."""
    if not path:
        return data
    if data is None:
        return None

    first, _, rest = path.partition(".")

    if first.endswith("[]"):
        key = first[:-2]
        value = data if not key else (
            data.get(key) if isinstance(data, dict) else None)
        if not isinstance(value, list):
            return None
        if not rest:
            return value
        resolved = [resolve(item, rest) for item in value]
        return [item for item in resolved if item is not None]

    if isinstance(data, dict):
        return resolve(data.get(first), rest)
    return None


@dataclass
class PathSpec:
    """Operator-supplied locations inside the response body.

    Every field is optional. Naming only ``source_path`` is normal: the
    item fields below it fall back to the same key names the structural
    search already knows, which covers most custom wrappers.
    """
    source_path: str = ""
    answer_path: str = ""
    text_path: str = ""
    title_path: str = ""
    chunk_id_path: str = ""
    doc_id_path: str = ""
    score_path: str = ""
    page_path: str = ""

    @property
    def active(self) -> bool:
        return bool(self.source_path or self.answer_path)

    def describe(self) -> str:
        named = [f"{name.replace('_path', '')}={value}"
                 for name, value in vars(self).items() if value]
        return ", ".join(named)


def split_spec(raw: str) -> tuple[str, str]:
    """Split ``"results[].doc"`` into the array path and the item path."""
    if "[]" not in raw:
        return raw, ""
    head, _, tail = raw.partition("[]")
    return head + "[]", tail.lstrip(".")
