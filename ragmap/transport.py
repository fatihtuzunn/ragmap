"""HTTP layer: send a query, record everything, hand back a normalised view.

Two design decisions worth stating.

**Raw recording.** Every request and response is written to disk before it is
interpreted. Analysis can then be re-run offline (``--replay``) with changed
criteria and zero new requests. If you decide what to look for while you are
recording, you can never see what you did not look for.

**Structural source detection.** Retrieved passages are found by the *shape*
of the response, not by a list of blessed field names. A scanner that only
knows ``sources``/``context``/``documents`` goes blind on Dify
(``metadata.retriever_resources``) and on any OpenAI-compatible wrapper that
calls them ``citations``. We look for the best candidate list anywhere in the
body and normalise whatever we find.
"""

from __future__ import annotations

import json
import random
import re

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests


# Field names used only to *label* an already-detected source entry. Finding
# the entries themselves never depends on this list.
TEXT_KEYS = ("text", "content", "page_content", "chunk", "passage", "body",
             "snippet", "document", "excerpt", "chunk_text")
TITLE_KEYS = ("title", "filename", "file_name", "document_name", "name",
              "source", "source_file", "doc_name", "path", "url")
# A document id names the document. An id that is different on every
# passage of the same file names the chunk, and treating it as the
# document puts each passage in a group of one -- which silently
# disables every measurement that compares passages of one document.
# Not every field whose name suggests a source carries an identifier:
# AnythingLLM's `docSource` is the same prose sentence on every
# document ("a text file uploaded by the user."), so it names nothing.
# Candidates are checked by shape before being believed.
DOCID_KEYS = ("doc_id", "document_id", "docid", "source_id",
              "file_id", "parent_id")
CHUNKID_KEYS = ("id", "uuid", "chunk_id", "vector_id", "_id")
PAGE_KEYS = ("page", "page_number", "page_label", "loc", "line")
SCORE_KEYS = ("score", "similarity", "similarity_score", "relevance",
              "relevance_score", "distance", "_distance", "rerank_score",
              "reranking_score", "confidence")
TOKEN_KEYS = ("usage", "prompt_tokens", "completion_tokens", "total_tokens",
              "input_tokens", "output_tokens", "prompt_eval_count",
              "eval_count", "token_count", "metrics")

ANSWER_PATHS: tuple[tuple, ...] = (
    ("choices", 0, "message", "content"),
    ("choices", 0, "text"),
    ("textResponse",),
    ("answer",),
    ("response",),
    ("output_text",),
    ("output",),
    ("result",),
    ("reply",),
    ("message", "content"),
    ("message",),
    ("content",),
    ("text",),
    ("data", "answer"),
    ("data", "response"),
    ("data", "text"),
)

from .opsec import Meter
from .paths import PathSpec, resolve

MIN_PASSAGE_CHARS = 80


@dataclass
class SourceEntry:
    text: str = ""
    title: str | None = None
    doc_id: str | None = None
    page: Any = None
    score: float | None = None
    chunk_id: str | None = None
    raw: Any = None

    @property
    def core(self) -> str:
        """The passage with any product-added wrapper removed."""
        return strip_envelope(self.text)


RATE_LIMIT_RE = re.compile(r"\b429\b|rate[ _-]?limit|too many requests|quota",
                           re.IGNORECASE)
RETRY_AFTER_RE = re.compile(r"try again in\s*([0-9.]+)\s*(ms|s|m)\b",
                            re.IGNORECASE)
# A per-minute limit clears by waiting; a daily or monthly allowance does
# not. Targets say which in the message itself - "on tokens per day (TPD):
# Limit 200000, Used 199163" - and a scanner that answers both by widening
# its pace spends the operator's afternoon collecting one reply every two
# minutes. Once the day's allowance is gone the honest move is to stop and
# say so.
QUOTA_WINDOW_RE = re.compile(
    r"per\s+(day|month)\b|\b(TPD|RPD)\b|daily\s+(limit|quota)"
    r"|monthly\s+(limit|quota)|quota\s+exceeded|insufficient[_ ]quota",
    re.IGNORECASE)


