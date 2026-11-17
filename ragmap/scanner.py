"""Scan orchestration: shape detection, module scheduling, result assembly."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from . import modules as _modules  # noqa: F401  (registers detectors)
from . import shapes
from .config import ScanConfig
from .context import Context
from .model import ModuleOutcome, ScanResult
from .registry import all_modules, plan, run_all, select
from .transport import Transport, probe_from_record


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def scan(config: ScanConfig, *, on_event=None) -> ScanResult:
    emit = on_event or (lambda *a, **k: None)
    started = time.perf_counter()

    out_dir = config.out_dir
    raw_dir = (out_dir / "raw") if out_dir else None

    transport = Transport(
        url=config.url, headers=config.headers, model=config.model,
        timeout=config.timeout, delay=config.delay,
        budget=config.effective_budget(), verify_tls=config.verify_tls,
        raw_dir=raw_dir, token_budget=config.token_budget,
    )
    ctx = Context(config, transport)

    emit("phase", "detecting request shape")
    ctx.shape = shapes.detect(transport, forced=config.shape,
                              query_field=config.query_field)

    if ctx.shape.detected:
        transport.body_template = ctx.shape.body_template
        emit("shape", ctx.shape.name)
        # Detection probes go out before a Context exists, so the successful
        # one is folded back in. Otherwise passive detectors (token channel,
        # product fingerprint) would never see the first real response.
        if ctx.shape.probe is not None:
            ctx.probes.append(ctx.shape.probe)
            ctx.harvest(ctx.shape.probe)
    else:
        if ctx.shape.requires_auth:
            reason = "endpoint requires authentication"
            advice = ("Supply credentials with --auth-bearer, --cookie "
                      "or -H before scanning.")
        elif ctx.shape.blocked:
            reason = f"target returned an error: {ctx.shape.blocked[:160]}"
            advice = ("The target is failing upstream rather than rejecting "
                      "the request format. Raise --delay and rescan; the "
                      "request shape was never in question.")
        else:
            reason = "no candidate request shape produced an answer"
            advice = ("Pass --shape or --query-field to drive the request "
                      "format manually.")
        emit("error", reason)
        ctx.note(f"Shape detection failed: {reason}. {advice}")

    selected, level_excluded = select(all_modules(), config.level,
                                      config.only or None, config.skip or None)

    for module in level_excluded:
        ctx.record_outcome(ModuleOutcome(
            module.name, "skipped-level", f"requires --level {module.level}"))
        module.on_skip(ctx, "skipped-level", f"needs --level {module.level}")

    # Shape detection has now paid for a few real exchanges, so the cost of
    # a request against THIS target is known rather than assumed. That is
    # what turns a token allowance into a request budget worth planning
    # against: a top-k of 12 over 1200-character chunks costs four times
    # what a terse O0 endpoint does, and guessing either way wastes the
    # operator's allowance or cuts the scan short.
    def affordable_now() -> int:
        """How many more requests both ceilings leave room for."""
        room = transport.remaining
        if config.token_budget and transport.tokens_per_request:
            by_tokens = int((config.token_budget - transport.tokens_used)
                            / transport.tokens_per_request)
            room = max(0, min(room, by_tokens))
        return room

    affordable = affordable_now()
    if config.token_budget and transport.tokens_per_request:
        if affordable < transport.remaining:
            ctx.note(f"A token ceiling of {config.token_budget} buys about "
                     f"{affordable} more requests at the "
                     f"{transport.tokens_per_request:.0f} tokens this target "
                     f"has charged per exchange"
                     + ("" if transport.tokens_measured else
                        " (estimated; the target reports no usage counters)")
                     + ". The scan is planned to that, not to --budget.")

    def spend(pool: list, allowance: int) -> list:
        """Run what `allowance` buys from `pool`; return what it did not."""
        bought, priced_out = plan(pool, allowance)
        for index, module in enumerate(bought):
            # A daily or monthly allowance cannot be waited out inside a
            # scan. Carrying on would collect one reply every couple of
            # minutes until the budget ran out, so the rest are marked unrun
            # rather than left to report "not applicable" about a target
            # nobody managed to measure.
            if transport.exhausted:
                reason = "the target's request allowance ran out"
                for pending in bought[index:]:
                    ctx.record_outcome(ModuleOutcome(
                        pending.name, "skipped-budget", reason))
                    pending.on_skip(ctx, "skipped-budget", reason)
                return []
            emit("module", module.name)
            run_all(ctx, [module])
        return [m for m, _ in priced_out]

    # Declared costs are ceilings, and most detectors come in under them, so
    # a single pass leaves budget on the table - on one run here, a third of
    # the operator's token allowance went unspent while three detectors sat
    # marked "priced out". Re-planning against what is actually left buys
    # some of them back. Two passes is enough; the third rarely finds
    # anything and every pass is free.
    leftover = spend(selected, affordable)
    for _ in range(2):
        if not leftover or transport.exhausted:
            break
        still_left = affordable_now()
        if still_left < min(m.cost for m in leftover):
            break
        regained = spend(leftover, still_left)
        if len(regained) == len(leftover):
            break
        leftover = regained

    _resettle(ctx, selected)

    for module in leftover:
        reason = (f"needs ~{module.cost} requests; what was left after the "
                  f"higher-value detectors did not cover it")
        ctx.record_outcome(ModuleOutcome(module.name, "skipped-budget", reason))
        module.on_skip(ctx, "skipped-budget", reason)
    if leftover:
        names = ", ".join(m.name for m in leftover[:4])
        extra = sum(m.cost for m in leftover)
        ctx.note(f"{len(leftover)} detector(s) were priced out of this "
                 f"budget: {names}"
                 + (" and others" if len(leftover) > 4 else "")
                 + f". About {extra} more requests would buy them; raise "
                 f"--budget, --tokens, or --spend.")

    # A scan that spent itself on refusals produces thin facts for a reason
    # that has nothing to do with the target's retrieval. Say so, rather than
    # leaving the operator to read "not applicable" as a property of the
    # system under test.
    if transport.exhausted:
        ctx.note(f"The scan stopped after {transport.used} requests: the "
                 f"target refused on a daily or monthly allowance, which no "
                 f"amount of waiting wins back inside one scan. The target "
                 f"said: {transport.exhausted[:200]}. Nothing reported here "
                 f"describes the system under test beyond the point it "
                 f"stopped answering - rescan once the allowance resets, or "
                 f"against a backend without one.")
    elif transport.throttled:
        ctx.note(f"The target rate limited {transport.throttled} of "
                 f"{transport.used} requests; pacing widened from "
                 f"{transport.base_delay:.0f}s to {transport.delay:.0f}s "
                 f"between requests. Facts marked not applicable may simply "
                 f"have run out of budget - rescan with a larger --delay or "
                 f"--budget before concluding anything from them.")

    return _assemble(ctx, config, started, transport)


def replay(config: ScanConfig) -> ScanResult:
    """Re-run analysis over a previous scan's raw recordings.

    Modules that would send requests are not re-run; what changes is how the
    recorded exchanges are interpreted. Useful when a detector is fixed after
    an engagement, since the client's system is never touched again.
    """
    started = time.perf_counter()
    raw_dir = config.replay_dir / "raw" if (config.replay_dir / "raw").is_dir() \
        else config.replay_dir

    transport = Transport(url=config.url or "(replay)", budget=0)
    ctx = Context(config, transport)

    files = sorted(raw_dir.glob("*.json"))
    for path in files:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        probe = probe_from_record(record)
        ctx.probes.append(probe)
        ctx.harvest(probe)

    ctx.note(f"Replayed {len(files)} recorded exchanges; no requests were sent.")

    # Shape detection cannot re-run offline, but the recordings already say
    # which shape worked. Without this, every module that depends on the
    # interface is blocked and a replay produces nothing.
    first = next((p for p in ctx.probes if p.answer), None)
    if first is not None:
        ctx.set_fact("iface.shape", "shape", "recorded",
                     display="from recording", section="interface",
                     method="request shape read back from the saved exchange",
                     kind="direct")
        ctx.set_fact("iface.answer_path", "answer path",
                     _path_str(first.answer_path),
                     display=_path_str(first.answer_path), section="interface",
                     method="answer located in the recorded response",
                     kind="direct")

    # Only passive modules can run offline: anything that needs to send a
    # query is reported as not-applicable rather than silently skipped.
    selected, _ = select(all_modules(), config.level,
                         config.only or None, config.skip or None)
    for module in selected:
        if module.cost == 0:
            run_all(ctx, [module])
        else:
            ctx.record_outcome(ModuleOutcome(
                module.name, "not-applicable", "replay mode sends no requests"))
            module.on_skip(ctx, "not-applicable", "replay sends no requests")

    result = _assemble(ctx, config, started, transport)
    result.target = config.replay_dir.name
    return result


def _resettle(ctx: Context, selected: list) -> None:
    """Re-run the detectors that cost nothing, once everything has been seen.

    A zero-cost detector reads evidence other modules' requests brought
    back, and running it at its place in the dependency order showed it only
    what had arrived by then. Against a live AnythingLLM that produced two
    contradictions in one report: the token channel was called "not exposed"
    while the scan was metering itself on the target's own token counts, and
    the document list said two while the passage list printed five. The
    first exchange of the scan had retrieved nothing, so it carried no
    counters and named no documents, and the detectors that read it never
    looked again.

    These modules send nothing, so a second run is free. Facts are
    overwritten and findings deduplicate by id, so the only thing that
    changes is that the summary describes the whole scan rather than its
    first minute.
    """
    ran = {outcome.name for outcome in ctx.outcomes if outcome.status == "ran"}
    for module in selected:
        if not module.resettle or module.cost or module.name not in ran:
            continue
        ctx.begin(module)
        try:
            module.run(ctx)
        except Exception:                             # noqa: BLE001
            # The first run's facts stand; a failure here changes nothing.
            pass
        finally:
            ctx.end()


def _assemble(ctx: Context, config: ScanConfig, started: float,
              transport: Transport) -> ScanResult:
    result = ScanResult(
        target=config.url,
        level=config.level,
        started_at=_stamp(),
        finished_at=_stamp(),
        duration_s=time.perf_counter() - started,
        requests_used=transport.used,
        budget=transport.budget,
        spend=config.spend,
        tokens_used=transport.tokens_used,
        tokens_measured=transport.tokens_measured,
        token_budget=transport.token_budget,
        requests_saved=ctx.reused,
        facts=ctx.facts,
        findings=ctx.findings,
        chunks=list(ctx.chunks.items),
        modules=ctx.outcomes,
        notes=ctx.notes,
    )
    if config.out_dir:
        result.out_dir_label = str(config.out_dir)
    if transport.rate_limit:
        pairs = ", ".join(f"{k}={v}" for k, v in
                          list(transport.rate_limit.items())[:3])
        ctx.note(f"Target advertised rate limits: {pairs}")
        result.notes = ctx.notes
    if transport.used >= transport.budget > 0:
        ctx.note(f"Request budget ({transport.budget}) was exhausted; some "
                 f"detectors were skipped. Raise it with --budget.")
        result.notes = ctx.notes
    return result


def default_out_dir(url: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(f"ragmap-{stamp}")


def _path_str(path) -> str:
    if not path:
        return ""
    out = ""
    for step in path:
        out += f"[{step}]" if isinstance(step, int) else ("." if out else "") + str(step)
    return out
