# Scanning a live third-party RAG

*A walkthrough you can reproduce end to end. Everything runs on your own
machine; no cloud API key, no rate limit, no daily allowance.*

The lab in [LAB.md](LAB.md) proves the detectors against a target this
project wrote. This proves them against one it did not: **AnythingLLM**, an
off-the-shelf open-source RAG product, backed by a **local Ollama model**,
configured away from its defaults so a correct reading cannot be a lucky
guess.

You will need Docker Desktop, [Ollama](https://ollama.com), and about 3 GB
of disk for the model.

---

## 0. One-time setup

### 0.1 The target

```bash
mkdir -p "$HOME/Documents/anythingllm" && touch "$HOME/Documents/anythingllm/.env"

docker run -d --name anythingllm-ragmap -p 3001:3001 --cap-add SYS_ADMIN \
  -e STORAGE_DIR=/app/server/storage \
  -v "$HOME/Documents/anythingllm:/app/server/storage" \
  -v "$HOME/Documents/anythingllm/.env:/app/server/.env" \
  mintplexlabs/anythingllm:latest
```

Open <http://127.0.0.1:3001>, finish the first-run wizard, and mint an API
key from Settings -> API Keys:

```bash
export ANYTHINGLLM_KEY=...        # PowerShell: $env:ANYTHINGLLM_KEY="..."
```

**Set the splitter before you upload anything.** Chunk size and overlap are
applied at embedding time, so changing them later leaves the existing
vectors at whatever they were built with:

```bash
curl -s -X POST "http://127.0.0.1:3001/api/admin/system-preferences" \
  -H "Authorization: Bearer $ANYTHINGLLM_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"text_splitter_chunk_size":900,"text_splitter_chunk_overlap":150}'
```

Now create a workspace called `meridian-harbor-policies` and upload the
five documents from `lab/corpus/` into it. They are fictional policies for
a made-up logistics company, written so that the facts a scan looks for -
an in-corpus topic, an off-corpus topic, a literal occurring exactly once -
are known in advance. `lab/corpus/MANIFEST.md` lists them.

### 0.2 The model

Ollama runs as a background service on `127.0.0.1:11434`.

```bash
ollama pull llama3.2:3b
ollama list
```

~2.0 GB. A 3B model is enough: ragmap measures *retrieval*, and the
generator only has to produce a coherent answer from the passages it is
handed. On CPU, expect 35-60 s per retrieving query.

**No network change is needed.** Docker Desktop's `host.docker.internal` proxy
reaches Ollama on loopback already - you do **not** need to set
`OLLAMA_HOST=0.0.0.0`, and you should not: that would publish an
unauthenticated model API to your LAN and VPN. Verify the container can see it:

```bash
docker exec anythingllm-ragmap node -e "require('http').get({host:'host.docker.internal',port:11434,path:'/api/tags'},r=>{let d='';r.on('data',c=>d+=c);r.on('end',()=>console.log(r.statusCode,d.slice(0,80)))})"
```

Expect `200 {"models":[{"name":"llama3.2:3b"...`.

### 0.3 Point AnythingLLM at it

```bash
curl -s -X POST "http://127.0.0.1:3001/api/system/update-env" \
  -H "Authorization: Bearer $ANYTHINGLLM_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"LLMProvider":"ollama","OllamaLLMBasePath":"http://host.docker.internal:11434","OllamaLLMModelPref":"llama3.2:3b","OllamaLLMTokenLimit":8192}'
```

It must answer with the keys echoed back in `newValues`. If `newValues` is `{}`
the settings were silently dropped - check the key spellings, they are
case-sensitive. Note this is `/api/system/update-env`, **not**
`/api/admin/system-preferences`: that one takes the splitter settings and
returns `success: true` for LLM keys without writing them.

Confirm:

```bash
docker exec anythingllm-ragmap sh -c "grep -iE 'llm_provider|ollama|embedding' /app/server/.env"
```

The embedder stays `native` (Xenova MiniLM) and the store stays LanceDB, so the
corpus does **not** need re-embedding and the ground truth below still holds.

---

## 1. Health check

```bash
curl -s -X POST "http://127.0.0.1:3001/api/v1/workspace/meridian-harbor-policies/chat" \
  -H "Authorization: Bearer $ANYTHINGLLM_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"message":"What does the document say about remote working?","mode":"query"}'
```

You should get `textResponse`, four entries under `sources`, and a `metrics`
object with `prompt_tokens`. The first call takes ~40 s while the model loads
into RAM; after that a retrieving query is 35-60 s on CPU.

A query that retrieves **nothing** returns in well under a second: AnythingLLM
short-circuits with *"There is no relevant information in this workspace"* and
never calls the model. This is why a scan is much faster than
`requests x 40 s` - roughly half the probes are deliberately off-corpus.

---

## 2. Ground truth

The workspace settings go the same way - deliberately away from
AnythingLLM's defaults, so that a correct reading cannot be a lucky guess:

```bash
curl -s -X POST "http://127.0.0.1:3001/api/v1/workspace/meridian-harbor-policies/update" \
  -H "Authorization: Bearer $ANYTHINGLLM_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"topN":4,"similarityThreshold":0.25,"openAiHistory":0,"chatMode":"query"}'
```

Default top-k is 4 as well, but the default threshold is none and the
default chat mode is `chat`; setting them explicitly means the scan has
something to find rather than something to assume. Verify any of it
yourself:

```bash
curl -s "http://127.0.0.1:3001/api/v1/workspace/meridian-harbor-policies" \
  -H "Authorization: Bearer $ANYTHINGLLM_KEY"

curl -s "http://127.0.0.1:3001/api/admin/system-preferences-for?labels=text_splitter_chunk_size" \
  -H "Authorization: Bearer $ANYTHINGLLM_KEY"
```

| Setting | Value | Where it lives |
|---|---|---|
| chunk size | 900 chars | `text_splitter_chunk_size` |
| chunk overlap | 150 chars | `text_splitter_chunk_overlap` |
| top-k | 4 | workspace `topN` |
| similarity threshold | 0.25 | workspace `similarityThreshold` |
| retrieval | dense only, no reranker | LanceDB + MiniLM |
| chat history | 0 turns | workspace `openAiHistory` |
| documents | 5 | workspace `documents` |
| chat mode | `query` (refuses off-corpus) | workspace `chatMode` |

---

## 3. Run the scan

```bash
ragmap -u "http://127.0.0.1:3001/api/v1/workspace/meridian-harbor-policies/chat" \
  --auth-bearer "$ANYTHINGLLM_KEY" \
  --spend quick --delay 0 --timeout 300 -o scan-mine
```

**Why these flags on a laptop:**

- `--spend quick` - 35-request ceiling, level 2. About ten minutes here. It buys
  observability, corpus topics, top-k and the threshold. `--spend peek` is 4
  requests and under a minute if you only want the interface fingerprint;
  `--spend standard` adds chunk size and the verbatim-leak check for roughly
  double the time.
- `--delay 0` - Ollama serialises requests anyway and there is no rate limit to
  respect. The delay exists for metered cloud targets.
- `--timeout 300` - the default 90 s is not enough. A long answer on CPU can
  take a minute, and a timeout would be recorded as a failed exchange.

Watch it live, or background it and read `scan-mine/ragmap.txt` afterwards.
The run takes about ten minutes on a laptop CPU and sends 32 requests.

A finished scan of exactly this setup ships with the tool, so you can see
what to expect before spending the time:

```
examples/anythingllm-ollama/
├── ragmap.txt           the report, as the live scan printed it
├── ragmap.json          the same facts, plus every passage in full
├── replay-0.2.0.txt     the same exchanges, re-read by the current build
└── raw/                 all 32 exchanges, request and response
```

Those two reports are worth putting side by side. The live scan was run by
an older build; `replay-0.2.0.txt` is what the current detectors make of
the *same* recordings - splitter family, chunk ids, token geometry, four
facts that did not exist when the scan was taken. Nothing was sent to the
target to get them.

```bash
ragmap --replay examples/anythingllm-ollama     # re-analyse it, sends nothing
```

---

## 4. What to compare

Put the scan output next to the table in step 2.

| ragmap says | Expected | Reading it |
|---|---|---|
| `observability O3` | O3 | passage text **and** scores come back |
| `top-k 4 (fixed)` | 4 | exact |
| `threshold applied` | 0.25 | ragmap reports *that* one is applied, not its value - see below |
| `documents 5 visible ids` | 5 | the five policy files |
| `token counter metrics.prompt_tokens` | exposed | Ollama reports usage, so ragmap meters itself on real counts |
| `source field sources` | - | structural detection, no AnythingLLM-specific rule |
| `router not applicable` | no router | a correct abstention, not a failure |
| `splitter separator-aware` | RecursiveCharacterTextSplitter | 0 of 18 passages cut mid-sentence |
| `id scheme opaque` | uuid chunk ids | random ids carry no order, so coverage is declined |
| `chunk tokens median 195` | - | the unit the splitter is configured in |

### Why chunk size comes back as `>= 897` and not `900`

At `--spend standard` you also get chunk size, and at `--spend deep` the
overlap. Chunk size comes back as a **bound**: `>= 897` against a true 900.
That is correct and deliberate.

AnythingLLM uses LangChain's `RecursiveCharacterTextSplitter`, which splits
on paragraph and sentence boundaries first and only falls back to a hard
cut. The configured 900 and 150 are **ceilings**, not widths. Most chunks
land well below them, so the widest passage observed is a lower bound on
the setting, and nothing seen from outside can prove the exact number.
Printing `900` would be a guess dressed as a measurement. `>= 897` is what
the evidence supports, and it is three characters from the truth.

Overlap is harder and the report is blunter about it. It is recovered as
the longest literal suffix/prefix match between consecutive passages from
the same document, which on this target measures **32 characters against a
configured 150**. That is not a near miss, it is a different quantity: a
separator-aware splitter overlaps by *whole units of text* and the literal
repeated run between two passages is whatever happens to be shared, which
can be far below the configured ceiling. Take it as a floor on the overlap,
not as the setting.

You can see this for yourself without scanning anything:

```bash
python tests/check_geometry.py examples/anythingllm-ollama/ragmap.json
```

### Why the threshold has no number

Scores come back as `score` and `_distance` where `score = 1 - _distance`.
ragmap can see *that* low-scoring passages are being cut, by walking a relevance
ladder from on-topic down to nonsense, but the cut-off in the product's own
units is not observable from the outside. So it reports `applied` and names the
rung where the list went empty.

---

## 5. Things to try

Change a setting, rescan, confirm ragmap follows:

```bash
# top-k 4 -> 8
curl -s -X POST "http://127.0.0.1:3001/api/v1/workspace/meridian-harbor-policies/update" \
  -H "Authorization: Bearer $ANYTHINGLLM_KEY" \
  -H 'Content-Type: application/json' -d '{"topN":8}'

# threshold off
curl -s -X POST "http://127.0.0.1:3001/api/v1/workspace/meridian-harbor-policies/update" \
  -H "Authorization: Bearer $ANYTHINGLLM_KEY" \
  -H 'Content-Type: application/json' -d '{"similarityThreshold":0.0}'
```

Then rerun step 3. `top-k` should follow to 8; with the threshold off, the
router detector stops abstaining because the zero-source signal becomes usable
again.

Other useful flags:

```bash
ragmap -u URL --auth-bearer KEY --spend quick --dump-chunks   # full passage text
ragmap -u URL --auth-bearer KEY --spend peek                  # 4 requests, under a minute
ragmap --replay scan-mine                                     # re-analyse offline, sends nothing
ragmap --list-modules                                         # cost and value of each detector
```

`--replay` is worth knowing: it re-runs every detector over the exchanges
already recorded in `scan-mine/raw/`. A detector fixed after an engagement can
be re-run against the client's data without touching the client's system again.

---

## 6. If something looks wrong

**Everything reports `not applicable` / the scan ends in seconds** - the
model is not loaded or AnythingLLM cannot reach Ollama. Rerun the health
check in step 1 and the `docker exec` check in 0.2.

**`no candidate request shape produced an answer`** - the URL or the key is
wrong. Run the step 1 curl; if that fails, ragmap will too.

**`timeout` errors in the exchange log** - raise `--timeout`. A 3B model on CPU
writing a 2,400-character answer can take over a minute.

**`413 Request too large`** - AnythingLLM prepends workspace chat history to
every prompt, so a long scan inflates its own requests. History is already off
(`openAiHistory: 0`); if it came back on, turn it off and clear what is there:

```bash
curl -s -X POST "http://127.0.0.1:3001/api/v1/workspace/meridian-harbor-policies/update" \
  -H "Authorization: Bearer $ANYTHINGLLM_KEY" \
  -H 'Content-Type: application/json' -d '{"openAiHistory":0}'

curl -s -X DELETE "http://127.0.0.1:3001/api/v1/workspace/meridian-harbor-policies/chats" \
  -H "Authorization: Bearer $ANYTHINGLLM_KEY"
```

**The machine grinds** - `--spend peek` first, then `quick`. Each tier prints
what it could not afford and what it would cost.

### Going back to a cloud model

```bash
curl -s -X POST "http://127.0.0.1:3001/api/system/update-env" \
  -H "Authorization: Bearer $ANYTHINGLLM_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"LLMProvider":"groq","GroqApiKey":"<key>","GroqModelPref":"openai/gpt-oss-20b"}'
```

Then `--delay 16` is mandatory and `--tokens <what you can afford>` is strongly
advised: Groq's free tier is **200,000 tokens per day**, about 160 exchanges
against this workspace, shared across every scan you run that day. ragmap stops
and says so when a daily allowance runs out, because waiting cannot buy one
back.

---

## 7. Scope

ragmap sends queries and reads responses. It does not write documents,
poison a corpus, or attempt exploitation. Modules that would write set
`mutating = True` and refuse to run without explicit authorisation; every
module shipped today is read-only.

Only scan systems you are authorised to test.
