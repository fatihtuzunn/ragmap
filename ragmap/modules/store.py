"""The vector store behind the chat endpoint.

Everything else in this scanner measures what a RAG system chooses to
reveal through its chat API. That framing has a blind spot, and it is a
large one: the chat endpoint is not the only way into the corpus. The
vector database behind it listens on its own port, speaks its own REST
API, and in a default deployment it has no authentication at all, because
the quickstart that put it there assumed it would never be reachable.

When that is true, every careful conclusion this tool draws about the
chat endpoint stops mattering. It does not matter that passages are
withheld, that a similarity threshold cuts off-topic queries, or that
scores are hidden, if the same corpus can be listed and downloaded
directly from port 8000 by anyone who asks. This is the one finding that
outranks observability, and it is invisible to a scanner that only knows
how to send chat messages.

**Scope.** The probe stays on the host the operator already named. It
does not scan a range, does not try other hosts, and does not follow
redirects somewhere else. It reads identity and counts - what product is
this, how many collections, how many vectors - and never retrieves
documents, even when the store would hand them over. The count is the
finding; the contents are the client's.

``--vector-store URL`` points it somewhere else outright, for a
deployment that keeps its store on another machine. ``--skip store`` turns
it off, which is the right call when the engagement covers one URL and
nothing else on the host.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .. import findings
from ..context import Context
from ..registry import Module, register

# One identifying request per product, chosen to be the cheapest endpoint
# that names the thing without listing anything sensitive. Ports are the
# documented defaults; a store moved elsewhere needs --vector-store.
#
# Each entry: (product, port, path, marker) where marker is a string that
# must appear in the reply for the identification to count. Matching on a
# marker rather than on status alone keeps an unrelated web server on the
# same port from being reported as a vector database.
PROBES: tuple[tuple[str, int, str, tuple[str, ...]], ...] = (
    ("Chroma",        8000, "/api/v2/heartbeat",   ("nanosecond heartbeat",)),
    ("Chroma",        8000, "/api/v1/heartbeat",   ("nanosecond heartbeat",)),
    ("Qdrant",        6333, "/",                   ("qdrant",)),
    ("Weaviate",      8080, "/v1/meta",            ("version", "hostname")),
    ("Milvus",        9091, "/healthz",            ("ok",)),
    ("Elasticsearch", 9200, "/",                   ("lucene_version",
                                                    "cluster_name")),
    ("Marqo",         8882, "/indexes",            ("results", "indexName")),
)

# Followed only once a product has answered, to turn "something is here"
# into "and it is open". Still counts and names; never reads documents.
INVENTORY: dict[str, tuple[str, ...]] = {
    "Chroma": ("/api/v2/tenants/default_tenant/databases/"
               "default_database/collections",
               "/api/v1/collections"),
    "Qdrant": ("/collections",),
    "Weaviate": ("/v1/schema",),
    "Elasticsearch": ("/_cat/indices?format=json",),
    "Marqo": ("/indexes",),
    "Milvus": (),
}

UNAUTH_STATUSES = (200, 201)
AUTH_STATUSES = (401, 403)


@register
class VectorStoreExposure(Module):
    name = "store.exposed"
    section = "store"
    # Level 2: it is not a retrieval measurement, but an operator deciding
    # whether to go deeper should learn this before spending a budget on
    # inferring through the chat API what the store would simply hand over.
    level = 2
    cost = 8
    value = 9
    requires = ()
    provides = ("store.product", "store.auth", "store.inventory")
    description = "Look for the vector database behind the chat endpoint"

    def run(self, ctx: Context) -> None:
        targets = self._targets(ctx)
        if not targets:
            for key in self.provides:
                ctx.skip_fact(key, status="not-applicable",
                              reason="no host to probe",
                              module=self)
            return

        found: tuple[str, str, Any] | None = None
        tried = 0

        for product, base, path, markers in targets:
            if ctx.transport.remaining <= 1:
                break
            url = base + path
            tried += 1
            probe = ctx.transport.fetch(url, label=f"store? {product}")
            if probe.error or probe.status is None:
                continue
            if probe.status in AUTH_STATUSES:
                found = (product, base, probe)
                break
            if probe.status in UNAUTH_STATUSES and _marked(probe, markers):
                found = (product, base, probe)
                break

        if found is None:
            ctx.set_fact(
                "store.product", "vector store", None,
                display="none reachable", section="store",
                method=f"{tried} default vector-store endpoints tried on the "
                       f"target's own host",
                evidence=", ".join(sorted({p for p, _, _, _ in targets})),
                kind="direct")
            for key in ("store.auth", "store.inventory"):
                ctx.skip_fact(key, status="not-applicable",
                              reason="no vector store answered on this host",
                              module=self)
            return

        product, base, probe = found
        authenticated = probe.status in AUTH_STATUSES

        ctx.set_fact(
            "store.product", "vector store", product,
            display=f"{product} at {_netloc(base)}", section="store",
            method="default API endpoint answered with a recognisable reply",
            evidence=f"HTTP {probe.status} from {probe.url}", kind="direct")

        ctx.set_fact(
            "store.auth", "store auth", not authenticated,
            display="required" if authenticated else "NONE",
            section="store",
            method=f"HTTP {probe.status} to an unauthenticated request",
            evidence=("the store refused an anonymous request"
                      if authenticated else
                      "the store answered an anonymous request"),
            kind="direct")

        if authenticated:
            ctx.set_fact(
                "store.inventory", "store contents", None,
                display="not readable anonymously", section="store",
                method="inventory not attempted; the store requires "
                       "credentials",
                kind="direct")
            ctx.note(f"A {product} instance is reachable at "
                     f"{_netloc(base)} but requires credentials. Reachable "
                     f"is not the same as exposed - but it is one stolen "
                     f"key away from it, and it is worth knowing whether "
                     f"that port should be open to you at all.")
            return

        self._inventory(ctx, product, base)

    # ------------------------------------------------------------------
    def _targets(self, ctx: Context):
        """Where to look: the operator's own choice, or the target's host."""
        override = getattr(ctx.config, "vector_store", None)
        if override:
            parts = urlsplit(override if "//" in override
                             else f"http://{override}")
            base = urlunsplit((parts.scheme or "http", parts.netloc, "", "", ""))
            # Named outright: try every product's path against it, since
            # the operator knows the address but not necessarily which
            # product is listening.
            return [(product, base, path, markers)
                    for product, _port, path, markers in PROBES]

        if not ctx.config.url:
            return []
        parts = urlsplit(ctx.config.url)
        host = parts.hostname
        if not host:
            return []
        scheme = "https" if parts.scheme == "https" else "http"
        return [(product, f"{scheme}://{_host(host)}:{port}", path, markers)
                for product, port, path, markers in PROBES]

    def _inventory(self, ctx: Context, product: str, base: str) -> None:
        """Count what is there. Never read it."""
        names: list[str] = []
        status = None
        for path in INVENTORY.get(product, ()):
            if ctx.transport.remaining <= 1:
                break
            probe = ctx.transport.fetch(base + path,
                                        label=f"store inventory {product}")
            status = probe.status
            if probe.status not in UNAUTH_STATUSES:
                continue
            names = _collection_names(probe.body)
            if names:
                break

        if names:
            ctx.set_fact(
                "store.inventory", "store contents", names,
                display=f"{len(names)} collection(s) listed", section="store",
                method="the store's own collection listing, read anonymously",
                evidence=", ".join(names[:4]), kind="direct")
        else:
            ctx.set_fact(
                "store.inventory", "store contents", [],
                display="listing not returned", section="store",
                method=f"collection listing requested; HTTP {status}",
                evidence="the store answered but named no collections",
                kind="direct")

        detail = (f"{len(names)} collection(s): {', '.join(names[:4])}"
                  if names else "collections not enumerated")
        ctx.add_finding(findings.make(
            "RAGMAP-014",
            f"{product} is reachable at {_netloc(base)} without credentials",
            evidence=detail,
            facts=("store.product", "store.auth", "store.inventory")))

        ctx.note(
            f"{product} answered an anonymous request at {_netloc(base)}. "
            f"Everything this scan measured about what the chat endpoint "
            f"withholds is moot while the corpus can be read, and written, "
            f"straight from the store. ragmap counted the collections and "
            f"stopped there; it did not download any documents.")


# ----------------------------------------------------------------------
def _host(host: str) -> str:
    """Bracket an IPv6 literal so it can carry a port."""
    return f"[{host}]" if ":" in host else host


def _netloc(base: str) -> str:
    return urlsplit(base).netloc or base


def _marked(probe, markers: tuple[str, ...]) -> bool:
    body = probe.raw_text or ""
    if not body and probe.body is not None:
        body = json.dumps(probe.body, ensure_ascii=False, default=str)
    lowered = body.lower()
    return any(marker.lower() in lowered for marker in markers)


def _collection_names(body: Any) -> list[str]:
    """Pull collection names out of whichever shape the store returned."""
    names: list[str] = []

    def take(value: Any) -> None:
        if isinstance(value, str) and value and value not in names:
            names.append(value)

    if isinstance(body, dict):
        # Qdrant: {"result": {"collections": [{"name": ...}]}}
        inner = body.get("result")
        if isinstance(inner, dict):
            body = inner.get("collections", inner)
        # Weaviate schema: {"classes": [{"class": ...}]}
        for key in ("classes", "collections", "indexes", "results"):
            if isinstance(body, dict) and isinstance(body.get(key), list):
                body = body[key]
                break

    if isinstance(body, list):
        for item in body[:50]:
            if isinstance(item, str):
                take(item)
            elif isinstance(item, dict):
                for key in ("name", "class", "collection_name", "index",
                            "indexName"):
                    if isinstance(item.get(key), str):
                        take(item[key])
                        break
    return names[:50]
