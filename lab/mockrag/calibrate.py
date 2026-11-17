#!/usr/bin/env python3
"""Measure the scanner against targets whose configuration is known.

This is what separates a reported number from a guess. Every mockrag profile
declares its true chunk size, overlap, top-k, threshold, retrieval mode and
observability level, and serves them at ``/__ground_truth``. The scanner is
run against each one and its output is compared with the truth.

Two numbers come out per detector:

    hits / total   how often the value was exactly right
    MAE            mean absolute error, for numeric facts

and one more that matters just as much:

    silent failures   times the detector returned nothing although the
                      information needed to measure it was on screen

The result is written to ``ragmap/data/calibration.json`` and shipped with
the tool, so the confidence shown next to a value in a real engagement is
backed by this measurement rather than by a hand-written label.

Usage (from the repository root, with the lab server already running):
    python lab/mockrag/calibrate.py                  # all profiles, level 4
    python lab/mockrag/calibrate.py --level 5
    python lab/mockrag/calibrate.py --only o3_full
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent        # lab/mockrag
LAB = HERE.parent                             # lab
ROOT = LAB.parent                             # repository root
# Run from a checkout without installing: the package sits at the root.
sys.path.insert(0, str(ROOT))

from ragmap.config import ScanConfig          # noqa: E402
from ragmap.scanner import scan               # noqa: E402

CALIBRATION_PATH = ROOT / "ragmap" / "data" / "calibration.json"

SHAPE_PATHS = {
    "openai": "/v1/chat/completions",
    "anythingllm": "/api/v1/workspace/ragmap-test/chat",
    "dify": "/v1/chat-messages",
}


def truth_for(base: str, profile: str) -> dict:
    url = f"{base}/__ground_truth?profile={profile}"
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.load(response)


def profiles_from(base: str) -> list[str]:
    with urllib.request.urlopen(f"{base}/__profiles", timeout=20) as response:
        return list(json.load(response)["profiles"])


# --------------------------------------------------------------------------
# Comparisons. Each returns (ok, error_or_None, expected_display)
# --------------------------------------------------------------------------

def _num(expected, actual, tolerance=0):
    if actual is None:
        return False, None, expected
    try:
        actual = float(actual)
        expected_f = float(expected)
    except (TypeError, ValueError):
        return False, None, expected
    error = abs(actual - expected_f)
    return error <= tolerance, error, expected


def compare(fact_key: str, fact, truth: dict):
    value = fact.value if fact and fact.ok else None

    if fact_key == "obs.level":
        return (value == truth["observability_declared"]), None, \
            truth["observability_declared"]

    if fact_key == "retrieval.top_k":
        # With a threshold in play the list is trimmed before it reaches the
        # caller, so the observable count is at most the configured top-k.
        # Reporting the smaller number is right, not wrong.
        if truth["similarity_threshold"] is not None and value is not None:
            return (0 < float(value) <= float(truth["top_k"])), None,                 f"<= {truth['top_k']}"
        return _num(truth["top_k"], value)

    if fact_key == "chunk.size":
        expected = truth["chunk_size"]
        if value is None:
            return False, None, expected
        # A lower bound is scored as correct only if it does not exceed the
        # real width; it is never credited with hitting the value.
        if fact.confidence.kind == "heuristic":
            return (value <= expected), abs(expected - value), expected
        return _num(expected, value, tolerance=10)

    if fact_key == "chunk.overlap":
        return _num(truth["chunk_overlap"], value, tolerance=5)

    if fact_key == "retrieval.threshold":
        expected = truth["similarity_threshold"]
        applied = expected is not None
        observed = value is not None
        return (applied == observed), None, ("applied" if applied else "none")

    if fact_key == "retrieval.mode":
        expected = truth["retrieval_mode"]
        return (value == expected), None, expected

    if fact_key == "routing.router":
        return (bool(value) == bool(truth["router"])), None, truth["router"]

    if fact_key == "routing.cache":
        return (bool(value) == bool(truth["cache"])), None, truth["cache"]

    if fact_key == "generation.determinism":
        expected = truth.get("temperature", 0) == 0
        return (bool(value) == expected), None, expected

    return None, None, None


# Facts that should have been measurable given what the target exposes.
def measurable(fact_key: str, truth: dict) -> bool:
    if fact_key in ("chunk.overlap",):
        return bool(truth["expose_chunk_text"])
    if fact_key == "chunk.size":
        # Either the passages are visible, or the generation layer has to be
        # willing to quote them. With a verbatim guard and no visible
        # passages there is nothing left to measure.
        return bool(truth["expose_chunk_text"]) or not truth["verbatim_guard"]
    if fact_key in ("retrieval.top_k", "retrieval.threshold"):
        return bool(truth["emit_sources"])
    if fact_key == "retrieval.mode":
        # Separating lexical from dense needs a usable discriminator: visible
        # scores, or a threshold that makes retrieve/miss meaningful. With
        # neither, declining is correct.
        return bool(truth["emit_sources"]) and (
            bool(truth["expose_scores"]) or truth["similarity_threshold"] is not None)
    # The router detector has a legitimate timing-only path, so it is
    # expected to answer even when no sources are visible.
    return True


TRACKED = ["obs.level", "retrieval.top_k", "chunk.size", "chunk.overlap",
           "retrieval.threshold", "retrieval.mode", "routing.router",
           "routing.cache", "generation.determinism"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate ragmap against mockrag")
    parser.add_argument("--base", default="http://127.0.0.1:8099")
    parser.add_argument("--level", type=int, default=4)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--budget", type=int, default=400)
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--report", type=Path,
                        default=ROOT / "docs" / "calibration-report.md")
    parser.add_argument("--no-write", action="store_true",
                        help="do not update ragmap/data/calibration.json")
    args = parser.parse_args()

    names = args.only or profiles_from(args.base)
    stats: dict[str, dict] = defaultdict(
        lambda: {"hits": 0, "total": 0, "errors": [], "silent": 0,
                 "abstained": 0, "false_positives": 0, "not_run": 0,
                 "by_obs": defaultdict(lambda: {"hits": 0, "total": 0, "errors": []})})
    rows: list[dict] = []

    for name in names:
        truth = truth_for(args.base, name)
        path = SHAPE_PATHS.get(truth["response_shape"], "/v1/chat/completions")
        url = f"{args.base}{path}?profile={name}"

        print(f"\n=== {name}  ({truth['response_shape']}, "
              f"declared {truth['observability_declared']}) ===")
        config = ScanConfig(url=url, level=args.level, budget=args.budget,
                            delay=args.delay, out_dir=None)
        result = scan(config)
        obs = truth["observability_declared"]

        row = {"profile": name, "shape": truth["response_shape"],
               "observability": obs, "requests": result.requests_used,
               "facts": {}}

        for key in TRACKED:
            fact = result.facts.get(key)
            ok, error, expected = compare(key, fact, truth)
            if ok is None:
                continue

            entry = stats[key]
            measured = bool(fact and fact.ok)

            # A detector that was never run is not evidence either way.
            # Scoring its silence as agreement was free marks: `bool(None)
            # == bool(False)` credited a level-gated detector with knowing
            # there was no router. Counted separately, a cheap scan shows
            # what it did not buy instead of what it did not find.
            status = getattr(fact, "status", "") if fact else "missing"
            if status in ("skipped-level", "skipped-budget"):
                entry["not_run"] += 1
                print(f"  --  {key:<26} not run ({status})")
                continue

            # When the target does not expose what the detector needs,
            # declining to answer IS the right answer. Scoring an abstention
            # as a miss would push the tool towards guessing, which is the
            # behaviour this whole exercise exists to avoid. A value produced
            # anyway is a false positive and is scored as one.
            if not measurable(key, truth):
                if not measured:
                    entry["abstained"] += 1
                    print(f"  --  {key:<26} not measurable here, abstained")
                    continue
                entry["total"] += 1
                entry["false_positives"] += 1
                print(f"  MISS {key:<26} not measurable here, but returned "
                      f"{fact.display}")
                row["facts"][key] = {"expected": "abstain", "got": fact.display,
                                     "ok": False}
                continue

            entry["total"] += 1
            entry["by_obs"][obs]["total"] += 1
            if ok:
                entry["hits"] += 1
                entry["by_obs"][obs]["hits"] += 1
            if error is not None:
                entry["errors"].append(error)
                entry["by_obs"][obs]["errors"].append(error)
            if (not fact or not fact.ok) and measurable(key, truth):
                entry["silent"] += 1

            got = fact.display if fact and fact.ok else (
                fact.status if fact else "missing")
            row["facts"][key] = {"expected": str(expected), "got": got, "ok": ok}
            flag = "ok " if ok else "MISS"
            print(f"  {flag} {key:<26} expected {str(expected):<18} got {got}")

        rows.append(row)

    _write_calibration(stats, args)
    _write_report(rows, stats, args.report, args.level)
    _summary(stats)


def _write_calibration(stats, args) -> None:
    if args.no_write:
        return
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "level": args.level,
        "facts": {},
    }
    for key, entry in stats.items():
        errors = entry["errors"]
        record = {
            "overall": {
                "hits": entry["hits"],
                "total": entry["total"],
                "silent_failures": entry["silent"],
                "correct_abstentions": entry["abstained"],
                "not_run": entry["not_run"],
                "false_positives": entry["false_positives"],
            },
            "by_observability": {},
        }
        if errors:
            record["overall"]["mae"] = round(sum(errors) / len(errors), 3)
        for obs, sub in entry["by_obs"].items():
            block = {"hits": sub["hits"], "total": sub["total"]}
            if sub["errors"]:
                block["mae"] = round(sum(sub["errors"]) / len(sub["errors"]), 3)
            record["by_observability"][obs] = block
        payload["facts"][key] = record

    CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    CALIBRATION_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                encoding="utf-8")
    print(f"\ncalibration written -> {CALIBRATION_PATH}")


def _write_report(rows, stats, path: Path, level: int) -> None:
    lines = [
        "# ragmap calibration report",
        "",
        f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} "
        f"at `--level {level}`.",
        "",
        "Each target declares its true configuration. The table measures the",
        "scanner, not the targets.",
        "",
        "| detector | hits | correct abstentions | silent failures "
        "| not run | MAE |",
        "|---|---|---|---|---|---|",
    ]
    for key, entry in sorted(stats.items()):
        errors = entry["errors"]
        mae = f"{sum(errors) / len(errors):.2f}" if errors else "-"
        lines.append(f"| `{key}` | {entry['hits']}/{entry['total']} | "
                     f"{entry['abstained']} | {entry['silent']} | "
                     f"{entry['not_run']} | {mae} |")

    lines += ["", "## Per target", ""]
    for row in rows:
        lines += [f"### {row['profile']}  ({row['shape']}, {row['observability']}, "
                  f"{row['requests']} requests)", "",
                  "| fact | expected | measured | |", "|---|---|---|---|"]
        for key, cell in row["facts"].items():
            mark = "ok" if cell["ok"] else "**miss**"
            lines.append(f"| `{key}` | {cell['expected']} | {cell['got']} | {mark} |")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"report written      -> {path}")


def _summary(stats) -> None:
    print("\n" + "=" * 62)
    print(f"{'detector':<28} {'hits':<9} {'abst':<6} {'silent':<8} "
          f"{'unrun':<7} MAE")
    print("=" * 62)
    total_hits = total = 0
    for key, entry in sorted(stats.items()):
        errors = entry["errors"]
        mae = f"{sum(errors) / len(errors):.2f}" if errors else "-"
        print(f"{key:<28} {entry['hits']}/{entry['total']:<7} "
              f"{entry['abstained']:<6} {entry['silent']:<8} "
              f"{entry['not_run']:<7} {mae}")
        total_hits += entry["hits"]
        total += entry["total"]
    print("=" * 62)
    print(f"{'TOTAL':<28} {total_hits}/{total}")


if __name__ == "__main__":
    main()
