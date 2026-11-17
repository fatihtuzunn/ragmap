# ragmap calibration report

Generated 2026-11-17T17:19:22+00:00 at `--level 4`.

Each target declares its true configuration. The table measures the
scanner, not the targets.

| detector | hits | correct abstentions | silent failures | not run | MAE |
|---|---|---|---|---|---|
| `chunk.overlap` | 4/4 | 6 | 0 | 0 | 0.00 |
| `chunk.size` | 4/9 | 1 | 5 | 0 | 0.00 |
| `generation.determinism` | 10/10 | 0 | 0 | 0 | - |
| `obs.level` | 10/10 | 0 | 0 | 0 | - |
| `retrieval.mode` | 5/5 | 5 | 0 | 0 | - |
| `retrieval.threshold` | 7/7 | 3 | 0 | 0 | - |
| `retrieval.top_k` | 7/7 | 3 | 0 | 0 | 0.00 |
| `routing.cache` | 10/10 | 0 | 0 | 0 | - |
| `routing.router` | 9/10 | 0 | 0 | 0 | - |

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
| `chunk.size` | 1000 | not-applicable | **miss** |
| `retrieval.threshold` | none | none | ok |
| `routing.router` | False | none | ok |
| `routing.cache` | False | not detected | ok |
| `generation.determinism` | True | deterministic | ok |

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

### anythingllm_like  (anythingllm, O3, 42 requests)

| fact | expected | measured | |
|---|---|---|---|
| `obs.level` | O3 | O3 | ok |
| `retrieval.top_k` | 4 | 4 (fixed) | ok |
| `chunk.size` | 1000 | 1000 chars | ok |
| `chunk.overlap` | 20 | 20 chars | ok |
| `retrieval.threshold` | none | none | ok |
| `retrieval.mode` | dense | dense | ok |
| `routing.router` | False | none | ok |
| `routing.cache` | False | not detected | ok |
| `generation.determinism` | True | deterministic | ok |

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

### router_threshold  (openai, O2, 43 requests)

| fact | expected | measured | |
|---|---|---|---|
| `obs.level` | O2 | O2 | ok |
| `retrieval.top_k` | <= 4 | 1 (varies [1, 2, 3]) | ok |
| `chunk.size` | 1000 | not-applicable | **miss** |
| `retrieval.threshold` | applied | applied (cuts at 'nonsense') | ok |
| `retrieval.mode` | dense | dense (lexical untested) | ok |
| `routing.router` | True | not detected | **miss** |
| `routing.cache` | False | not detected | ok |
| `generation.determinism` | True | deterministic | ok |

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

### verbose_errors  (openai, O2, 43 requests)

| fact | expected | measured | |
|---|---|---|---|
| `obs.level` | O2 | O2 | ok |
| `retrieval.top_k` | 4 | 4 (fixed) | ok |
| `chunk.size` | 1000 | not-applicable | **miss** |
| `retrieval.threshold` | none | none | ok |
| `routing.router` | False | none | ok |
| `routing.cache` | False | not detected | ok |
| `generation.determinism` | True | deterministic | ok |