def upstream_error(body: Any, status: int | None) -> str | None:
    """Return a reason when the reply is the target failing, not answering.

    A rate-limited or crashed target still answers with a well-formed body:
    AnythingLLM turns an upstream 429 into ``{"type":"abort","sources":[],
    "error":"429 Rate limit reached..."}``. Read naively that is a successful
    exchange with no retrieved passages, and a scanner that counts it as
    evidence will report an O3 system as O0. An errored exchange is not
    evidence of anything except that the request failed.
    """
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, str) and err.strip():
            return err.strip()[:300]
        if isinstance(err, dict):
            message = err.get("message") or err.get("detail") or json.dumps(err)
            return str(message)[:300]
        if str(body.get("type", "")).strip().lower() == "abort":
            return "response marked aborted by the target"
    if status is not None and status >= 500:
        return f"HTTP {status}"
    return None


def quota_exhausted(reason: str) -> bool:
    """True when the refusal names a daily or monthly allowance.

    Distinguished from an ordinary pace limit because no amount of waiting
    inside one scan wins the allowance back.
    """
    return bool(reason) and bool(QUOTA_WINDOW_RE.search(reason))


def retry_after_seconds(reason: str) -> float | None:
    """Honour a 'please try again in 3.03s' hint when the target gives one."""
    match = RETRY_AFTER_RE.search(reason or "")
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit == "ms":
        return value / 1000.0
    if unit == "m":
        return value * 60.0
    return value


@dataclass
class Probe:
    """One request/response exchange, parsed but not yet interpreted."""
    query: str
    url: str = ""
    status: int | None = None
    latency_ms: float = 0.0
    headers: dict = field(default_factory=dict)
    body: Any = None
    raw_text: str = ""
    answer: str = ""
    answer_path: tuple | None = None
    sources: list[SourceEntry] = field(default_factory=list)
    source_field: str | None = None
    source_count: int | None = None
    token_fields: list[str] = field(default_factory=list)
    error: str | None = None
    index: int = 0
    tokens: int = 0                 # what this one exchange cost
    cached: bool = False            # answered from an earlier identical ask

    @property
    def ok(self) -> bool:
        return self.error is None and self.status is not None and self.status < 400

    @property
    def scores(self) -> list[float]:
        return [s.score for s in self.sources if s.score is not None]

    @property
    def chunk_texts(self) -> list[str]:
        return [s.text for s in self.sources if s.text]


