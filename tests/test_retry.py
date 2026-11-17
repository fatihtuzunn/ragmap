"""Exercise the rate-limit retry path without touching the network.

It had never run: a retry only happens when the target actually reports a
rate limit, and until the live scan hit one, the code path was dead.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragmap.transport import Transport

ABORT = {
    "id": "x", "type": "abort", "textResponse": None, "sources": [],
    "close": True,
    "error": ("429 Rate limit reached for model `openai/gpt-oss-20b` on "
              "tokens per minute (TPM): Limit 8000. Please try again in 0.01s."),
}
DAILY = {
    "id": "x", "type": "abort", "textResponse": None, "sources": [],
    "close": True,
    "error": ("429 Rate limit reached for model `openai/gpt-oss-20b` in "
              "organization `org_01` service tier `on_demand` on tokens per "
              "day (TPD): Limit 200000, Used 199163, Requested 1010. Please "
              "try again in 1m14.736s."),
}
GOOD = {"textResponse": "Retention is ten years.",
        "sources": [{"title": "policy.md", "text": "x" * 300, "score": 0.5}],
        "error": None}


class FakeResponse:
    def __init__(self, payload, status):
        self._payload = payload
        self.status_code = status
        self.headers = {"Content-Type": "application/json"}

    @property
    def text(self):
        import json
        return json.dumps(self._payload)

    def json(self):
        return self._payload


def make_transport(script):
    t = Transport(url="http://fake.invalid", budget=20, delay=0)
    t.body_template = {"message": "{{QUERY}}"}
    calls = {"n": 0}

    def post(url, **kwargs):
        payload, status = script[min(calls["n"], len(script) - 1)]
        calls["n"] += 1
        return FakeResponse(payload, status)

    t.session = types.SimpleNamespace(post=post)
    t._calls = calls
    return t


print("case 1: limited twice, then succeeds")
t = make_transport([(ABORT, 500), (ABORT, 500), (GOOD, 200)])
p = t.send("what is the retention period?")
print("   requests:", t._calls["n"], "| ok:", p.ok,
      "| answer:", repr(p.answer[:30]), "| sources:", len(p.sources))
assert t._calls["n"] == 3 and p.ok and p.sources, "retry did not recover"

print("case 2: limited throughout, gives up without raising")
t = make_transport([(ABORT, 500)])
p = t.send("what is the retention period?")
print("   requests:", t._calls["n"], "| ok:", p.ok,
      "| error:", (p.error or "")[:40])
assert t._calls["n"] == t.max_retries + 1, "wrong number of attempts"
assert not p.ok and p.error, "failure was not reported"

print("case 3: a clean reply is not retried")
t = make_transport([(GOOD, 200)])
p = t.send("what is the retention period?")
print("   requests:", t._calls["n"], "| ok:", p.ok)
assert t._calls["n"] == 1 and p.ok

print("case 4: a 400 is a shape problem, not a rate limit - no retry")
t = make_transport([({"error": "message is required"}, 400)])
p = t.send("hello")
print("   requests:", t._calls["n"], "| error:", (p.error or "")[:40])
assert t._calls["n"] == 1

print("case 5: a daily allowance is not retried and stops the scan")
t = make_transport([(DAILY, 500)])
p = t.send("what is the retention period?")
print("   requests:", t._calls["n"], "| remaining:", t.remaining,
      "| exhausted:", bool(t.exhausted))
assert t._calls["n"] == 1, "a per-day limit must not be retried"
assert t.exhausted and t.remaining == 0, "scan did not stop"

print("case 6: a per-minute limit still widens the pace rather than stopping")
t = make_transport([(ABORT, 500)])
t.delay = 1.0
t.base_delay = 1.0
t.max_delay = 0.0          # keep the test instant; pacing still records
p = t.send("what is the retention period?")
print("   requests:", t._calls["n"], "| exhausted:", bool(t.exhausted),
      "| throttled:", t.throttled)
assert not t.exhausted, "a pace limit must not be read as an allowance"

print("all retry cases pass")
