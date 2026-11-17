# The lab: `mockrag`

This is not a target. It is an **instrument for checking the instrument**.

Against a real deployment you only know the ground truth as well as an admin
screen happens to show it. Here the chunk size, overlap, top-k, threshold,
router, cache and observability level are values *you* set, served back at
`/__ground_truth`. So you can establish that ragmap reads a system correctly
before you point it at one you do not control.

```
lab/
├── mockrag/
│   ├── server.py        the configurable RAG server (stdlib + requests)
│   ├── profiles.json    10 profiles = 10 different ground truths
│   └── calibrate.py     runs all of them and scores the scanner
└── corpus/              5 fictional policy documents + MANIFEST.md
```

---

## Running it

```bash
python lab/mockrag/server.py --port 8099
```

It reads the corpus at startup, chunks it, and stays up. The profile is
chosen by the URL, so **one server serves ten targets at once**:

```
http://127.0.0.1:8099/v1/chat/completions?profile=o0_opaque
http://127.0.0.1:8099/v1/chat/completions?profile=o3_full
http://127.0.0.1:8099/api/v1/workspace/ragmap-test/chat?profile=anythingllm_like
http://127.0.0.1:8099/v1/chat-messages?profile=dify_like
```

`profiles.json` is re-read on every request, so changing a profile needs no
restart. The corpus and the chunk index *are* cached — restart after editing
anything under `lab/corpus/`.

### Helper endpoints

| Endpoint | Returns |
|---|---|
| `GET /healthz` | up or not, which generator, which model |
| `GET /__ground_truth?profile=X` | that profile's FULL ground truth |
| `GET /__corpus` | loaded documents and chunk counts |
| `GET /__profiles` | profile names and descriptions |

Nothing in the scanner reads those endpoints during a scan. They exist for
`calibrate.py` and for you.

---

## Install