class BudgetExhausted(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------

def dig(obj: Any, path: tuple) -> Any:
    cur = obj
    for step in path:
        if isinstance(step, int):
            if not isinstance(cur, list) or len(cur) <= step:
                return None
            cur = cur[step]
        else:
            if not isinstance(cur, dict) or step not in cur:
                return None
            cur = cur[step]
    return cur


def find_answer(body: Any) -> tuple[tuple | None, str]:
    if isinstance(body, str):
        return ("<raw>",), body
    for path in ANSWER_PATHS:
        value = dig(body, path)
        if isinstance(value, str) and value.strip():
            return path, value
    return None, ""


def _first(entry: dict, keys: tuple) -> Any:
    for key in keys:
        for actual in entry:
            if actual.lower() == key:
                value = entry[actual]
                if value not in (None, "", []):
                    return value
    return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


ENVELOPE_RE = re.compile(
    r"\A\s*<\s*(document_metadata|metadata|doc_meta|source_metadata)\s*>"
    r".*?</\s*\1\s*>\s*", re.DOTALL | re.IGNORECASE)


def strip_envelope(text: str) -> str:
    """Remove a product-added metadata header from a returned passage.

    AnythingLLM prefixes every passage with a <document_metadata> block
    naming the source file and its publication date. It is real text in the
    prompt, so it belongs in what the operator sees, but it is not corpus
    text: counting it makes every chunk look ~125 characters wider than the
    splitter was configured for, and it breaks overlap matching, because two
    neighbouring chunks no longer start with shared text.
    """
    if not text:
        return ""
    return ENVELOPE_RE.sub("", text, count=1)


def looks_like_identifier(value: str) -> bool:
    """Reject prose that happens to sit in an identifier-shaped field.

    An identifier names one thing. A sentence - several words, ending in a
    full stop - names nothing, and a field that holds the same sentence for
    every document is a description, not an id.
    """
    text = (value or "").strip()
    if not text or len(text) > 160:
        return False
    if text.endswith("."):
        return "." in text[:-1] or " " not in text    # allows "policy.md"
    return text.count(" ") <= 4


def normalise_entry(item: Any) -> SourceEntry:
    """Turn one element of a source list into a common shape."""
    if isinstance(item, str):
        return SourceEntry(text=item, raw=item)
    if not isinstance(item, dict):
        return SourceEntry(raw=item)

    text = _first(item, TEXT_KEYS)
    if not isinstance(text, str):
        # Some shapes nest the passage one level down (e.g. {"document": {...}}).
        for value in item.values():
            if isinstance(value, dict):
                nested = _first(value, TEXT_KEYS)
                if isinstance(nested, str):
                    text = nested
                    break
    page = _first(item, PAGE_KEYS)
    title = _first(item, TITLE_KEYS)
    doc_id = _first(item, DOCID_KEYS)
    if doc_id is not None and not looks_like_identifier(str(doc_id)):
        doc_id = None
    chunk_id = _first(item, CHUNKID_KEYS)
    score = _as_float(_first(item, SCORE_KEYS))

    return SourceEntry(
        text=text if isinstance(text, str) else "",
        title=str(title) if title is not None else None,
        doc_id=str(doc_id) if doc_id is not None else None,
        chunk_id=str(chunk_id) if chunk_id is not None else None,
        page=page,
        score=score,
        raw=item,
    )


# Lists that carry the reply itself, not retrieved passages. Without this
# guard the OpenAI envelope wins the scoring on every opaque target: the
# answer is long text inside a list, which is exactly what a passage looks
# like. The result is that an O0 system reads as O3 and every retrieval
# parameter is then measured against the answer instead of a chunk.
ANSWER_ENVELOPE_KEYS = {"choices", "messages", "message", "output", "outputs",
                        "candidates", "generations", "results"}


def find_sources(body: Any, answer: str = "") -> tuple[str | None, list[SourceEntry]]:
    """
    Locate the retrieved-passage list anywhere in the response.

    Scoring favours lists whose entries look like retrieval results: dicts
    carrying a passage, a score or an identifier, or plain long strings.
    The winning list's key name is reported so the operator can see what the
    product calls it.
    """
    best_key: str | None = None
    best_items: list[SourceEntry] = []
    best_score = 0
    answer_norm = " ".join((answer or "").split())

    def is_answer(text: str) -> bool:
        if not answer_norm or not text:
            return False
        norm = " ".join(text.split())
        return norm == answer_norm or norm in answer_norm or answer_norm in norm

    def consider(key: str | None, node: list) -> None:
        nonlocal best_key, best_items, best_score
        if not key or not node or key.lower() in ANSWER_ENVELOPE_KEYS:
            return
        entries = [normalise_entry(item) for item in node]
        score = 0
        for entry in entries:
            # A passage that is simply the reply is not evidence of retrieval.
            if is_answer(entry.text):
                continue
            if entry.text and len(entry.text) >= MIN_PASSAGE_CHARS:
                score += 3
            elif entry.text:
                score += 1
            if entry.score is not None:
                score += 2
            if entry.doc_id or entry.title:
                score += 1
        if score > best_score:
            best_score, best_key, best_items = score, key, entries

    def walk(node: Any, key: str | None) -> None:
        if isinstance(node, list):
            consider(key, node)
            for item in node:
                walk(item, key)
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)

    walk(body, None)
    return best_key, best_items


