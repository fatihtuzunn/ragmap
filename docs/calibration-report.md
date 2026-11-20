# ragmap calibration report

Generated 2026-11-20T16:07:22+00:00 at `--level 4`.

Each target declares its true configuration. The table measures the
scanner, not the targets.

| detector | hits | correct abstentions | silent failures | not run | MAE |
|---|---|---|---|---|---|
| `chunk.collisions` | 7/7 | 3 | 0 | 0 | - |
| `chunk.id_scheme` | 7/7 | 3 | 0 | 0 | - |
| `chunk.overlap` | 4/4 | 6 | 0 | 0 | 0.25 |
| `chunk.size` | 7/9 | 1 | 2 | 0 | 2.43 |
| `chunk.splitter` | 4/4 | 6 | 0 | 0 | - |
| `generation.determinism` | 10/10 | 0 | 0 | 0 | - |
| `obs.level` | 10/10 | 0 | 0 | 0 | - |
| `retrieval.mode` | 5/5 | 5 | 0 | 0 | - |
| `retrieval.threshold` | 7/7 | 3 | 0 | 0 | - |
| `retrieval.top_k` | 7/7 | 3 | 0 | 0 | 0.00 |
| `routing.cache` | 10/10 | 0 | 0 | 0 | - |
| `routing.router` | 9/10 | 0 | 1 | 0 | - |

## Per target

### o0_opaque  (openai, O0, 42 requests)

| fact | expected | measured | |
|---|---|---|---|
| `obs.level` | O0 | O0 | ok |
| `chunk.size` | 1000 | not-applicable | **miss** |
| `routing.router` | False | not detected | ok |
| `routing.cache` | False | not detected | ok |
| `generation.determinism` | True | deterministic | ok |

### o0_hardened  (openai, O0, 43 requests)

| fact | expected | measured | |
|---|---|---|---|
| `obs.level` | O0 | O0 | ok |
| `routing.router` | False | not detected | ok |
| `routing.cache` | False | not detected | ok |
| `generation.determinism` | True | deterministic | ok |

### o1_narrative  (openai, O1, 42 requests)

| fact | expected | measured | |
|---|---|---|---|
| `obs.level` | O1 | O1 | ok |
| `chunk.size` | 1000 | not-applicable | **miss** |
| `routing.router` | False | not detected | ok |
| `routing.cache` | False | not detected | ok |
| `generation.determinism` | True | deterministic | ok |

### o2_structured  (openai, O2, 43 requests)

| fact | expected | measured | |
|---|---|---|---|
| `obs.level` | O2 | O2 | ok |
| `retrieval.top_k` | 4 | 4 (fixed) | ok |
| `chunk.size` | 1000 | >= 995 chars | ok |
| `retrieval.threshold` | none | none | ok |
| `routing.router` | False | none | ok |
| `routing.cache` | False | not detected | ok |
| `generation.determinism` | True | deterministic | ok |
| `chunk.id_scheme` | per document | per document, 0-based | ok |
| `chunk.collisions` | 0 | none | ok |

### o3_full  (openai, O3, 42 requests)

| fact | expected | measured | |
|---|---|---|---|
| `obs.level` | O3 | O3 | ok |
| `retrieval.top_k` | 5 | 5 (fixed) | ok |
| `chunk.size` | 1000 | 1000 chars | ok |
| `chunk.overlap` | 200 | 200 chars | ok |
| `retrieval.threshold` | none | none | ok |
| `retrieval.mode` | dense | dense | ok |
| `routing.router` | False | none | ok |
| `routing.cache` | False | not detected | ok |
| `generation.determinism` | True | deterministic | ok |
| `chunk.splitter` | fixed-width | fixed-width (32/37 cut mid-sentence) | ok |
| `chunk.id_scheme` | per document | per document, 0-based | ok |
| `chunk.collisions` | 0 | none | ok |

### anythingllm_like  (anythingllm, O3, 42 requests)

| fact | expected | measured | |
|---|---|---|---|
| `obs.level` | O3 | O3 | ok |
| `retrieval.top_k` | 4 | 4 (fixed) | ok |
| `chunk.size` | 1000 | >= 998 chars | ok |
| `chunk.overlap` | 20 | >= 19 chars | ok |
| `retrieval.threshold` | none | none | ok |
| `retrieval.mode` | dense | dense | ok |
| `routing.router` | False | none | ok |
| `routing.cache` | False | not detected | ok |
| `generation.determinism` | True | deterministic | ok |
| `chunk.splitter` | separator-aware | separator-aware (0/34 cut mid-sentence) | ok |
| `chunk.id_scheme` | per document | per document, 0-based | ok |
| `chunk.collisions` | 0 | none | ok |

### dify_like  (dify, O3, 42 requests)

| fact | expected | measured | |
|---|---|---|---|
| `obs.level` | O3 | O3 | ok |
| `retrieval.top_k` | 3 | 3 (fixed) | ok |
| `chunk.size` | 800 | 800 chars | ok |
| `chunk.overlap` | 100 | 100 chars | ok |
| `retrieval.threshold` | none | none | ok |
| `retrieval.mode` | dense | dense | ok |
| `routing.router` | False | none | ok |
| `routing.cache` | False | not detected | ok |
| `generation.determinism` | True | deterministic | ok |
| `chunk.splitter` | fixed-width | fixed-width (30/34 cut mid-sentence) | ok |
| `chunk.id_scheme` | per document | per document, 0-based | ok |
| `chunk.collisions` | 0 | none | ok |

### router_threshold  (openai, O2, 43 requests)

| fact | expected | measured | |
|---|---|---|---|
| `obs.level` | O2 | O2 | ok |
| `retrieval.top_k` | <= 4 | 4 (fixed) | ok |
| `chunk.size` | 1000 | >= 995 chars | ok |
| `retrieval.threshold` | applied | applied (cuts at 'nonsense') | ok |
| `retrieval.mode` | dense | dense (lexical untested) | ok |
| `routing.router` | True | not-applicable | **miss** |
| `routing.cache` | False | not detected | ok |
| `generation.determinism` | True | deterministic | ok |
| `chunk.id_scheme` | per document | per document, 0-based | ok |
| `chunk.collisions` | 0 | none | ok |

### cached_hybrid  (openai, O3, 42 requests)

| fact | expected | measured | |
|---|---|---|---|
| `obs.level` | O3 | O3 | ok |
| `retrieval.top_k` | 4 | 4 (fixed) | ok |
| `chunk.size` | 1000 | 1000 chars | ok |
| `chunk.overlap` | 200 | 200 chars | ok |
| `retrieval.threshold` | none | none | ok |
| `retrieval.mode` | hybrid | hybrid (lexical + dense) | ok |
| `routing.router` | False | none | ok |
| `routing.cache` | True | present | ok |
| `generation.determinism` | True | deterministic | ok |
| `chunk.splitter` | fixed-width | fixed-width (30/35 cut mid-sentence) | ok |
| `chunk.id_scheme` | per document | per document, 0-based | ok |
| `chunk.collisions` | 0 | none | ok |

### verbose_errors  (openai, O2, 43 requests)

| fact | expected | measured | |
|---|---|---|---|
| `obs.level` | O2 | O2 | ok |
| `retrieval.top_k` | 4 | 4 (fixed) | ok |
| `chunk.size` | 1000 | >= 995 chars | ok |
| `retrieval.threshold` | none | none | ok |
| `routing.router` | False | none | ok |
| `routing.cache` | False | not detected | ok |
| `generation.determinism` | True | deterministic | ok |
| `chunk.id_scheme` | per document | per document, 0-based | ok |
| `chunk.collisions` | 0 | none | ok |
