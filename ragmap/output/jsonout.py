"""Machine-readable report.

Chunk text is always complete here, regardless of terminal truncation: the
JSON file is the artefact other tooling consumes, and a truncated passage is
useless as evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import confidence
from ..model import ScanResult


def to_dict(result: ScanResult) -> dict:
    return {
        "tool": "ragmap",
        "version": "0.1.0",
        "target": result.target,
        "level": result.level,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "duration_s": round(result.duration_s, 2),
        "requests_used": result.requests_used,
        "budget": result.budget,
        "spend": result.spend,
        "requests_saved": result.requests_saved,
        "tokens_used": result.tokens_used,
        "tokens_measured": result.tokens_measured,
        "token_budget": result.token_budget,
        "calibration_generated_at": confidence.generated_at(),
        "facts": {
            key: {
                "label": fact.label,
                "section": fact.section,
                "value": _safe(fact.value),
                "display": fact.display,
                "status": fact.status,
                "reason": fact.reason,
                "method": fact.method,
                "evidence": fact.evidence,
                "confidence": {
                    "kind": fact.confidence.kind,
                    "calibration": fact.confidence.calibration,
                },
            }
            for key, fact in sorted(result.facts.items())
        },
        "findings": [
            {
                "id": f.id,
                "title": f.title,
                "severity": f.severity,
                "summary": f.summary,
                "detail": f.detail,
                "evidence": f.evidence,
                "facts": f.facts,
            }
            for f in result.sorted_findings()
        ],
        "chunks": [
            {
                "text": c.text,
                "query": c.query,
                "doc_id": c.doc_id,
                "chunk_id": c.chunk_id,
                "title": c.title,
                "page": _safe(c.page),
                "score": c.score,
                "chars": len(c.text),
            }
            for c in result.chunks
        ],
        "modules": [
            {
                "name": m.name,
                "status": m.status,
                "reason": m.reason,
                "requests": m.requests,
                "seconds": m.seconds,
            }
            for m in result.modules
        ],
        "notes": result.notes,
    }


def _safe(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    return str(value)


def write(result: ScanResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_dict(result), ensure_ascii=False, indent=2),
                    encoding="utf-8")