def find_token_fields(body: Any) -> list[str]:
    hits: list[str] = []

    def walk(node: Any, prefix: str = "") -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                full = f"{prefix}.{k}" if prefix else k
                if k.lower() in TOKEN_KEYS and v not in (None, {}, []):
                    hits.append(full)
                walk(v, full)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{prefix}[{i}]")

    walk(body)
    return hits


USAGE_IN_KEYS = ("prompt_tokens", "input_tokens", "prompt_eval_count")
USAGE_OUT_KEYS = ("completion_tokens", "output_tokens", "eval_count")


def measured_tokens(body: Any) -> tuple[int | None, int | None]:
    """Read the target's own token counts when it reports them.

    OpenAI-shaped bodies carry ``usage.prompt_tokens``; Ollama reports
    ``prompt_eval_count``; Anthropic ``input_tokens``. A measured count beats
    any estimate, and a target that exposes one is also the kind most likely
    to meter the operator on it.
    """
    found: dict[str, int] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                low = key.lower()
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    if low in USAGE_IN_KEYS or low in USAGE_OUT_KEYS:
                        found.setdefault(low, int(value))
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(body)
    tokens_in = next((found[k] for k in USAGE_IN_KEYS if k in found), None)
    tokens_out = next((found[k] for k in USAGE_OUT_KEYS if k in found), None)
    return tokens_in, tokens_out


