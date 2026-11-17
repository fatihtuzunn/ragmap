"""Exercise the spend planner and the probe cache without a network.

Both decide what a scan buys, and both can be wrong in ways a live run
hides: a planner that quietly orphans a dependency, or a cache that hands a
rate-limited reply to the next detector that asks the same question.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragmap import modules as _modules          # noqa: F401  (registers)
from ragmap.config import SPEND_TIERS, ScanConfig
from ragmap.context import Context
from ragmap.registry import all_modules, plan, select
from ragmap.transport import Transport

GOOD = {"textResponse": "Retention is ten years.",
        "sources": [{"title": "policy.md", "text": "x" * 300, "score": 0.5}],
        "error": None}
ABORT = {"type": "abort", "sources": [], "textResponse": None,
         "error": "429 Rate limit reached on tokens per minute (TPM)."}


class FakeResponse:
    def __init__(self, payload, status):
        self._payload, self.status_code = payload, status
        self.headers = {"Content-Type": "application/json"}

    @property
    def text(self):
        import json
        return json.dumps(self._payload)

    def json(self):
        return self._payload


def make_ctx(script):
    t = Transport(url="http://fake.invalid", budget=50, delay=0)
    t.body_template = {"message": "{{QUERY}}"}
    calls = {"n": 0}

    def post(url, **kwargs):
        payload, status = script[min(calls["n"], len(script) - 1)]
        calls["n"] += 1
        return FakeResponse(payload, status)

    t.session = types.SimpleNamespace(post=post)
    ctx = Context(ScanConfig(url="http://fake.invalid"), t)
    ctx._calls = calls
    return ctx


def chosen_names(level, budget):
    selected, _ = select(all_modules(), level)
    kept, dropped = plan(selected, budget)
    return [m.name for m in kept], {m.name: n for m, n in dropped}


print("case 1: a plan never exceeds its budget")
for level in (1, 2, 3, 4, 5):
    for budget in (5, 12, 20, 35, 60, 90, 220):
        kept, _ = chosen_names(level, budget)
        spent = sum(m.cost for m in all_modules() if m.name in kept)
        assert spent <= budget, (level, budget, spent)
print("   checked 35 level/budget combinations")

print("case 2: a chosen module never has an unmet in-plan dependency")
for level in (2, 3, 4, 5):
    for budget in (12, 20, 35, 90, 220):
        kept, _ = chosen_names(level, budget)
        produced = set()
        for module in all_modules():
            if module.name in kept:
                produced.update(module.provides)
        everything = {k for m in all_modules() for k in m.provides}
        for module in all_modules():
            if module.name not in kept:
                continue
            for key in module.requires:
                # A requirement nothing in the registry provides is produced
                # by shape detection, outside the plan.
                assert key not in everything or key in produced, \
                    (module.name, key, level, budget)
print("   no orphaned dependencies")

print("case 3: a tight budget buys the headline facts, not the filler")
kept, dropped = chosen_names(SPEND_TIERS["quick"]["level"],
                             SPEND_TIERS["quick"]["budget"])
print("   quick buys:", ", ".join(kept))
assert "retrieval.topk" in kept, "top-k was priced out of the quick tier"
assert "corpus.discover" in kept, "its prerequisite was not bought with it"

print("case 4: a bigger budget is never worse than a smaller one")
small, _ = chosen_names(4, 35)
large, _ = chosen_names(4, 220)
assert set(small) <= set(large), set(small) - set(large)

print("case 5: an answered question is not bought twice")
ctx = make_ctx([(GOOD, 200)])
first = ctx.ask("what is the retention period?")
second = ctx.ask("what is the retention period?")
print("   requests:", ctx._calls["n"], "| reused:", ctx.reused,
      "| cached flag:", second.cached)
assert ctx._calls["n"] == 1 and ctx.reused == 1 and second.cached
assert second.answer == first.answer

print("case 6: fresh=True always buys a real request")
ctx = make_ctx([(GOOD, 200)])
ctx.ask("what is the retention period?")
ctx.ask("what is the retention period?", fresh=True)
print("   requests:", ctx._calls["n"], "| reused:", ctx.reused)
assert ctx._calls["n"] == 2 and ctx.reused == 0

print("case 7: a failed exchange is never replayed as evidence")
ctx = make_ctx([(ABORT, 500), (ABORT, 500), (ABORT, 500), (ABORT, 500),
                (GOOD, 200)])
first = ctx.ask("what is the retention period?")
assert not first.ok, "the fake target should have failed"
before = ctx._calls["n"]
second = ctx.ask("what is the retention period?")
print("   first failed, second sent a real request:", ctx._calls["n"] > before,
      "| ok:", second.ok)
assert ctx._calls["n"] > before, "a rate-limited reply was cached"
assert second.ok and not second.cached

print("case 8: a different question is a different request")
ctx = make_ctx([(GOOD, 200)])
ctx.ask("one")
ctx.ask("two")
assert ctx._calls["n"] == 2 and ctx.reused == 0

print("case 9: a re-run detector costs nothing and judges nothing")
for module in all_modules():
    if not module.resettle:
        continue
    # Re-running a detector that spends requests would double its cost
    # silently, after the budget has already been reported as spent.
    assert module.cost == 0, f"{module.name} is re-run but costs requests"
resettled = [m.name for m in all_modules() if m.resettle]
print("   re-run at the end:", ", ".join(resettled))
assert "observability.level" not in resettled, \
    "a graded judgement must not be re-run over error-probe replies"
assert resettled, "nothing is re-run; the inventory facts will be stale"

print("all plan and cache cases pass")