```bash
python -m venv .venv
.venv/Scripts/activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

Nothing else. The retrieval layer is TF-IDF plus a character 3-gram term,
in pure Python: no vector database, no torch, no model download.

### The generation layer

With no API key the server runs a deterministic **mock generator** that
assembles the answer from the retrieved chunks with a template. Retrieval,
chunking, scoring and response shapes are all real in mock mode, so the
retrieval-side calibration is valid without a key.

Two detectors are **not** meaningful against the mock generator:

- **verbatim leak** — the mock generator copies chunk text into the answer
  by construction, so a "leak" there is the fixture, not a finding.
- **determinism** — the mock generator is deterministic by construction.

For those two, point the server at a real LLM:

```bash
export GROQ_API_KEY=gsk_...          # PowerShell: $env:GROQ_API_KEY="gsk_..."
```

The model is chosen automatically: the server fetches Groq's model list at
startup and takes the first of its preferences that is actually available.
Override with `GROQ_MODEL` or `--model`; `GET /healthz` says what a running
server settled on.

### What was measured on Groq (2026-11-16)

The catalogue was narrower than expected — no Llama models; the chat-capable
ones were `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b` and
`allam-2-7b`, and auto-selection took `gpt-oss-120b`. **Do not treat the
preference list as fact**: Groq's catalogue changes often, which is why
`_pick_model` verifies it at startup rather than trusting the constant.

**Reasoning models eat the completion budget.** The `gpt-oss` family emits
invisible reasoning tokens:

| Setting | Reasoning tokens | Visible answer |
|---|---|---|
| `max_tokens=20` | 18 | **empty** |
| `max_tokens=700`, default reasoning | 295 | 625 characters |
| `max_tokens=900`, `reasoning_effort=low` | 25 | 625 characters (identical) |

Hence the defaults `max_tokens=900` and `reasoning_effort=low`. Run with a
low `max_tokens` and you get empty answers, which is very easy to mistake
for an observability finding.

**Rate limits (free tier, measured).** The binding limit is tokens per
minute: `x-ratelimit-limit-tokens: 8000`, with 1000 requests per day. A
typical probe costs ~970 prompt + ~160 completion = ~1130 tokens, so the
safe ceiling is about **6 requests per minute** — `--delay 9` or more.

The server also backs off on a 429, but that is a safety valve only: waiting
inflates the latency the scanner measures. When it happens the response
carries an `X-RAGmap-Throttled-Ms` header and **that exchange must be left
out of anything read off the latency axis**. The figure is deliberately not
added to the response body, because a new body field would pollute the
scanner's structural field search — and polluting the thing under test is
exactly what a calibration rig must not do.

---

## The profiles

| Profile | Level | Shape | What it tests |
|---|---|---|---|
| `o0_opaque` | O0 | openai | No sources, but a token counter and no verbatim guard |
| `o0_hardened` | O0 | openai | Quoting ban + no token counter. The control group |
| `o1_narrative` | O1 | openai | Sources named only inside the answer prose |
| `o2_structured` | O2 | openai | Identifiers present, chunk text absent |
| `o3_full` | O3 | openai | Chunk text + score + identifiers |
| `anythingllm_like` | O3 | anythingllm | AnythingLLM's shipped defaults: chunk 1000 / overlap 20, no threshold |
| `dify_like` | O3 | dify | **A trap**: the source field is named `retriever_resources` |
| `router_threshold` | O2 | openai | Router + threshold: retrieval never runs for off-corpus queries |
| `cached_hybrid` | O3 | openai | Semantic cache + hybrid retrieval (catches the rare literal) |
| `verbose_errors` | O2 | openai | Traceback and a fake framework trace on a bad request |

Adding a profile is a block in `profiles.json`; nothing else needs to change.

Two of these earn their place by being awkward:

- **`dify_like`** returns 800 characters of chunk text and a score under
  `metadata.retriever_resources`. A scanner matching a fixed list of field
  names (`sources`, `context`, `documents`) reads this fully transparent
  target as opaque. It is here so that failure mode shows up as a number.
- **`o1_narrative`** has no structured source field at all, but the answer
  mentions the document title. The honest result is O1-or-O0, and a scanner
  that confidently resolves it is overreaching.

---

## Calibration

```bash
python lab/mockrag/server.py --port 8099 &
python lab/mockrag/calibrate.py --level 4
```

It scans every profile, compares each fact with that profile's declared
truth, and writes:

- `docs/calibration-report.md` — the full table, plus a per-target breakdown
- `ragmap/data/calibration.json` — the numbers the scanner prints in
  brackets next to a value during a real engagement

So `cal 7/7, MAE 0` in a report is not a hand-written confidence label. It
is the score that detector got here, shipped with the tool.

Useful flags: `--only o3_full` for one profile, `--level 5` for everything,
`--no-write` to leave `calibration.json` alone, `--base` for a server on
another port.

### Four things the scoring does on purpose

1. **An abstention is not a hit.** A detector that ran and said "not
   measurable" is counted separately from one that returned the right value.
2. **A detector that never ran is counted separately again.** Scoring
   silence as agreement would be free marks: `bool(None) == bool(False)`
   would credit a level-gated detector with correctly knowing there is no
   router.
3. **A silent failure is its own column.** Returning nothing while the
   information needed was on screen is a worse defect than returning the
   wrong number, and it is the one that hides.
4. **The score is conditioned on what the target exposes.** `chunk.size`
   scoring 4/9 is not a bug in the table. Chunk width is measured exactly
   when passages are visible and recovered unreliably when it has to come
   through verbatim extraction. That limit is published rather than averaged
   away.

### The honest limit of the retrieval layer

The embedding layer is TF-IDF, not a real dense encoder. `dense` mode
**imitates** a dense retriever's exact-match blindness by dropping literals
that occur once in the corpus from the query representation. The character
3-gram term ensures every query — nonsense included — gets a non-zero score,
which is what happens in a real vector space and what makes the nonsense
probe meaningful at all.

This is not a measurement of any embedding model. To fit a real encoder,
replace the vectorisation in `Index._query_vector` and `Chunk.vector`;
everything else works unchanged.

A target this simple cannot stand in for a production RAG, and the numbers
it produces are a lower bound on what a scan faces in the field. That is why
the live walkthrough in [LIVE-TARGET.md](LIVE-TARGET.md) exists: it points
ragmap at AnythingLLM, which nobody here wrote.