def estimate_tokens(text: str) -> int:
    """Four characters to a token: close enough to pace a scan by."""
    return max(1, len(text or "") // 4)


def substitute(obj: Any, query: str, model: str) -> Any:
    if isinstance(obj, str):
        return obj.replace("{{QUERY}}", query).replace("{{MODEL}}", model)
    if isinstance(obj, dict):
        return {k: substitute(v, query, model) for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute(v, query, model) for v in obj]
    return obj


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------

class Transport:
    def __init__(self, url: str, headers: dict | None = None,
                 body_template: dict | None = None, model: str = "ragmap",
                 timeout: int = 90, delay: float = 0.5, budget: int = 200,
                 verify_tls: bool = True, raw_dir: Path | None = None,
                 token_budget: int = 0, proxy: str | None = None,
                 jitter: float = 0.0, paths: PathSpec | None = None,
                 rotate_every: int = 0, session_field: str = "session_id",
                 opsec: Meter | None = None):
        self.url = url
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        self.body_template = body_template
        self.model = model
        self.timeout = timeout
        self.delay = delay
        self.budget = budget
        self.verify_tls = verify_tls
        self.raw_dir = raw_dir
        self.used = 0
        self.session = requests.Session()
        # An intercepting proxy is how an operator watches a scan, replays
        # one exchange by hand, or shows a client what was actually sent.
        self.proxy = proxy
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        # A scan that sends one request exactly every N seconds is a
        # straight line in anyone's request log. Jitter spreads the pace
        # around the operator's delay without changing its average.
        self.jitter = max(0.0, jitter)
        # Where the structural search is wrong, the operator says where to
        # look instead. An empty spec means the structural search decides.
        self.paths = paths or PathSpec()
        # Some targets thread a conversation id through the body. Keeping
        # one for the whole scan ties every probe together in the target's
        # own logs; rotating it breaks that correlation.
        self.rotate_every = max(0, rotate_every)
        self.session_field = session_field
        self.session_id = uuid4().hex
        self.rotations = 0
        self._since_rotation = 0
        # What this scan would look like to whoever is watching the target.
        # Measured, not promised: see ragmap/opsec.py.
        self.opsec = opsec
        self.rate_limit: dict[str, str] = {}
        # How many times a rate-limited request is retried before the probe
        # is handed back as failed. Retries are real requests and are
        # charged to the budget.
        self.max_retries = 3
        # Adaptive pacing. `delay` is the operator's starting point; it is
        # widened whenever the target reports a rate limit and allowed to
        # settle back after a stretch of clean replies.
        self.base_delay = delay
        self.max_delay = 90.0
        self.throttled = 0
        self._clean_streak = 0
        # Set to the target's own words the first time it refuses on a daily
        # or monthly allowance. From then on the scan has no requests left,
        # whatever the budget says.
        self.exhausted: str | None = None
        # Token accounting. Targets meter on tokens, not requests, so a
        # request ceiling alone cannot keep a scan inside an allowance: one
        # question against a top-k of 12 costs four times what it costs
        # against a top-k of 3. `tokens_measured` records whether these are
        # the target's own numbers or our four-chars-to-a-token estimate.
        self.token_budget = token_budget
        self.tokens_in = 0
        self.tokens_out = 0
        self.tokens_measured = False
        if self.raw_dir:
            self.raw_dir.mkdir(parents=True, exist_ok=True)

    @property
    def remaining(self) -> int:
        if self.exhausted:
            return 0
        if self.token_budget and self.tokens_used >= self.token_budget:
            return 0
        return max(0, self.budget - self.used)

    @property
    def tokens_used(self) -> int:
        return self.tokens_in + self.tokens_out

    @property
    def tokens_per_request(self) -> float:
        """What one exchange has cost so far, used to price the next one."""
        if not self.used:
            return 0.0
        return self.tokens_used / self.used

    def can_afford(self, n: int) -> bool:
        """True when n more requests fit both ceilings.

        The token ceiling is priced from what this target has actually
        charged so far. Before the first exchange nothing is known, so the
        request ceiling decides alone.
        """
        if self.remaining < n:
            return False
        if self.token_budget and self.used:
            projected = self.tokens_used + n * self.tokens_per_request
            if projected > self.token_budget:
                return False
        return True

    # ----------------------------------------------------------------
    def send(self, query: str, body_template: dict | None = None,
             extra_headers: dict | None = None) -> Probe:
        """Send one query, retrying while the target says it is rate limited.

        Retries are real requests and are charged to the budget like any
        other. Giving up returns the failed probe rather than raising: the
        caller records the failure and the scan continues.
        """
        attempt = 0
        while True:
            probe = self._send_once(query, body_template, extra_headers)
            if not probe.error or not RATE_LIMIT_RE.search(probe.error):
                self._note_clean()
                return probe

            if quota_exhausted(probe.error):
                # Waiting cannot buy back a day's allowance. Record why the
                # scan stops and hand the failed probe back unretried.
                self.throttled += 1
                self.exhausted = probe.error
                return probe

            self._note_throttled()
            if attempt >= self.max_retries or self.remaining <= 1:
                return probe

            # The target's own hint clears the request that was refused, not
            # the whole window, so wait the hint plus the pace we have
            # settled on rather than the hint alone.
            wait = retry_after_seconds(probe.error) or 2.0 * (2 ** attempt)
            time.sleep(min(wait + self.delay, self.max_delay))
            attempt += 1

    def _note_throttled(self) -> None:
        self.throttled += 1
        self._clean_streak = 0
        widened = max(self.delay * 1.5, (self.base_delay or 1.0) * 1.5, 2.0)
        self.delay = min(widened, self.max_delay)

    def _note_clean(self) -> None:
        if not self.throttled:
            return
        self._clean_streak += 1
        # Five clean replies in a row suggest the widened pace is more than
        # the target needs; give a little back, but never below where the
        # operator started.
        if self._clean_streak >= 5 and self.delay > self.base_delay:
            self.delay = max(self.base_delay, self.delay * 0.8)
            self._clean_streak = 0

    def _send_once(self, query: str, body_template: dict | None = None,
                   extra_headers: dict | None = None) -> Probe:
        if self.exhausted:
            raise BudgetExhausted(
                f"the target's own allowance is spent: {self.exhausted[:120]}")
        if self.budget and self.used >= self.budget:
            raise BudgetExhausted(f"request budget of {self.budget} is spent")

        template = body_template or self.body_template
        if template is None:
            raise RuntimeError("no request shape has been established yet")

        body = substitute(template, query, self.model)
        self._stamp_session(body)
        if self.opsec is not None:
            # Counted here rather than in send(): a retry is a second real
            # request against the target and shows up in its logs twice.
            self.opsec.observe(query)

        if self.token_budget:
            # Stop before the request that would cross the ceiling, not
            # after it. Price it from the body about to be sent rather than
            # from the running average: the long-input probe that tests
            # error verbosity carries twenty thousand characters, four times
            # what an average question costs, and an average would wave it
            # through and overshoot the operator's allowance by a quarter.
            cost = estimate_tokens(json.dumps(body, ensure_ascii=False))
            cost += int(self.tokens_out / self.used) if self.used else 0
            if (self.tokens_used >= self.token_budget
                    or self.tokens_used + cost > self.token_budget):
                raise BudgetExhausted(
                    f"token budget of {self.token_budget} is spent "
                    f"({self.tokens_used} used over {self.used} requests; "
                    f"this one would cost about {cost})")

        headers = dict(self.headers)
        if extra_headers:
            headers.update(extra_headers)

        probe = Probe(query=query, url=self.url, index=self.used)
        start = time.perf_counter()
        try:
            response = self.session.post(self.url, headers=headers, json=body,
                                         timeout=self.timeout,
                                         verify=self.verify_tls)
        except requests.RequestException as exc:
            probe.error = f"{type(exc).__name__}: {exc}"
            probe.latency_ms = (time.perf_counter() - start) * 1000
            self.used += 1
            self._record(probe, body)
            return probe

        probe.latency_ms = (time.perf_counter() - start) * 1000
        probe.status = response.status_code
        probe.headers = dict(response.headers)
        probe.raw_text = response.text
        self._note_rate_limit(response.headers)

        try:
            probe.body = response.json()
        except ValueError:
            probe.body = response.text

        probe.error = upstream_error(probe.body, probe.status)

        probe.answer_path, probe.answer = find_answer(probe.body)
        probe.source_field, probe.sources = find_sources(probe.body, probe.answer)
        self._apply_paths(probe)
        probe.source_count = len(probe.sources) if probe.source_field else None
        probe.token_fields = find_token_fields(probe.body)
        self._charge(probe, body)

        self.used += 1
        self._record(probe, body)
        self._pause()
        return probe

    def _pause(self) -> None:
        if not self.delay and not self.jitter:
            return
        wait = self.delay + random.uniform(-self.jitter, self.jitter)
        if wait > 0:
            time.sleep(wait)

    def _stamp_session(self, body: Any) -> None:
        """Carry a session id in the body, rotating it every N requests.

        Off by default: inventing a field the target did not ask for can
        change how it routes the request, and a recon tool should not alter
        the thing it is measuring without being told to.
        """
        if not self.rotate_every or not isinstance(body, dict):
            return
        body[self.session_field] = self.session_id
        self._since_rotation += 1
        if self._since_rotation >= self.rotate_every:
            self.session_id = uuid4().hex
            self._since_rotation = 0
            self.rotations += 1

    def _apply_paths(self, probe: Probe) -> None:
        """Replace structural findings with the operator's own paths.

        Only the paths given are overridden; anything left unset keeps
        whatever the structural search produced. A path that resolves to
        nothing leaves the field empty rather than falling back, so a wrong
        path shows up as a wrong path.
        """
        spec = self.paths
        if not spec.active or not isinstance(probe.body, (dict, list)):
            return

        if spec.answer_path:
            value = resolve(probe.body, spec.answer_path)
            probe.answer = value if isinstance(value, str) else (
                "" if value is None
                else json.dumps(value, ensure_ascii=False, default=str))
            probe.answer_path = tuple(
                part for part in spec.answer_path.replace("[]", "").split(".")
                if part)

        if spec.source_path:
            items = resolve(probe.body, spec.source_path)
            if not isinstance(items, list):
                items = []
            entries = [self._entry_from_paths(item) for item in items]
            probe.sources = [e for e in entries if e.text or e.title or e.doc_id]
            probe.source_field = spec.source_path

    def _entry_from_paths(self, item: Any) -> SourceEntry:
        """Build one passage from an item, path first, key search second."""
        if isinstance(item, str):
            return SourceEntry(text=item, title=None, raw=item)
        if not isinstance(item, dict):
            return SourceEntry(raw=item)

        spec = self.paths

        def pick(path: str, keys: tuple) -> Any:
            # Naming the array is usually enough: the fields inside it
            # mostly carry the names the structural search already knows,
            # so an unnamed field keeps working.
            return resolve(item, path) if path else _first(item, keys)

        text = pick(spec.text_path, TEXT_KEYS)
        title = pick(spec.title_path, TITLE_KEYS)
        doc_id = pick(spec.doc_id_path, DOCID_KEYS)
        chunk_id = pick(spec.chunk_id_path, CHUNKID_KEYS)
        page = pick(spec.page_path, PAGE_KEYS)
        score = _as_float(pick(spec.score_path, SCORE_KEYS))

        return SourceEntry(
            text=text if isinstance(text, str) else "",
            title=str(title) if title is not None else None,
            doc_id=str(doc_id) if doc_id is not None else None,
            chunk_id=str(chunk_id) if chunk_id is not None else None,
            page=page,
            score=score,
            raw=item,
        )

    # ----------------------------------------------------------------
    def _charge(self, probe: Probe, request_body: Any) -> None:
        """Add what this exchange cost to the running token total.

        A refused request is charged too. Providers meter the tokens a
        prompt asked for, not the ones they ended up generating, so a scan
        that only counted successful answers would walk straight through an
        allowance it had already spent on retries.
        """
        tokens_in, tokens_out = measured_tokens(probe.body)
        if tokens_in is not None or tokens_out is not None:
            self.tokens_measured = True
        if tokens_in is None:
            tokens_in = estimate_tokens(json.dumps(request_body,
                                                   ensure_ascii=False))
        if tokens_out is None:
            tokens_out = estimate_tokens(probe.raw_text)
        self.tokens_in += max(0, int(tokens_in))
        self.tokens_out += max(0, int(tokens_out))
        probe.tokens = max(0, int(tokens_in)) + max(0, int(tokens_out))

    def _note_rate_limit(self, headers) -> None:
        for key, value in headers.items():
            if "ratelimit" in key.lower() or key.lower() == "retry-after":
                self.rate_limit[key] = value

    def _record(self, probe: Probe, request_body: Any) -> None:
        if not self.raw_dir:
            return
        path = self.raw_dir / f"{probe.index:04d}.json"
        payload = {
            "index": probe.index,
            "query": probe.query,
            "url": probe.url,
            "request_body": request_body,
            "status": probe.status,
            "latency_ms": round(probe.latency_ms, 2),
            "response_headers": probe.headers,
            "raw_text": probe.raw_text,
            "error": probe.error,
        }
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        except OSError:
            pass


def probe_from_record(record: dict) -> Probe:
    """Rebuild a Probe from a recorded exchange (``--replay``)."""
    probe = Probe(query=record.get("query", ""), url=record.get("url", ""),
                  index=record.get("index", 0))
    probe.status = record.get("status")
    probe.latency_ms = record.get("latency_ms") or 0.0
    probe.headers = record.get("response_headers") or {}
    probe.raw_text = record.get("raw_text") or ""
    probe.error = record.get("error")
    try:
        probe.body = json.loads(probe.raw_text)
    except (ValueError, TypeError):
        probe.body = probe.raw_text
    probe.answer_path, probe.answer = find_answer(probe.body)
    probe.source_field, probe.sources = find_sources(probe.body, probe.answer)
    probe.source_count = len(probe.sources) if probe.source_field else None
    probe.token_fields = find_token_fields(probe.body)
    return probe
