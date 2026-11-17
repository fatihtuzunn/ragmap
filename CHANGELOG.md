# Changelog

## 0.1.0 — 2026-11-17

First packaged release. Everything below has been measured against the
bundled lab, against a live AnythingLLM backed by a local Ollama model, or
both.

### The scanner

- Detectors for interface shape, retrieval presence, observability level,
  top-k, similarity threshold, retrieval mode, chunk size, chunk overlap,
  reranking, routing, caching, determinism, verbatim leakage, token
  channel, error verbosity and embedding behaviour.
- Request shapes detected structurally, covering OpenAI-compatible,
  AnythingLLM and Dify bodies, with `--shape` and `--query-field` to force
  one.
- Retrieved passages located by response *shape* rather than by a list of
  field names, with answer envelopes excluded so an opaque system is not
  read as transparent.
- Probe values (in-corpus topic, off-corpus topic, rare literal) derived
  from the target itself and confirmed against it before use.
- Bounded figures printed as bounds (`>= 897 chars`), never rounded into a
  value the evidence does not support.
- `--replay DIR` re-analyses a recorded scan offline, sending nothing.

### Spend

- `--spend peek|quick|standard|deep|max` sets a depth level and a request
  ceiling together.
- The planner buys detectors by value per request, including the
  prerequisites each drags in, with seeded fills so a cheap trio cannot eat
  the budget an expensive chain needed. Two re-planning passes recover the
  budget detectors did not use.
- `--tokens N` caps a scan in tokens, read from the target's own usage
  counters where it exposes them and estimated otherwise. Each request is
  priced from the body about to be sent, so the scan stops before crossing
  the ceiling. Refused requests are charged, because providers meter them.
- Answered questions are reused within a scan; detectors whose measurement
  is repetition or latency always send real requests. Failed exchanges are
  never cached or replayed as evidence.

### Rate limits

- A per-minute limit widens pacing and settles back after clean replies.
- A per-day or per-month allowance stops the scan, with a note saying where
  measurement ended — waiting cannot win one back inside a scan.
- Error-shaped bodies returned with HTTP 500 (AnythingLLM's `{"type":
  "abort"}`) are recognised as failures, not as successful exchanges that
  happened to retrieve nothing.

### Calibration

- `lab/mockrag` serves ten profiles whose true configuration is declared
  and exposed at `/__ground_truth`.
- `lab/mockrag/calibrate.py` scores every detector against that truth and
  ships the result in `ragmap/data/calibration.json`, which is where the
  bracketed `cal n/n` labels come from. Current total: 66/72.
- Abstentions, silent failures and never-run detectors are counted in
  separate columns, so a level-gated detector cannot score as a correct
  "no".

### Fixed during the live AnythingLLM run

Three defects with one root cause: zero-cost detectors ran at their place
in the dependency order and saw only the evidence that had arrived by then.
The scan's first exchange retrieved nothing, so it carried no token
counters and named no documents.

- The token channel reported "not exposed" while the scan was metering
  itself on the target's own token counts.
- The document inventory reported 2 identifiers above a passage list naming
  5.
- The same inventory was computed twice, in two places, with two different
  answers.

Fixed by `Module.resettle`: inventory detectors re-run once at the end of
the scan, over everything that came back. It is opt-in because the first
attempt applied it to `observability.level` as well, which then read prose
in error-probe replies as source attribution and promoted O0 targets to O1
— more evidence made a heuristic noisier, not better. `tests/test_plan.py`
now enforces that a re-run detector costs nothing and makes no graded
judgement.

All three were verified against the recorded exchanges with `--replay`, at
no further cost to the target.
