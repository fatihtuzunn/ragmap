"""Exercise the vector-store detector without a network.

Three things can go wrong here and none of them shows up in a live run
against a target that happens to have no store on it:

  * a web server that is not a vector database gets reported as one, and
    the operator hands a client a high-severity finding about a port that
    serves a status page;
  * a store that requires credentials gets reported as open;
  * the detector reads documents out of a store it was only supposed to
    count, which is the one thing a read-only scanner must never do.

The transport is replaced with a scripted one, so each case is a fixed
set of replies and the assertions are about the decision, not the network.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragmap.config import ScanConfig
from ragmap.context import Context
from ragmap.modules.store import VectorStoreExposure, _collection_names
from ragmap.transport import Probe, Transport

HEARTBEAT = '{"nanosecond heartbeat": 1795202012291000}'
COLLECTIONS = ('[{"id": "9d1c", "name": "company_docs"},'
               ' {"id": "a4f2", "name": "hr_policies"}]')
# A status page on 8000 that has nothing to do with retrieval.
NOT_A_STORE = '{"status": "ok", "service": "internal-metrics"}'


def make_ctx(replies, url="http://target.invalid/api/chat"):
    """replies: path fragment -> (status, body). Anything else refuses."""
    transport = Transport(url=url, budget=50, delay=0)
    sent = []

    def fetch(target, *, timeout=4.0, label=""):
        sent.append(target)
        probe = Probe(query=label, url=target, index=len(sent))
        for fragment, (status, body) in replies.items():
            if fragment in target:
                probe.status = status
                probe.raw_text = body
                try:
                    import json
                    probe.body = json.loads(body)
                except ValueError:
                    probe.body = body
                return probe
        probe.error = "ConnectionError: refused"
        return probe

    transport.fetch = fetch
    ctx = Context(ScanConfig(url=url), transport)
    ctx._sent = sent
    return ctx


def run(ctx):
    module = VectorStoreExposure()
    ctx.begin(module)
    try:
        module.run(ctx)
    finally:
        ctx.end()
    return module


print("case 1: an open store is identified, counted, and reported")
ctx = make_ctx({"8000/api/v2/heartbeat": (200, HEARTBEAT),
                "default_database/collections": (200, COLLECTIONS)})
module = run(ctx)
print("   product:", ctx.facts["store.product"].display,
      "| auth:", ctx.facts["store.auth"].display,
      "| contents:", ctx.facts["store.inventory"].display)
assert ctx.get("store.product") == "Chroma"
assert ctx.get("store.auth") is True          # True means no auth required
assert ctx.get("store.inventory") == ["company_docs", "hr_policies"]
assert [f.id for f in ctx.findings] == ["RAGMAP-014"]
assert ctx.findings[0].severity == "high"

print("case 2: a store behind credentials is not a finding")
ctx = make_ctx({"8000/api/v2/heartbeat": (401, '{"error": "Unauthorized"}')})
run(ctx)
print("   product:", ctx.facts["store.product"].display,
      "| auth:", ctx.facts["store.auth"].display)
assert ctx.get("store.product") == "Chroma"
assert ctx.get("store.auth") is False
assert not ctx.findings, "a store that refused anonymous access is not open"

print("case 3: nothing listening is reported as nothing listening")
ctx = make_ctx({})
run(ctx)
print("   ", ctx.facts["store.product"].display)
assert ctx.get("store.product") is None
assert not ctx.findings

print("case 4: a 200 from something that is not a store is not a store")
ctx = make_ctx({"8000/api/v2/heartbeat": (200, NOT_A_STORE),
                "8000/api/v1/heartbeat": (200, NOT_A_STORE)})
run(ctx)
print("   ", ctx.facts["store.product"].display)
assert ctx.get("store.product") is None, \
    "a reply without the product's own marker must not be identified"
assert not ctx.findings

print("case 5: the detector counts collections and never reads documents")
ctx = make_ctx({"8000/api/v2/heartbeat": (200, HEARTBEAT),
                "default_database/collections": (200, COLLECTIONS)})
module = run(ctx)
print("   requests:", len(ctx._sent))
for target in ctx._sent:
    for forbidden in ("/get", "/query", "/documents", "include="):
        assert forbidden not in target, f"{target} would read documents"
assert len(ctx._sent) <= module.cost, \
    f"{len(ctx._sent)} requests against a declared cost of {module.cost}"

print("case 6: a named store is tried wherever the operator pointed")
config = ScanConfig(url="http://target.invalid/api/chat",
                    vector_store="10.0.0.9:9999")
transport = Transport(url=config.url, budget=50, delay=0)
seen = []


def fetch(target, *, timeout=4.0, label=""):
    seen.append(target)
    probe = Probe(query=label, url=target, index=len(seen))
    if "9999" in target and "heartbeat" in target:
        probe.status, probe.raw_text = 200, HEARTBEAT
        probe.body = {"nanosecond heartbeat": 1}
        return probe
    probe.error = "ConnectionError: refused"
    return probe


transport.fetch = fetch
ctx = Context(config, transport)
run(ctx)
print("   ", ctx.facts["store.product"].display)
assert ctx.get("store.product") == "Chroma"
assert all("target.invalid" not in t for t in seen), \
    "with --vector-store given, the target's own host must not be probed"

print("case 7: collection names come out of each store's own shape")
shapes = {
    "plain list": ([{"name": "a"}, {"name": "b"}], ["a", "b"]),
    "qdrant": ({"result": {"collections": [{"name": "docs"}]}}, ["docs"]),
    "weaviate": ({"classes": [{"class": "Policy"}]}, ["Policy"]),
    "elasticsearch": ([{"index": "rag-idx", "health": "green"}], ["rag-idx"]),
    "bare strings": (["one", "two"], ["one", "two"]),
}
for name, (body, expected) in shapes.items():
    got = _collection_names(body)
    print(f"   {name:<14} -> {got}")
    assert got == expected, f"{name}: {got} != {expected}"

print("all vector-store cases pass")
