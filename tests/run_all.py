#!/usr/bin/env python3
"""Run every offline test. No network, no running server, no fixtures.

    python tests/run_all.py

Each test is a plain script of asserts rather than a pytest suite, so the
only thing needed to run them is Python. They cover the parts of ragmap a
live scan cannot check for you:

    test_plan.py       the spend planner and the probe cache - a planner
                       that orphans a dependency, or a cache that replays a
                       rate-limited reply as evidence, both produce a
                       plausible-looking report that is wrong
    test_retry.py      the rate-limit paths - a per-minute limit must widen
                       pacing and a daily allowance must stop the scan,
                       and neither path runs unless a target refuses
    check_geometry.py  the chunk-size and overlap detectors, replayed
                       against the recorded AnythingLLM scan whose true
                       geometry (900 / 150) is known
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

SCRIPTS = ["test_plan.py", "test_retry.py", "check_geometry.py"]


def main() -> int:
    failed: list[str] = []
    for name in SCRIPTS:
        print(f"\n=== {name} " + "=" * (60 - len(name)), flush=True)
        result = subprocess.run([sys.executable, str(HERE / name)], cwd=ROOT)
        if result.returncode != 0:
            failed.append(name)

    print("\n" + "=" * 66, flush=True)
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    print(f"all {len(SCRIPTS)} test scripts passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
