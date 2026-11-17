# ragmap

**Reconnaissance scanner for Retrieval-Augmented Generation systems.**

Point it at a chat endpoint and it works out what the retrieval layer is
doing: how wide the chunks are, how many are fetched, whether a similarity
threshold exists, whether retrieval is dense or lexical, what the corpus
covers, and what the system hands back to anyone who asks.

a scanner with depth
levels, a spend budget, declared detectors and a machine-readable report
not a checklist that asks a model what it thinks of itself.

```
$ ragmap -u https://chat.example.com/api/chat -H "Authorization: Bearer ..." --spend deep

[+] interface
    shape             openai-compatible           [1 shape tried]
    answer path       choices[0].message.content
    auth              supplied by operator
    model             gpt-4o-mini
    token counter     usage, usage.prompt_tokens  [context size is derivable]

[+] retrieval
    source field      citations
    observability     O3                          [passage text and scores exposed | cal 10/10]
    top-k             5 (fixed)                   [6/6 queries returned 5 | cal 7/7, MAE 0]
    chunk size        1000 chars                  [39 passages, 36 at modal width | cal 4/4, MAE 0]
    overlap           200 chars                   [30/30 adjacent pairs agree | cal 4/4, MAE 0]
    threshold         none                        [passages returned at every step]
    retrieval mode    dense                       [rare literal scored 0.008 vs baseline 0.464]
    router            none                        [general-knowledge queries retrieved too]

[!] findings
    RAGMAP-001  high    Verbatim chunk extraction
                         995 characters of source text recovered through the answer
    RAGMAP-002  medium  No similarity threshold
                         nonsense and off-domain queries still return passages
```

---

## Contents

