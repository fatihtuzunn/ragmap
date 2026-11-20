# Changelog

## 0.2.0 - 2026-11-20

Two things this release is about: reading the retrieval index itself
rather than only the answers it produces, and being honest about how much
noise the scan makes while doing it.

Until now every passage was treated as a piece of text with a score. It is
also a numbered position in a document, cut at a particular boundary, in a
store that may or may not keep its identifiers straight - and all of that
was arriving on every response and being discarded. Reading it costs no
requests and says things nothing else here can: how much of a corpus is
still unseen, whether two documents share an identifier, whether the
configured chunk size is a width or a ceiling.

The operational side caught up at the same time: a proxy, jittered pacing,
session rotation, and explicit response paths for the targets structural
detection reads wrong.

Calibration against the lab went from **66/72 to 87/90**, with three new
scored detectors and no detector worse than before.

### New: what the index gives away

- `chunking.index` reads the chunk identifier scheme, reports whether
  numbering is scoped per document or globally, and turns the ids a scan
  has seen into a **coverage bound** - how many passages the corpus holds
  at minimum and how many were never retrieved.
- Identifiers shared by two documents are reported and raise
  **RAGMAP-011**: the store cannot tell those documents apart.
- Random identifiers (uuids, hex blobs) are reported as `opaque` and
  coverage is declined. A trailing hex digit is not a sequence position;
  before that rule, AnythingLLM's uuids produced "10 seen, >= 710 exist"
  on a five-document corpus.
- `chunking.quality` measures passage length **in tokens** as well as
  characters, with median, p95 and max, and names the smallest embedding
  window the widest passage still fits. `pip install 'ragmap[tokens]'` for
  real counts; without it they are estimated and say so.
- The same detector reports the **splitter family**: a fixed window lands
  mid-sentence almost every time, a separator-aware one almost never.
  Only where a passage *ends* is evidence - where it starts is set by the
  overlap step - and a passage ending on a heading stopped at a boundary
  too. This is now corroborating evidence for whether `chunk.size` can be
  reported exactly or only bounded, a decision that used to rest on the
  shape of the length distribution alone.
- Passages indexed under more than one document raise **RAGMAP-012**, and
  encoded payloads in the index raise **RAGMAP-013**.
- Passages a target names but will not show (observability O2) are now
  kept. They were discarded for having no text, which blinded every
  identifier detector exactly where identifiers are the whole disclosure,
  and starved topic discovery of the document titles it could have used.
  That single change moved `chunk.size` from 4/9 to 7/9.

### New: how loud the scan is

- Every scan now ends with its own footprint - how many of the queries it
  sent match the patterns a defender's prompt-monitoring rules look for,
  by category, counted the way token spend is counted. A meter, not a
  mode: the first thing it flags is usually ragmap's own corpus discovery.
- Rate-based rules only count once their own threshold is reached, so one
  "tell me about X" is a user and twenty in a minute is a sweep.
- Text the operator supplies with `--topic`, `--rare-token` or
  `--seed-queries` is checked before the scan starts and warned about on
  stderr, because a tally arrives too late to help.
- Patterns ship in `ragmap/data/opsec.json`; `--opsec-rules FILE` merges
  a client's own. JSON rather than YAML, to keep the dependency count at
  one.

### New: operating the thing

- `--proxy URL` sends every request through Burp or ZAP.
- `--jitter SEC` spreads the pace around `--delay` without changing its
  average, so a scan is not a straight line in a request log.
- `--rotate-every N` carries a session id in the body and changes it every
  N requests. Off by default: inventing a field the target did not ask for
  can change how it routes the request.
- Supplying all four probe values (`--topic`, `--second-topic`,
  `--absent-topic`, `--rare-token`) now skips corpus discovery outright
  instead of running its questions anyway. On the lab that is 42 requests
  down to 33, with the same eight findings - and the questions it drops
  are the loudest the scan sends.
- `--source-path`, `--answer-path`, `--text-path`, `--title-path`,
  `--chunk-id-path`, `--doc-id-path`, `--score-path` and `--page-path`
  name response locations outright when structural detection is wrong. A
  path that resolves to nothing leaves the field empty rather than falling
  back, so a wrong path looks like a wrong path.

### Fixed

- Chunk identifiers were parsed out of every response and then dropped on
  the way into the chunk store.
- A fact label exactly as wide as its column ran into its own value.
- A detector that runs twice - every free inventory detector does - left
  two notes saying the same thing with different numbers. Notes can now
  carry a key and supersede themselves.
- The scan's results directory holds `ragmap.txt` as well as `ragmap.json`;
  the live-target walkthrough had been telling readers to open a file that
  was never written.
- The calibration report's detector table was one column short of its own
  header.

### Lab

- `mockrag` gained a second splitter. `fixed` is the old character window;
  `recursive` cuts on paragraph and sentence boundaries the way LangChain,
  AnythingLLM and LlamaIndex do, which makes `chunk_size` a ceiling.
  `anythingllm_like` now uses it, so the splitter detector has something to
  be wrong about - a rig that only cuts one way would score a hard-coded
  answer as perfect.
- Ground truth now declares `splitter`, `chunk_id_scheme` and
  `chunk_id_collisions`, and the harness scores all three.


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
