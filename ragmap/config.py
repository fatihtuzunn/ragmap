"""Scan configuration - everything the CLI can set."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .paths import PathSpec


DEFAULT_LEVEL = 3

# Rough request ceilings per level. --budget overrides.
LEVEL_BUDGET = {1: 40, 2: 90, 3: 200, 4: 400, 5: 700}

DEFAULT_SPEND = "standard"

# --spend is the one dial for how much of the target's allowance the scan is
# allowed to eat. It sets a detection depth and a request ceiling together,
# because asking for level 4 on a thirty-request budget only produces a
# report full of "skipped - budget". Either half can still be set outright:
# an explicit --level or --budget wins over the tier.
#
# The ceilings are what the planner may spend, not what it will. It buys by
# information density, so a tier that cannot afford everything comes back
# with the facts most worth having rather than the first ones in the graph.
SPEND_TIERS: dict[str, dict] = {
    "peek":     {"level": 1, "budget": 12,
                 "about": "is it a RAG, and what can be seen from outside"},
    "quick":    {"level": 2, "budget": 35,
                 "about": "+ corpus topics, top-k, threshold"},
    "standard": {"level": 3, "budget": 90,
                 "about": "+ chunk size, retrieval mode, verbatim leak"},
    "deep":     {"level": 4, "budget": 220,
                 "about": "+ chunk overlap, reranker, fine threshold"},
    "max":      {"level": 5, "budget": 700,
                 "about": "everything, including embedding behaviour"},
}


@dataclass
class ScanConfig:
    url: str = ""
    headers: dict = field(default_factory=dict)
    level: int = DEFAULT_LEVEL
    budget: int = 0                     # 0 => derive from level
    token_budget: int = 0               # 0 => no token ceiling
    spend: str = DEFAULT_SPEND
    delay: float = 0.5
    jitter: float = 0.0
    timeout: int = 90
    verify_tls: bool = True
    model: str = "ragmap"
    proxy: str | None = None

    # Session handling. Off unless the operator asks for it: inventing a
    # body field the target did not ask for can change how it routes the
    # request, and a recon tool should not alter what it is measuring.
    rotate_every: int = 0
    session_field: str = "session_id"
    opsec_rules: Path | None = None

    only: set[str] = field(default_factory=set)
    skip: set[str] = field(default_factory=set)
    allow_mutating: bool = False

    # Manual overrides that let an operator skip detection entirely.
    shape: str | None = None
    query_field: str | None = None
    vector_store: str | None = None
    paths: PathSpec = field(default_factory=PathSpec)
    topic: str | None = None
    second_topic: str | None = None
    absent_topic: str | None = None
    rare_token: str | None = None
    seed_queries: list[str] = field(default_factory=list)

    out_dir: Path | None = None
    json_out: Path | None = None
    text_out: Path | None = None
    replay_dir: Path | None = None

    dump_chunks: bool = False
    max_chunk_chars: int = 200
    color: bool = True
    verbosity: int = 0

    def effective_budget(self) -> int:
        if self.budget:
            return self.budget
        tier = SPEND_TIERS.get(self.spend)
        if tier:
            return int(tier["budget"])
        return LEVEL_BUDGET.get(self.level, 200)