- [Install](#install)
- [Quick start](#quick-start)
- [What is in this repository](#what-is-in-this-repository)
- [Depth: `--level`](#depth---level)
- [Spend: `--spend`, `--budget`, `--tokens`](#spend---spend---budget---tokens)
- [When the target refuses](#when-the-target-refuses)
- [Flags](#flags)
- [Output](#output)
- [How it works](#how-it-works)
- [Observability levels](#observability-levels)
- [Calibration](#calibration)
- [Writing a detector](#writing-a-detector)
- [Scope and authorisation](#scope-and-authorisation)

---

## Install

Python 3.10 or newer. The only dependency is `requests`.

```bash
python -m venv .venv
```

```bash
.venv/Scripts/activate
```

On Linux or macOS that last line is `source .venv/bin/activate`. Then:

```bash
pip install -e .
```

```bash
ragmap --version
```

`pip install -e .` puts a `ragmap` command on your path. To run from the
checkout without installing anything, use `python -m ragmap` instead —
every example below works either way, as long as `requests` is available:

```bash
pip install -r requirements.txt
```

Check the install without touching a network:

```bash
python tests/run_all.py
```

---

## Quick start

### Against the bundled lab

No API key, no external service, about a minute:

```bash
python lab/mockrag/server.py --port 8099
```

Then, in another shell:

```bash
ragmap -u "http://127.0.0.1:8099/v1/chat/completions?profile=o3_full" --spend quick
```

The lab server declares its own true configuration at
`http://127.0.0.1:8099/__ground_truth?profile=o3_full`, so you can check
every number the scan prints. Ten profiles cover observability O0 to O3,
thresholds, routers, caches, dense and hybrid retrieval, and three response
shapes. See [docs/LAB.md](docs/LAB.md).

### Against a real product

[docs/LIVE-TARGET.md](docs/LIVE-TARGET.md) walks through scanning
**AnythingLLM** backed by a local **Ollama** model, configured away from
its defaults, with its true settings written down beforehand. That run
ships in this repository:

```bash
ragmap --replay examples/anythingllm-ollama
```

That re-analyses 32 recorded exchanges and sends nothing.

### Against something of your own

```bash
ragmap -u https://host/api/chat --auth-bearer TOKEN --spend quick
```

Start at `--spend peek` on a target you do not control. It is four
requests and it tells you whether there is a retrieval layer there at all.

---

## What is in this repository

```
ragmap/              the scanner
├── cli.py           argument surface, banner, exit codes
├── scanner.py       orchestration: shape detection, planning, assembly
├── registry.py      the Module contract and the spend planner
├── transport.py     requests, pacing, retry, token accounting, recording
├── context.py       facts, findings, chunk store, probe cache
├── shapes.py        request-shape detection (OpenAI, AnythingLLM, Dify, ...)
├── discovery.py     deriving probe values from the target's own corpus
├── confidence.py    calibration lookup for the bracketed [cal n/n] labels
├── modules/         the detectors, one file per area
├── output/          terminal and JSON renderers
└── data/            calibration.json, produced by the lab

lab/                 a RAG target whose ground truth is declared, not guessed
├── mockrag/         the server, its profiles, and the calibration harness
└── corpus/          five fictional policy documents + MANIFEST.md

docs/
├── LAB.md                    running the lab and reading its numbers
├── LIVE-TARGET.md            the AnythingLLM + Ollama walkthrough
└── calibration-report.md     the current scores, per detector and per target

examples/
└── anythingllm-ollama/       a finished scan: report, JSON, and raw exchanges

tests/                        offline tests; no network, no server
```

The lab is not decoration. The confidence figures the scanner prints come
out of it, and a detector whose score is not in
[docs/calibration-report.md](docs/calibration-report.md) is a detector
nobody has measured.

---

## Depth: `--level`

Depth controls which detectors are eligible
Higher levels enable more and spend more.

| Level | Adds | Requests |
|---|---|---|
| 1 | interface, retrieval presence, observability, top-k, token channel | ~15 |
| 2 | corpus discovery, coarse threshold, routing, error verbosity | ~40 |
| 3 *(default)* | chunk size, retrieval mode, cache, determinism, verbatim leak | ~80 |
| 4 | chunk overlap, reranker, fine threshold | ~160 |
| 5 | embedding behaviour, long-context probes | ~300 |

A detector excluded by level is reported as `skipped (level)`, not dropped
silently. Knowing that something was never looked at is part of the result.

---

## Spend: `--spend`, `--budget`, `--tokens`

Depth says *what* to look for. Spend says how much of the target's
allowance to eat looking. They are separate knobs for a reason: asking for
level 4 on thirty requests produces a report full of `skipped (budget)`.
`--spend` sets both at once.

| Tier | Level | Ceiling | Requests used | Facts | Buys |
|---|---|---|---|---|---|
| `peek` | 1 | 12 | 4 | 11 | is it a RAG, and what shows from outside |
| `quick` | 2 | 35 | 32 | 22 | + corpus topics, top-k, threshold |
| `standard` *(default)* | 3 | 90 | 42 | 27 | + chunk size, mode, verbatim leak |
| `deep` | 4 | 220 | 42 | 29 | + chunk overlap, reranker |
| `max` | 5 | 700 | 45 | 30 | everything |



### How a budget is spent

Running detectors in dependency order until the money runs out spends
whatever happened to come first. A scan capped at thirty requests bought
corpus discovery and stopped, and the operator got a report with no top-k
in it.

So each detector declares what it costs in requests and what a reader
learns from it (1-10), and the planner buys by **value per request**,
counting the prerequisites a detector drags in with it. `--list-modules`
prints both numbers. They are a judgement, and printing them is how that
judgement gets argued with.

Density alone is myopic — three cheap middling detectors can eat the budget
a single expensive chain needed — so the planner also tries committing to
each detector in turn and filling around it, and keeps the most valuable
plan. What a detector declares is a ceiling, and most come in under it, so
a second pass re-plans against what is actually left.

### Token ceilings

`--tokens N` is a ceiling in tokens rather than requests, for targets
metered that way.

Counts come from the target's own usage fields where it exposes them
(`usage.prompt_tokens`, `prompt_eval_count`, `input_tokens`) and are
estimated at four characters to a token otherwise; the report says which.
Once shape detection has paid for a real exchange, the cost of a request
against *this* target is known rather than assumed, and the token ceiling
is converted into a request budget at that rate — a top-k of 12 over
1200-character chunks costs four times what a terse endpoint does. Each
request is then priced from the body about to be sent, so the scan stops
before the one that would cross the ceiling rather than after it.

**Refused requests are charged too.** Providers meter the tokens a prompt
asked for, not the ones they ended up generating, so a scan that only
counted answered exchanges would walk straight through an allowance it had
already spent on retries.

### Caching

A detector whose measurement *is* repetition — caching, determinism — and
one that measures latency always send real requests. Everything else reuses
an answer this scan already has, and the summary line reports how many
requests that saved. A failed exchange is never cached: a rate-limited
reply handed to the next detector is evidence of nothing.

### Does spending less make it wrong?

No — it makes it answer fewer things. Against the ten lab profiles:

| Tier | Facts attempted | Correct | Wrong |
|---|---|---|---|
| `peek` | 10 | 10 | 0 |
| `quick` | 34 | 33 | 1 |
| `standard` | 68 | 62 | 6 |
| `deep` | 72 | 66 | 6 |

A detector that was never run is counted separately from one that ran and
abstained. Scoring silence as agreement would be free marks: `bool(None) ==
bool(False)` credits a level-gated detector with knowing there is no router.

---

---

## Flags

```
-u, --url URL              chat endpoint
-H, --header 'K: V'        extra header (repeatable)
--auth-bearer TOKEN        shorthand for Authorization: Bearer
--cookie VALUE             Cookie header
--insecure                 do not verify TLS certificates

--spend TIER               peek|quick|standard|deep|max (default standard)
--level 1-5                detection depth; overrides the tier
--budget N                 hard request ceiling; overrides the tier
--tokens N                 hard token ceiling
--delay SEC                pause between requests (default 0.5)
--timeout SEC              per-request timeout (default 90)
--only / --skip MOD        run or exclude modules, e.g. --only retrieval
--list-modules             show the module table and exit

--topic / --second-topic   supply probe values instead of discovering them
--absent-topic             a subject known NOT to be in the corpus
--rare-token               a rare literal known to be in the corpus
--seed-queries FILE        discovery queries, one per line
--shape / --query-field    force the request format

-o DIR                     results directory (default ragmap-<timestamp>)
-oJ FILE / -oN FILE        JSON and text reports at a chosen path
--no-out-dir               write nothing to disk
--dump-chunks              print retrieved passages in full
--max-chunk-chars N        terminal truncation width (default 200)
--no-color  -v  --version
--replay DIR               re-analyse a previous scan, sending nothing
```

Exit code is **1** when findings were produced, **0** when none, **2** on
interrupt. A scan that fails to run returns non-zero with the reason on
stderr.

On a slow local model, raise `--timeout`: the default 90 s is not enough
for a 3B model on CPU writing a long answer, and a timeout is recorded as a
failed exchange.

---

## Output

Every scan writes a directory:

```
ragmap-20261117-224103/
├── ragmap.txt      the report, as printed, without colour
├── ragmap.json     facts, findings, full passage text, module outcomes
└── raw/            every request and response, one file each
```

Terminal output truncates passages; the JSON always holds them in full.

`raw/` is there so analysis can be re-run offline after a detector is
improved, **without touching the client's system again**:

```bash
ragmap --replay ragmap-20261117-224103
```

That is not a convenience feature. Three defects in this scanner were found
by a live run, fixed, and verified against the recording at zero further
cost to the target — which is what you want when the target belongs to
someone who gave you a one-week window.

The recordings contain retrieved passages. That is client data; handle the
output directory under the engagement's retention rules. `.gitignore`
excludes scan directories for the same reason.

---

## How it works

### It derives its own probes

Measuring retrieval needs a topic that is in the corpus, a topic that is
not, and a rare literal that appears once. In a lab you know these because
you loaded the documents. In an engagement the corpus belongs to the
client, you have never seen it, and you cannot upload your own — that is a
write, and writes are out of scope for reconnaissance.

So ragmap derives them from the target. It asks what the system covers,
mines candidates from the answers, the source labels and any passages
already returned, then **puts every candidate back to the target and keeps
the ones that measurably retrieve**. A scanner that ships a fixed query
list picks both the present and the absent topic wrong whenever the
target's domain differs from the author's assumptions, and every
measurement downstream inherits that error.

`--topic`, `--absent-topic` and `--rare-token` skip discovery when you
already know them. That is the cheaper scan, not the better one.

### It finds sources structurally

Retrieved passages are located by the *shape* of the response, not by a
list of blessed field names. A scanner that only knows `sources`, `context`
and `documents` goes blind on Dify (`metadata.retriever_resources`) and on
any OpenAI-compatible wrapper that calls them `citations`.

The flip side matters too: the OpenAI envelope itself (`choices`) looks
exactly like a passage list, and treating it as one makes every opaque
system read as fully transparent. ragmap excludes answer envelopes and
discards any "passage" that is simply the reply.

### It will not guess

Each detector declares what it needs. If the precondition is unmet the
detector does not run, and its fact is reported as `not applicable` with
the reason. An operator must be able to tell "no overlap" from "overlap was
never measurable".

Where a figure can only be bounded, it is printed as a bound (`>= 897
chars`), never as a value. Separator-aware splitters such as LangChain's
`RecursiveCharacterTextSplitter` treat the configured chunk size as a
*ceiling* and cut on paragraph boundaries below it, so the widest passage
observed is a lower bound on the setting and nothing visible from outside
can prove the exact number. Printing the round number would be a guess
dressed as a measurement.

### Its confidence is measured, not asserted

The bracketed `cal 4/4, MAE 0` is not a hand-written label. It is that
detector's score against the lab, shipped in `ragmap/data/calibration.json`.
See [Calibration](#calibration).

---

## Observability levels

Everything downstream depends on how much the system says about its own
retrieval, so that is classified first:

| Level | Visible |
|---|---|
| O3 | passage text, similarity score, source count |
| O2 | source identifiers and count, no passage text |
| O1 | sources named only inside the answer prose |
| O0 | answer text only |

O0 is not a security control. The `o0_opaque` lab profile exists to make
that concrete: it returns no sources at all and still gives up chunk text
through the answer, and its token counter still leaks context size.

---

## Calibration

```bash
python lab/mockrag/server.py --port 8099
```

```bash
python lab/mockrag/calibrate.py --level 4
```

Every lab profile declares its true chunk size, overlap, top-k, threshold,
mode and observability level. The scanner is run against each, the output is
compared with the truth, and the result is written to
[docs/calibration-report.md](docs/calibration-report.md) and to
`ragmap/data/calibration.json`.

Current scores, conditioned on what each target exposes:

| detector | hits | correct abstentions | silent failures | MAE |
|---|---|---|---|---|
| `obs.level` | 10/10 | 0 | 0 | - |
| `routing.cache` | 10/10 | 0 | 0 | - |
| `generation.determinism` | 10/10 | 0 | 0 | - |
| `routing.router` | 9/10 | 0 | 0 | - |
| `retrieval.top_k` | 7/7 | 3 | 0 | 0 |
| `retrieval.threshold` | 7/7 | 3 | 0 | - |
| `retrieval.mode` | 5/5 | 5 | 0 | - |
| `chunk.overlap` | 4/4 | 6 | 0 | 0 |
| `chunk.size` | 4/9 | 1 | 5 | 0 |

Read the last row as the honest result it is: chunk width is measured
exactly when passages are visible, and recovering it through verbatim
extraction alone is unreliable. The limitation is published rather than
hidden behind a confidence label.

`routing.router` scores 9/10 because the lab's in-memory search is too fast
to produce a latency signal on one profile. That is a limit of the rig, and
it is reported as one rather than tuned away.

---

## Writing a detector

Drop a class into `ragmap/modules/` and decorate it with `@register`:

```python
@register
class TopK(Module):
    name = "retrieval.topk"
    section = "retrieval"
    level = 2
    requires = ("obs.source_field", "corpus.topic")
    provides = ("retrieval.top_k",)
    cost = 6        # requests it may spend; a ceiling, not an estimate
    value = 10      # what a reader learns from it, 1-10

    def run(self, ctx): ...
```

The engine orders modules from the dependency graph, filters by level, buys
what the budget affords in order of value per request, and emits
placeholder facts for anything it had to skip. `cost` is a ceiling the
module must stay within: the planner bought it at that price and the rest
of the scan is counting on the change.

Three rules the engine enforces:

1. **Dependencies are declared, not assumed.** A module names the facts it
   needs and the facts it produces; order comes from that graph.
2. **A module that cannot run says so.** Unmet precondition means the facts
   are emitted as `not-applicable` with a reason. Nothing disappears
   quietly.
3. **Writes need permission.** `mutating = True` modules refuse to run
   without explicit authorisation. Every module shipped today is read-only.

There is a fourth rule that is easy to get wrong. A zero-cost detector that
takes an *inventory* — what documents were named, what token counters
appeared — can set `resettle = True` and run again at the end of the scan,
over everything that came back. A detector that makes a *graded judgement*
from a heuristic must not: given forty exchanges instead of six,
`observability.level` started reading prose in error-probe replies as
source attribution and promoted O0 targets to O1. More evidence made it
noisier, not better. `tests/test_plan.py` enforces the distinction.

Then re-measure what you wrote:

```bash
python lab/mockrag/calibrate.py --only o3_full
```

---

## Scope and authorisation

**Only scan systems you are authorised to test.**

ragmap sends queries and reads responses. It does not write documents,
poison a corpus, or attempt exploitation. Modules that would write set
`mutating = True` and refuse to run without explicit authorisation; every
module shipped today is read-only.

It keeps short evidence excerpts for the findings it reports, and those
excerpts are client data.

The request budget is a real ceiling, not a suggestion. Raise it
deliberately — on a metered target it is someone else's money, and on an
unmetered one it is someone else's service.

---

MIT. See [LICENSE](LICENSE).
