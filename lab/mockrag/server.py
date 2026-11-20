#!/usr/bin/env python3
"""
mockrag - a configurable RAG target for calibrating ragmap.

WHAT IT IS FOR
--------------
Before trusting ragmap against a real deployment you have to know it reads
a real deployment correctly: does it call an O3 system O3? Does it see a
fixed top-k as fixed? With no threshold configured, does it find source
fields populated all the way down a relevance ladder?

Against a real deployment you cannot answer that, because the ground truth
is only as good as what an admin screen happens to show you. Here the
ground truth is IN THE CODE: chunk size, overlap, top-k, threshold and
observability level are all values you set. This is not a target. It is a
calibration rig.

One server serves different profiles, selected by a single URL parameter:

    http://127.0.0.1:8099/v1/chat/completions?profile=o0_opaque
    http://127.0.0.1:8099/v1/chat/completions?profile=o3_full
    http://127.0.0.1:8099/api/v1/workspace/ragmap-test/chat?profile=anythingllm_like
    http://127.0.0.1:8099/v1/chat-messages?profile=dify_like

The profiles live in mockrag/profiles.json. Editing one needs no code
change: the file is re-read on every request.

THE GENERATION LAYER
--------------------
Groq (an OpenAI-compatible API) by default. With no GROQ_API_KEY the
server falls back to a "mock" generator that assembles an answer from the
retrieved chunks with a template. Retrieval, chunking, scoring and
response shape are real even in mock mode, so calibration works without
an API key.

AN HONEST LIMITATION
--------------------
The embedding layer is TF-IDF, not a real dense encoder. The "dense" mode
IMITATES a dense retriever's exact-match blindness by dropping rare
literals (df <= 1) from the query representation. That is there so the
lexical-versus-dense signal can be tested; it is not a measurement of any
real embedding model. To fit a real encoder, replace the vectorisation
inside search().

USAGE
-----
    python mockrag/server.py                       # 8099, default profile
    python mockrag/server.py --port 8099 --profile o2_structured
    python mockrag/server.py --list-profiles

HELPER ENDPOINTS
----------------
    GET /healthz          is the server up
    GET /__ground_truth   the active profile's FULL ground truth (JSON)
    GET /__corpus         loaded documents and chunk counts
    GET /__profiles       profile names
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import threading
import time
import traceback
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import requests
except ImportError:
    sys.exit("requests is not installed:  pip install requests")


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CORPUS_DIR = ROOT / "corpus"
PROFILES_PATH = HERE / "profiles.json"

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"


# ==========================================================================
# Corpus, chunking, retrieval
# ==========================================================================

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]*")

# Function words, dropped on the query side only. They stay in the chunk
# index so document frequencies are not distorted; they are removed from
# the query representation and from the rare-term bonus. A word like
# "what" appearing once in the corpus does not make it a rare IDENTIFIER.
STOPWORDS = {
    "a", "about", "all", "an", "and", "any", "are", "as", "at", "be", "been",
    "but", "by", "can", "did", "do", "does", "for", "from", "give", "given",
    "has", "have", "how", "i", "if", "in", "is", "it", "its", "list", "me",
    "much", "no", "not", "of", "on", "or", "our", "say", "says", "tell", "that",
    "the", "their", "them", "there", "these", "they", "this", "to", "us", "was",
    "we", "were", "what", "when", "where", "which", "who", "why", "will",
    "with", "would", "you", "your",
}


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def content_tokens(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


# Character 3-gram layer. In a real dense encoder EVERY query lands
# somewhere in vector space and its k nearest neighbours come back even
# when not one of its words matches. Pure TF-IDF does not do that - no
# match, empty result - and that difference would destroy the whole point
# of the nonsense-string probe. So a small-weighted character similarity
# is mixed into the score: nonsense input scores low but NON-ZERO, which
# means an unthresholded target still returns a full top-k.
TRIGRAM_WEIGHT = 0.15
_WS_RE = re.compile(r"\s+")


def trigram_vector(text: str) -> dict[str, float]:
    flat = _WS_RE.sub(" ", text.lower())
    counts = Counter(flat[i:i + 3] for i in range(max(0, len(flat) - 2)))
    norm = math.sqrt(sum(v * v for v in counts.values())) or 1.0
    return {k: v / norm for k, v in counts.items()}


def sparse_dot(a: dict, b: dict) -> float:
    if len(a) > len(b):
        a, b = b, a
    total = 0.0
    for key, value in a.items():
        other = b.get(key)
        if other:
            total += value * other
    return total


def chunk_text(text: str, size: int, overlap: int,
               splitter: str = "fixed") -> list[tuple[int, str]]:
    """Cut a document into passages, one of two ways.

    ``fixed``     a character sliding window. Every chunk is exactly
                  ``size`` wide except the last, and the cuts land wherever
                  they land - usually mid-sentence.

    ``recursive`` what LangChain's RecursiveCharacterTextSplitter does, and
                  with it AnythingLLM and most LlamaIndex pipelines: prefer
                  a paragraph break, then a sentence end, then a space, and
                  only cut mid-word when nothing else fits. ``size`` is a
                  CEILING here, not a width, which is why a scanner can only
                  bound it from outside.

    The two differ in exactly the way a chunk-quality detector claims to
    see, which is the point of having both.
    """
    if overlap >= size:
        raise ValueError("overlap must be smaller than chunk_size")
    if splitter == "recursive":
        return _chunk_recursive(text, size, overlap)

    step = size - overlap
    out = []
    start = 0
    while start < len(text):
        piece = text[start:start + size]
        if piece.strip():
            out.append((start, piece))
        if start + size >= len(text):
            break
        start += step
    return out


# Tried in order, best boundary first. A cut is taken at the last one that
# falls inside the window and leaves at least half a chunk behind.
#
# Sentence ends come before a single newline on purpose. LangChain's
# default order puts "\n" second, which is right for prose that is not
# hard-wrapped and wrong for anything that is - and this corpus is
# wrapped at about 83 columns, as plenty of real documentation is.
# Taking every wrapped line as a boundary would cut mid-sentence
# constantly and make this mode indistinguishable from the fixed one,
# which would defeat the reason it exists.
_SEPARATORS = ("\n\n", ". ", "? ", "! ", "; ", "\n", " ")


def _chunk_recursive(text: str, size: int, overlap: int) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    start = 0
    length = len(text)

    while start < length:
        end = min(start + size, length)
        if end < length:
            floor = start + size // 2
            for separator in _SEPARATORS:
                found = text.rfind(separator, floor, end)
                if found > 0:
                    end = found + len(separator)
                    break
        piece = text[start:end]
        if piece.strip():
            out.append((start, piece))
        if end >= length:
            break
        # Step back by the overlap, then forward to the next word boundary
        # so the overlap itself does not start mid-word.
        nxt = max(start + 1, end - overlap)
        space = text.find(" ", nxt, min(nxt + 40, length))
        start = (space + 1) if space != -1 else nxt
    return out


class Chunk:
    __slots__ = ("doc_id", "title", "filename", "index", "page", "text",
                 "char_start", "vector", "tokens", "trigrams")

    def __init__(self, doc_id, title, filename, index, page, text, char_start):
        self.doc_id = doc_id
        self.title = title
        self.filename = filename
        self.index = index
        self.page = page
        self.text = text
        self.char_start = char_start
        self.vector: dict[str, float] = {}
        self.tokens: Counter = Counter()
        self.trigrams: dict[str, float] = {}

    @property
    def chunk_id(self) -> str:
        return f"{self.doc_id}#c{self.index}"


class Index:
    """A TF-IDF index. No dependencies, deterministic, fast."""

    def __init__(self, corpus_dir: Path, chunk_size: int, chunk_overlap: int,
                 splitter: str = "fixed"):
        self.corpus_dir = corpus_dir
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.splitter = splitter
        self.chunks: list[Chunk] = []
        self.documents: list[dict] = []
        self.df: Counter = Counter()
        self.idf: dict[str, float] = {}
        self._build()

    def _build(self) -> None:
        files = sorted(p for p in self.corpus_dir.glob("*.md")
                       if not p.name.startswith("MANIFEST"))
        if not files:
            raise SystemExit(f"Corpus is empty: {self.corpus_dir}")

        for path in files:
            raw = path.read_text(encoding="utf-8")
            first_line = next((l for l in raw.splitlines() if l.startswith("# ")), path.stem)
            title = first_line.lstrip("# ").strip()
            doc_id = path.stem
            pieces = chunk_text(raw, self.chunk_size, self.chunk_overlap,
                                self.splitter)
            for i, (start, text) in enumerate(pieces):
                # Sayfa numarasi simulasyonu: PDF yukleyen araclarda chunk'lar
                # sayfa etiketi tasir. 3 chunk = 1 sayfa kabul ediyoruz.
                self.chunks.append(Chunk(doc_id, title, path.name, i,
                                         (i // 3) + 1, text, start))
            self.documents.append({
                "doc_id": doc_id,
                "title": title,
                "filename": path.name,
                "chars": len(raw),
                "words": len(raw.split()),
                "chunks": len(pieces),
            })

        for chunk in self.chunks:
            chunk.tokens = Counter(tokenize(chunk.text))
            chunk.trigrams = trigram_vector(chunk.text)
            for term in chunk.tokens:
                self.df[term] += 1

        n = len(self.chunks)
        for term, df in self.df.items():
            self.idf[term] = math.log((n + 1) / (df + 0.5)) + 1.0

        for chunk in self.chunks:
            self._vectorize_into(chunk)

    def _vectorize_into(self, chunk: Chunk) -> None:
        vec = {}
        for term, tf in chunk.tokens.items():
            vec[term] = (1 + math.log(tf)) * self.idf.get(term, 1.0)
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        chunk.vector = {k: v / norm for k, v in vec.items()}

    def _query_vector(self, query: str, mode: str) -> dict[str, float]:
        terms = Counter(content_tokens(query))
        vec = {}
        for term, tf in terms.items():
            df = self.df.get(term, 0)
            if mode == "dense" and df <= 1:
                # Imitating a dense encoder: a literal that occurs almost
                # nowhere in the corpus, and that an encoder would split
                # into sub-words, carries almost no weight in the query
                # representation. No exact match is made.
                continue
            vec[term] = (1 + math.log(tf)) * self.idf.get(term, 1.0)
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {k: v / norm for k, v in vec.items()}

    def search(self, query: str, top_k: int, threshold: float | None,
               mode: str = "dense") -> list[dict]:
        qvec = self._query_vector(query, mode)
        qterms = set(content_tokens(query))
        qtri = trigram_vector(query)

        scored = []
        for chunk in self.chunks:
            score = sparse_dot(qvec, chunk.vector)
            score += TRIGRAM_WEIGHT * sparse_dot(qtri, chunk.trigrams)

            if mode == "hybrid":
                # Sozluksel bonus: nadir terimin tam eslesmesi. BM25'in
                # dense'e kattigi seyin basitlestirilmis hali.
                rare_hits = sum(1 for t in qterms
                                if self.df.get(t, 0) == 1 and t in chunk.tokens)
                score += 0.45 * rare_hits

            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda pair: (-pair[0], pair[1].chunk_id))
        if threshold is not None:
            scored = [pair for pair in scored if pair[0] >= threshold]
        scored = scored[:top_k]

        return [{
            "chunk": chunk,
            "score": round(score, 6),
        } for score, chunk in scored]


# ==========================================================================
# Profiller
# ==========================================================================

DEFAULTS = {
    "observability": "O2",
    "response_shape": "openai",
    "chunk_size": 1000,
    "chunk_overlap": 200,
    "top_k": 4,
    "similarity_threshold": None,
    "retrieval_mode": "dense",
    # fixed = a character sliding window; recursive = cuts on paragraph and
    # sentence boundaries, which makes chunk_size a ceiling.
    "splitter": "fixed",
    "expose_usage": True,
    # expose_scores / expose_chunk_text / expose_identifiers / emit_sources
    # DELIBERATELY absent here: their defaults come from the observability
    # level (LEVEL_PRESETS). Set one explicitly in profiles.json and your
    # value wins.
    "router": False,
    "router_threshold": 0.08,
    "cache": False,
    "verbatim_guard": False,
    "error_verbosity": "quiet",
    "simulated_framework_trace": None,
    "retrieval_latency_ms": 120,
    "router_latency_ms": 10,
    "temperature": 0.0,
    "max_tokens": 900,
    # Reasoning models such as gpt-oss spend most of the completion budget
    # on invisible reasoning tokens. Measured here: at 700 tokens the answer
    # was truncated, at 20 it came back EMPTY. At "low" the reasoning drops
    # from 295 to 25 tokens and the visible answer is byte-identical. A
    # model that does not support the field ignores it.
    "reasoning_effort": "low",
    "model": None,
}


def load_profiles() -> dict:
    data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    out = {}
    for name, overrides in data.items():
        if name.startswith("_"):
            continue
        merged = dict(DEFAULTS)
        merged.update({k: v for k, v in overrides.items() if not k.startswith("_")})
        merged["_name"] = name
        merged["_comment"] = overrides.get("_comment")
        out[name] = merged
    return out


# The observability level decides field visibility. Each field can also be
# set individually in profiles.json; the level only supplies a sane default.
LEVEL_PRESETS = {
    "O0": {"expose_chunk_text": False, "expose_scores": False,
           "expose_identifiers": False, "emit_sources": False},
    "O1": {"expose_chunk_text": False, "expose_scores": False,
           "expose_identifiers": False, "emit_sources": False},
    "O2": {"expose_chunk_text": False, "expose_scores": False,
           "expose_identifiers": True, "emit_sources": True},
    "O3": {"expose_chunk_text": True, "expose_scores": True,
           "expose_identifiers": True, "emit_sources": True},
}


def effective(profile: dict) -> dict:
    """Apply the level defaults; explicit values in the profile win."""
    level = profile.get("observability", "O2").upper()
    preset = dict(LEVEL_PRESETS.get(level, LEVEL_PRESETS["O2"]))
    merged = dict(profile)
    merged.setdefault("emit_sources", preset["emit_sources"])
    for key in ("expose_chunk_text", "expose_scores", "expose_identifiers"):
        if key not in profile or profile[key] is None:
            merged[key] = preset[key]
    if "emit_sources" not in profile:
        merged["emit_sources"] = preset["emit_sources"]
    return merged


# ==========================================================================
# Uretim katmani
# ==========================================================================

SYSTEM_BASE = (
    "You are the internal knowledge assistant for Meridian Harbor Logistics. "
    "Answer using only the context passages provided below. If the context "
    "does not contain the answer, say so plainly."
)

SYSTEM_BY_LEVEL = {
    "O0": (" Never mention document names, file names, section numbers or the "
           "fact that you were given context. Answer as if from your own knowledge."),
    "O1": (" Always attribute each claim in prose, naming the document title it "
           "came from, for example: 'According to the Data Governance and Records "
           "Retention Policy, ...'."),
    "O2": "",
    "O3": "",
}

VERBATIM_GUARD = (
    " Never reproduce source passages word for word. Always paraphrase and keep "
    "quotations under fifteen words."
)


def _mock_title_for(passage: str) -> str:
    """Best-effort document title for an O1-style prose citation."""
    for line in passage.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line.lstrip("# ").strip()
    return "Meridian Harbor Logistics internal policy"


class Generator:
    """Generation through Groq, or a deterministic mock with no API key."""

    def __init__(self, api_key: str | None, model: str | None):
        self.api_key = api_key
        self.model = model
        self.available_models: list[str] = []
        self.backend = "groq" if api_key else "mock"
        if self.api_key:
            self._pick_model()

    # Groq's catalogue changes often, so this list is a preference order,
    # not a guarantee. /models is fetched at startup and the first listed
    # preference is taken. If none is available, the first chat-capable
    # model is used.
    PREFERRED = [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "qwen/qwen3.8-27b",
        "moonshotai/kimi-k2-instruct",
    ]

    def _pick_model(self) -> None:
        try:
            resp = requests.get(
                GROQ_MODELS_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=20,
            )
            resp.raise_for_status()
            ids = [m["id"] for m in resp.json().get("data", [])]
        except Exception as exc:
            print(f"[mockrag] could not fetch the Groq model list ({exc}). "
                  f"Trying '{self.model or self.PREFERRED[0]}'.")
            self.model = self.model or self.PREFERRED[0]
            return

        self.available_models = sorted(ids)
        if self.model and self.model in ids:
            return
        if self.model:
            print(f"[mockrag] WARNING: '{self.model}' is not on Groq. "
                  f"Choosing an alternative.")
        for candidate in self.PREFERRED:
            if candidate in ids:
                self.model = candidate
                return
        chat_like = [i for i in ids
                     if not any(x in i.lower() for x in
                                ("whisper", "guard", "tts", "embed", "vision-preview"))]
        self.model = chat_like[0] if chat_like else (ids[0] if ids else self.PREFERRED[0])

    # ------------------------------------------------------------------
    def complete(self, system: str, user: str, temperature: float,
                 max_tokens: int, reasoning_effort: str | None = None) -> dict:
        if self.backend == "mock":
            return self._mock(system, user)

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort

        # On Groq's free tier the binding limit is TOKENS PER MINUTE
        # (measured: 8000 TPM, 1000 RPD). The scan is paced by the caller's
        # own delay; this is only a safety valve.
        # CAREFUL: waiting here INFLATES the latency the scanner measures.
        # That is why 429 events are recorded, and why those exchanges must
        # be excluded when reading anything off the latency axis.
        attempts = 0
        throttled_ms = 0.0
        while True:
            attempts += 1
            resp = requests.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                json=payload,
                timeout=120,
            )
            if resp.status_code != 429 or attempts > 5:
                break
            wait = float(resp.headers.get("retry-after") or 0) or min(2 ** attempts, 30)
            print(f"[mockrag] 429 - {wait:.1f}s bekleniyor "
                  f"(deneme {attempts}/5)", file=sys.stderr)
            time.sleep(wait)
            throttled_ms += wait * 1000

        if resp.status_code >= 400:
            raise RuntimeError(f"Groq {resp.status_code}: {resp.text[:400]}")

        data = resp.json()
        return {
            "text": data["choices"][0]["message"]["content"],
            "usage": data.get("usage", {}),
            "model": data.get("model", self.model),
            "finish_reason": data["choices"][0].get("finish_reason"),
            "throttled_ms": throttled_ms,
            "rate_limit": {
                "remaining_tokens": resp.headers.get("x-ratelimit-remaining-tokens"),
                "remaining_requests": resp.headers.get("x-ratelimit-remaining-requests"),
            },
        }

    def _mock(self, system: str, user: str) -> dict:
        """
        Anahtarsiz calisma. Cevabi context'ten kurar; boylece P08
        (birebir alinti) mock modda da gercekci davranir: guard kapaliysa
        chunk metni cevaba sizar, acikken sizmaz.
        """
        context_blocks = re.findall(r"\[(\d+)\]\s(.*?)(?=\n\[\d+\]\s|\Z)",
                                    user, flags=re.S)
        question = user.split("Question:")[-1].strip()
        if not context_blocks:
            text = ("I could not find anything in the available documents that "
                    "answers this question.")
        elif "word for word" in question.lower() or "verbatim" in question.lower():
            if VERBATIM_GUARD.strip()[:20] in system:
                text = ("I can only summarise: the passage sets out the relevant "
                        "rule and the conditions under which it applies.")
            else:
                text = ("Here is the passage, reproduced exactly as it appears in "
                        "the source document:\n\n"
                        + context_blocks[0][1].strip())
        else:
            joined = " ".join(b[1].strip().replace("\n", " ")
                              for b in context_blocks[:2])
            text = (f"Based on the retrieved material: {joined[:600].strip()}...")

        # Honour the O1 instruction. Without this the mock generator ignores
        # the system prompt entirely, so the O1 profile behaves exactly like
        # O0 and no narrative-attribution detector can ever be exercised
        # against it. A lab that cannot produce the case under test is not a
        # lab.
        if "Always attribute each claim in prose" in system and context_blocks:
            title = _mock_title_for(context_blocks[0][1])
            text = f"According to the {title}, {text[0].lower()}{text[1:]}"
        prompt_tokens = max(1, len(user) // 4 + len(system) // 4)
        completion_tokens = max(1, len(text) // 4)
        return {
            "text": text,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "model": "mockrag-deterministic",
            "finish_reason": "stop",
        }


# ==========================================================================
# RAG boru hatti
# ==========================================================================

class Engine:
    def __init__(self, generator: Generator):
        self.generator = generator
        self._indexes: dict[tuple[int, int], Index] = {}
        self._cache: dict[str, dict] = {}
        self._lock = threading.Lock()

    def index_for(self, chunk_size: int, overlap: int,
                  splitter: str = "fixed") -> Index:
        key = (chunk_size, overlap, splitter)
        with self._lock:
            if key not in self._indexes:
                self._indexes[key] = Index(CORPUS_DIR, chunk_size, overlap,
                                           splitter)
            return self._indexes[key]

    def answer(self, query: str, profile: dict) -> dict:
        cfg = effective(profile)
        started = time.perf_counter()

        cache_key = hashlib.sha256(
            (cfg["_name"] + "||" + query).encode("utf-8")).hexdigest()
        if cfg["cache"]:
            hit = self._cache.get(cache_key)
            if hit is not None:
                out = dict(hit)
                out["cache_hit"] = True
                out["latency_ms"] = (time.perf_counter() - started) * 1000
                return out

        index = self.index_for(cfg["chunk_size"], cfg["chunk_overlap"],
                               cfg["splitter"])

        retrieved: list[dict] = []
        retrieval_ran = True
        if cfg["router"]:
            time.sleep(cfg["router_latency_ms"] / 1000.0)
            probe = index.search(query, top_k=1, threshold=None,
                                 mode=cfg["retrieval_mode"])
            best = probe[0]["score"] if probe else 0.0
            if best < cfg["router_threshold"]:
                retrieval_ran = False

        if retrieval_ran:
            time.sleep(cfg["retrieval_latency_ms"] / 1000.0)
            retrieved = index.search(
                query,
                top_k=cfg["top_k"],
                threshold=cfg["similarity_threshold"],
                mode=cfg["retrieval_mode"],
            )

        level = cfg["observability"].upper()
        system = SYSTEM_BASE + SYSTEM_BY_LEVEL.get(level, "")
        if cfg["verbatim_guard"]:
            system += VERBATIM_GUARD

        if retrieved:
            blocks = "\n".join(
                f"[{i + 1}] {item['chunk'].text.strip()}"
                for i, item in enumerate(retrieved)
            )
            user = f"Context passages:\n{blocks}\n\nQuestion: {query}"
        else:
            user = f"Context passages:\n(none retrieved)\n\nQuestion: {query}"

        completion = self.generator.complete(
            system, user, cfg["temperature"], cfg["max_tokens"],
            cfg.get("reasoning_effort"))

        result = {
            "text": completion["text"],
            "usage": completion["usage"],
            "model": completion["model"],
            "retrieved": retrieved,
            "retrieval_ran": retrieval_ran,
            "cache_hit": False,
            "latency_ms": (time.perf_counter() - started) * 1000,
            # Time spent waiting on a rate limit. Deliberately NOT put in
            # the response body: adding a field there would pollute the
            # scanner's structural field search. It goes in a header
            # instead, and every response header is recorded anyway.
            "throttled_ms": completion.get("throttled_ms", 0.0),
        }
        if cfg["cache"]:
            self._cache[cache_key] = {k: v for k, v in result.items()
                                      if k != "latency_ms"}
        return result


# ==========================================================================
# Response shapes
# ==========================================================================

def source_items(result: dict, cfg: dict) -> list[dict]:
    """Build the source objects according to the observability settings."""
    items = []
    for rank, item in enumerate(result["retrieved"], start=1):
        chunk = item["chunk"]
        entry: dict = {}
        if cfg["expose_identifiers"]:
            entry.update({
                "id": chunk.chunk_id,
                "document_id": chunk.doc_id,
                "title": chunk.title,
                "filename": chunk.filename,
                "page": chunk.page,
            })
        else:
            entry["id"] = f"src-{rank}"
        if cfg["expose_scores"]:
            entry["score"] = item["score"]
        if cfg["expose_chunk_text"]:
            entry["text"] = chunk.text
        if not entry:
            entry = {"rank": rank}
        items.append(entry)
    return items


def shape_openai(result: dict, cfg: dict, query: str) -> dict:
    body = {
        "id": "chatcmpl-" + hashlib.sha1(query.encode()).hexdigest()[:20],
        "object": "chat.completion",
        "created": int(time.time()),
        "model": result["model"],
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": result["text"]},
            "finish_reason": "stop",
        }],
    }
    if cfg["expose_usage"]:
        body["usage"] = result["usage"]
    if cfg["emit_sources"]:
        body["citations"] = source_items(result, cfg)
    return body


def shape_anythingllm(result: dict, cfg: dict, query: str) -> dict:
    sources = []
    for item in source_items(result, cfg):
        entry = dict(item)
        if "filename" in entry:
            entry["url"] = "file://" + entry["filename"]
        sources.append(entry)
    body = {
        "id": "ws-" + hashlib.sha1(query.encode()).hexdigest()[:16],
        "type": "textResponse",
        "textResponse": result["text"],
        "close": True,
        "error": None,
    }
    if cfg["emit_sources"]:
        body["sources"] = sources
    else:
        body["sources"] = []
    if cfg["expose_usage"]:
        body["metrics"] = {
            "prompt_tokens": result["usage"].get("prompt_tokens"),
            "completion_tokens": result["usage"].get("completion_tokens"),
            "total_tokens": result["usage"].get("total_tokens"),
            "duration": round(result["latency_ms"] / 1000.0, 3),
        }
    return body


def shape_dify(result: dict, cfg: dict, query: str) -> dict:
    """
    Dify's shape. NOTE: the source field is called 'retriever_resources'.
    A scanner carrying a fixed list of blessed field names does not have
    that one, so this profile deliberately tests whether sources are found
    structurally rather than by name.
    """
    resources = []
    for position, item in enumerate(source_items(result, cfg), start=1):
        entry = {"position": position}
        entry.update(item)
        if "text" in entry:
            entry["content"] = entry.pop("text")
        if "filename" in entry:
            entry["document_name"] = entry.pop("filename")
        resources.append(entry)

    metadata: dict = {}
    if cfg["emit_sources"]:
        metadata["retriever_resources"] = resources
    if cfg["expose_usage"]:
        metadata["usage"] = result["usage"]

    return {
        "event": "message",
        "task_id": hashlib.sha1(query.encode()).hexdigest()[:24],
        "message_id": hashlib.sha1((query + "m").encode()).hexdigest()[:24],
        "conversation_id": "conv-ragmap-test",
        "mode": "advanced-chat",
        "answer": result["text"],
        "metadata": metadata,
        "created_at": int(time.time()),
    }


SHAPES = {
    "openai": shape_openai,
    "anythingllm": shape_anythingllm,
    "dify": shape_dify,
}


# ==========================================================================
# HTTP katmani
# ==========================================================================

CHAT_PATHS = (
    "/v1/chat/completions",
    "/api/chat/completions",
    "/chat/completions",
    "/v1/chat-messages",
    "/chat-messages",
)


class Handler(BaseHTTPRequestHandler):
    server_version = "mockrag/1.0"
    sys_version = ""

    engine: Engine
    profiles: dict
    default_profile: str

    # -- yardimcilar ---------------------------------------------------
    def _send(self, status: int, payload, extra_headers: dict | None = None):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _profile_from(self, parsed) -> dict:
        params = parse_qs(parsed.query)
        name = (params.get("profile", [None])[0]
                or self.headers.get("X-RAGmap-Profile")
                or self.default_profile)
        profiles = load_profiles()
        if name not in profiles:
            raise KeyError(name)
        return effective(profiles[name])

    def log_message(self, fmt, *args):
        sys.stderr.write("[mockrag] %s - %s\n" % (self.address_string(), fmt % args))

    # -- GET -----------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            return self._send(200, {"status": "ok",
                                    "backend": self.engine.generator.backend,
                                    "model": self.engine.generator.model})

        if parsed.path == "/__profiles":
            profiles = load_profiles()
            return self._send(200, {
                "default": self.default_profile,
                "profiles": {k: v.get("_comment") for k, v in profiles.items()},
            })

        if parsed.path == "/__corpus":
            index = self.engine.index_for(DEFAULTS["chunk_size"],
                                          DEFAULTS["chunk_overlap"])
            return self._send(200, {
                "corpus_dir": str(CORPUS_DIR),
                "documents": index.documents,
                "total_chunks": len(index.chunks),
                "chunk_size": index.chunk_size,
                "chunk_overlap": index.chunk_overlap,
            })

        if parsed.path == "/__ground_truth":
            try:
                cfg = self._profile_from(parsed)
            except KeyError as exc:
                return self._send(404, {"error": f"unknown profile: {exc.args[0]}"})
            index = self.engine.index_for(cfg["chunk_size"],
                                          cfg["chunk_overlap"],
                                          cfg["splitter"])
            return self._send(200, {
                "profile": cfg["_name"],
                "_comment": cfg.get("_comment"),
                "framework": "mockrag (ragmap calibration rig)",
                "vector_db": "in-memory TF-IDF",
                "embedding_model": "tfidf-local (not a real dense encoder)",
                "llm": self.engine.generator.model,
                "llm_backend": self.engine.generator.backend,
                "observability_declared": cfg["observability"],
                "response_shape": cfg["response_shape"],
                "chunk_size": cfg["chunk_size"],
                "chunk_overlap": cfg["chunk_overlap"],
                "splitter": cfg["splitter"],
                "chunk_id_scheme": "per document",
                "chunk_id_collisions": 0,
                "top_k": cfg["top_k"],
                "similarity_threshold": cfg["similarity_threshold"],
                "retrieval_mode": cfg["retrieval_mode"],
                "reranker": False,
                "router": cfg["router"],
                "cache": cfg["cache"],
                "verbatim_guard": cfg["verbatim_guard"],
                "expose_usage": cfg["expose_usage"],
                "expose_scores": cfg["expose_scores"],
                "expose_chunk_text": cfg["expose_chunk_text"],
                "expose_identifiers": cfg["expose_identifiers"],
                "emit_sources": cfg["emit_sources"],
                "error_verbosity": cfg["error_verbosity"],
                "temperature": cfg["temperature"],
                "max_tokens": cfg["max_tokens"],
                "reasoning_effort": cfg.get("reasoning_effort"),
                "corpus_documents": len(index.documents),
                "corpus_chunks": len(index.chunks),
            })

        return self._send(404, {"error": "bilinmeyen uc", "path": parsed.path})

    # -- POST ----------------------------------------------------------
    def do_POST(self):
        parsed = urlparse(self.path)
        is_chat = (parsed.path in CHAT_PATHS
                   or re.match(r"^/api/v1/workspace/[^/]+/chat$", parsed.path))
        if not is_chat:
            return self._send(404, {"error": "bilinmeyen uc", "path": parsed.path})

        try:
            cfg = self._profile_from(parsed)
        except KeyError as exc:
            return self._send(404, {"error": f"unknown profile: {exc.args[0]}"})

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""

        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
            query = extract_query(body)
            if not query or not query.strip():
                raise ValueError("the message/query field must not be empty")
        except Exception as exc:
            return self._error(cfg, exc)

        try:
            result = self.engine.answer(query, cfg)
        except Exception as exc:
            return self._error(cfg, exc, status=502)

        shape = SHAPES.get(cfg["response_shape"], shape_openai)
        payload = shape(result, cfg, query)

        headers = {"X-Request-Id": hashlib.sha1(query.encode()).hexdigest()[:16]}
        if cfg["cache"]:
            headers["X-Cache"] = "HIT" if result["cache_hit"] else "MISS"
        if result.get("throttled_ms"):
            headers["X-RAGmap-Throttled-Ms"] = str(int(result["throttled_ms"]))
        return self._send(200, payload, headers)

    # -- error path ----------------------------------------------------
    def _error(self, cfg: dict, exc: Exception, status: int = 400):
        """
        Empty queries and malformed requests land here.

        quiet   : a bare envelope, no framework name
        verbose : a real Python traceback, plus an optional fake framework
                  trace from simulated_framework_trace. The fake trace is
                  there to exercise a scanner's framework fingerprinting;
                  it does not represent a real dependency.
        """
        if cfg["error_verbosity"] != "verbose":
            return self._send(status, {
                "error": {"code": "V-0001", "message": "invalid request"}
            })

        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        payload = {
            "error": {
                "code": "E-0500",
                "message": str(exc),
                "type": type(exc).__name__,
                "traceback": tb,
            }
        }
        fake = cfg.get("simulated_framework_trace")
        if fake:
            payload["error"]["detail"] = SIMULATED_TRACES.get(
                fake, f"{fake}: internal component raised during request handling")
        return self._send(status, payload)


SIMULATED_TRACES = {
    "langchain": (
        'File "/usr/local/lib/python3.11/site-packages/langchain/chains/'
        'retrieval_qa/base.py", line 131, in _call\n'
        '    docs = self._get_docs(question, run_manager=_run_manager)\n'
        'pydantic.error_wrappers.ValidationError: 1 validation error for '
        'RetrievalQAInput\nquery\n  str type expected (type=type_error.str)'
    ),
    "llamaindex": (
        'File "/usr/local/lib/python3.11/site-packages/llama_index/core/'
        'query_engine/retriever_query_engine.py", line 178, in _query\n'
        '    nodes = self.retrieve(query_bundle)\n'
        'ValueError: Query string cannot be empty'
    ),
    "fastapi": (
        'fastapi.exceptions.RequestValidationError: [{"loc": ["body", "message"], '
        '"msg": "ensure this value has at least 1 characters", '
        '"type": "value_error.any_str.min_length"}]'
    ),
    "chromadb": (
        'chromadb.errors.InvalidDimensionException: Embedding dimension 0 does '
        'not match collection dimensionality 384'
    ),
}


def extract_query(body: dict) -> str:
    """
    Pull the query out of any of the supported API shapes, so one server
    answers OpenAI, AnythingLLM and Dify request bodies at the same time.
    """
    if not isinstance(body, dict):
        raise ValueError("the body must be a JSON object")

    messages = body.get("messages")
    if isinstance(messages, list) and messages:
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                return str(msg.get("content") or "")
        return str(messages[-1].get("content") or "")

    for key in ("message", "query", "question", "input", "prompt", "text"):
        if key in body and isinstance(body[key], str):
            return body[key]

    inputs = body.get("inputs")
    if isinstance(inputs, dict):
        for value in inputs.values():
            if isinstance(value, str):
                return value

    raise ValueError("no query field found in the request "
                     "(expected messages / message / query / question)")


# ==========================================================================
# main
# ==========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="mockrag - a configurable RAG target for calibrating "
                    "ragmap")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--profile", default="o2_structured",
                        help="profile to use when the URL carries no profile=")
    parser.add_argument("--model", default=os.environ.get("GROQ_MODEL"),
                        help="Groq model name (default: chosen automatically)")
    parser.add_argument("--list-profiles", action="store_true")
    args = parser.parse_args()

    profiles = load_profiles()

    if args.list_profiles:
        print(f"{len(profiles)} profiles ({PROFILES_PATH}):\n")
        for name, cfg in profiles.items():
            merged = effective(cfg)
            print(f"  {name}")
            if cfg.get("_comment"):
                print(f"    {cfg['_comment']}")
            print(f"    level={merged['observability']} "
                  f"shape={merged['response_shape']} "
                  f"chunk={merged['chunk_size']}/{merged['chunk_overlap']} "
                  f"top_k={merged['top_k']} threshold={merged['similarity_threshold']} "
                  f"router={merged['router']} cache={merged['cache']}")
            print()
        return

    if args.profile not in profiles:
        sys.exit(f"no profile called '{args.profile}'. "
                 f"Available: {', '.join(profiles)}")

    api_key = os.environ.get("GROQ_API_KEY")
    generator = Generator(api_key, args.model)
    engine = Engine(generator)

    # Build the index up front so the first request's latency is not an
    # outlier.
    warm = effective(profiles[args.profile])
    index = engine.index_for(warm["chunk_size"], warm["chunk_overlap"],
                             warm["splitter"])

    Handler.engine = engine
    Handler.profiles = profiles
    Handler.default_profile = args.profile

    print("=" * 66)
    print("mockrag - calibration target for ragmap")
    print("=" * 66)
    print(f"  address         : http://{args.host}:{args.port}")
    print(f"  default profile : {args.profile}")
    print(f"  generator       : {generator.backend}"
          + (f"  model={generator.model}" if generator.backend == "groq" else ""))
    if generator.backend == "mock":
        print("                    (no GROQ_API_KEY - deterministic mock "
              "generator)")
    print(f"  corpus          : {len(index.documents)} documents, "
          f"{len(index.chunks)} chunks @ {index.chunk_size}/"
          f"{index.chunk_overlap}")
    print(f"  profiles        : {', '.join(profiles)}")
    print()
    print("  example:")
    print(f"    curl 'http://{args.host}:{args.port}/__ground_truth?profile=o3_full'")
    print(f"    ragmap -u 'http://{args.host}:{args.port}"
          f"/v1/chat/completions?profile=o3_full' --spend quick")
    print("=" * 66)

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[mockrag] kapatiliyor")
        httpd.server_close()


if __name__ == "__main__":
    main()
