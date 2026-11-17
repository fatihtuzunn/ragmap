"""Module contract and scheduler.

Every detector is a Module. The scheduler decides which ones run, in what
order, and what to do when one cannot.

Three rules the engine enforces:

1. **Dependencies are declared, not assumed.** A module names the facts it
   needs (``requires``) and the facts it produces (``provides``). Order is
   derived from that graph, so a detector never runs before the fact it
   depends on exists.

2. **A module that cannot run says so.** If a precondition is unmet the
   module is not executed and its facts are emitted with status
   ``not-applicable`` and a reason. Nothing disappears quietly: an operator
   must be able to tell "no overlap" from "overlap was never measurable".

3. **Writes need permission.** ``mutating = True`` modules refuse to run
   unless the caller passed explicit authorisation. Recon modules are all
   read-only; this is the gate future attack modules go through.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Iterable

from .model import ModuleOutcome
from .transport import BudgetExhausted

if TYPE_CHECKING:
    from .context import Context


class Module:
    name: str = ""
    section: str = "misc"
    phase: str = "recon"
    level: int = 1
    requires: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()
    cost: int = 0
    # How much a reader learns from this detector, 1 (marginal) to 10 (the
    # answer someone opened the report for). Paired with `cost` it is what
    # the planner spends a tight budget on: a detector is worth buying when
    # it tells you more per request than the one next to it. The numbers are
    # a judgement, and the module table prints them so the judgement can be
    # argued with.
    value: int = 3
    # Run again at the end of the scan, over everything that came back.
    # Only for detectors that take an inventory - where more evidence can
    # only add to the answer. A detector that makes a graded judgement from
    # a heuristic must not set this: given forty exchanges instead of six,
    # `observability.level` started reading prose in error-probe replies as
    # source attribution and promoted O0 targets to O1. More evidence made
    # it noisier, not better.
    resettle: bool = False
    mutating: bool = False
    description: str = ""

    def run(self, ctx: "Context") -> None:      # pragma: no cover - interface
        raise NotImplementedError

    def on_skip(self, ctx: "Context", status: str, reason: str) -> None:
        """Emit placeholder facts so the module is visible in the output."""
        for key in self.provides:
            ctx.skip_fact(key, status=status, reason=reason, module=self)


REGISTRY: list[type[Module]] = []


def register(cls: type[Module]) -> type[Module]:
    if not cls.name:
        raise ValueError(f"{cls.__name__} must define a name")
    REGISTRY.append(cls)
    return cls


def all_modules() -> list[Module]:
    return [cls() for cls in REGISTRY]


def _topological(modules: list[Module]) -> list[Module]:
    """Order modules so each runs after whatever produces its requirements."""
    producer: dict[str, str] = {}
    for module in modules:
        for key in module.provides:
            producer.setdefault(key, module.name)

    by_name = {m.name: m for m in modules}
    ordered: list[Module] = []
    state: dict[str, int] = {}      # 0 = visiting, 1 = done

    def visit(module: Module, trail: tuple[str, ...]) -> None:
        mark = state.get(module.name)
        if mark == 1:
            return
        if mark == 0:
            # Cycle: leave the order as-is rather than failing the scan.
            return
        state[module.name] = 0
        for key in module.requires:
            dependency = producer.get(key)
            if dependency and dependency != module.name and dependency in by_name:
                visit(by_name[dependency], trail + (module.name,))
        state[module.name] = 1
        ordered.append(module)

    # Stable starting order: by level, then declared cost, then name.
    for module in sorted(modules, key=lambda m: (m.level, m.cost, m.name)):
        visit(module, ())
    return ordered


def plan(modules: list[Module], budget: int) -> tuple[list[Module],
                                                      list[tuple[Module, int]]]:
    """Pick the most informative subset of `modules` that `budget` buys.

    Running in dependency order until the money ran out spent whatever
    happened to come first: a scan capped at 30 requests bought corpus
    discovery and stopped, and the operator got a report with no top-k in
    it. This buys by information density instead - value per request,
    counting the prerequisites a detector drags in with it - so a small
    budget returns the facts most worth having rather than the first ones
    alphabetically.

    Returns the chosen modules in dependency order, and the dropped ones
    each paired with the extra requests that would have bought it.
    """
    if budget <= 0:
        return _topological(modules), []

    producer = {key: m.name for m in modules for key in m.provides}
    by_name = {m.name: m for m in modules}

    def closure(module: Module, have: set[str]) -> list[Module]:
        """The module plus every prerequisite not already bought."""
        out: list[Module] = []
        seen: set[str] = set()

        def walk(node: Module) -> None:
            if node.name in seen or node.name in have:
                return
            seen.add(node.name)
            for key in node.requires:
                owner = producer.get(key)
                if owner and owner != node.name and owner in by_name:
                    walk(by_name[owner])
            out.append(node)

        walk(module)
        return out

    def fill(seed: Module | None) -> tuple[set[str], int, int]:
        """Buy greedily by density, optionally committing to `seed` first."""
        chosen: set[str] = set()
        spent = 0

        if seed is not None:
            group = closure(seed, chosen)
            cost = sum(m.cost for m in group)
            if cost > budget:
                return chosen, 0, 0
            chosen.update(m.name for m in group)
            spent = cost

        while True:
            best: tuple[float, int, list[Module]] | None = None
            for module in modules:
                if module.name in chosen:
                    continue
                group = closure(module, chosen)
                cost = sum(m.cost for m in group)
                if spent + cost > budget:
                    continue
                worth = sum(m.value for m in group)
                density = worth / cost if cost else float("inf")
                # Ties go to the cheaper group: it leaves more budget behind.
                if best is None or (density, -cost) > (best[0], -best[1]):
                    best = (density, cost, group)
            if best is None:
                break
            _, cost, group = best
            chosen.update(m.name for m in group)
            spent += cost

        worth = sum(m.value for m in modules if m.name in chosen)
        return chosen, spent, worth

    # Density alone is myopic: three cheap middling detectors can eat the
    # budget that a single expensive chain - corpus discovery, and the top-k
    # and threshold measurements that depend on it - needed to run at all,
    # and the operator gets a report with no retrieval parameters in it.
    # Committing to each detector in turn and filling around it costs
    # nothing at this size and reliably catches those chains.
    best_plan = fill(None)
    for module in modules:
        candidate = fill(module)
        if (candidate[2], -candidate[1]) > (best_plan[2], -best_plan[1]):
            best_plan = candidate
    chosen = best_plan[0]

    kept = [m for m in modules if m.name in chosen]
    dropped = []
    for module in modules:
        if module.name in chosen:
            continue
        need = sum(m.cost for m in closure(module, chosen))
        dropped.append((module, need))
    return _topological(kept), dropped


def select(modules: Iterable[Module], level: int,
           only: set[str] | None = None,
           skip: set[str] | None = None) -> tuple[list[Module], list[Module]]:
    """Split modules into (selected, excluded-by-level)."""
    chosen: list[Module] = []
    level_excluded: list[Module] = []

    def matches(patterns: set[str], name: str) -> bool:
        return any(name == p or name.startswith(p + ".") or p == name.split(".")[0]
                   for p in patterns)

    for module in modules:
        if only and not matches(only, module.name):
            continue
        if skip and matches(skip, module.name):
            continue
        if module.level > level:
            level_excluded.append(module)
            continue
        chosen.append(module)

    return _topological(chosen), level_excluded


def run_all(ctx: "Context", modules: list[Module]) -> None:
    for module in modules:
        if module.mutating and not ctx.config.allow_mutating:
            ctx.record_outcome(ModuleOutcome(
                module.name, "refused",
                "module performs writes; requires explicit authorisation"))
            module.on_skip(ctx, "not-applicable", "writes not authorised")
            continue

        missing = [key for key in module.requires if not ctx.satisfied(key)]
        if missing:
            reason = "needs " + ", ".join(missing)
            ctx.record_outcome(ModuleOutcome(module.name, "not-applicable", reason))
            module.on_skip(ctx, "not-applicable", reason)
            continue

        if module.cost and not ctx.transport.can_afford(module.cost):
            reason = (f"needs ~{module.cost} requests, "
                      f"{ctx.transport.remaining} left in budget")
            ctx.record_outcome(ModuleOutcome(module.name, "skipped-budget", reason))
            module.on_skip(ctx, "skipped-budget", reason)
            continue

        before = ctx.transport.used
        started = time.perf_counter()
        ctx.begin(module)
        try:
            module.run(ctx)
            status, reason = "ran", ""
        except BudgetExhausted as exc:
            # Running out of budget mid-module is an accounting outcome, not
            # a defect. Whatever it already wrote stays; the rest is marked.
            status, reason = "skipped-budget", str(exc)
            module.on_skip(ctx, "skipped-budget", reason)
        except Exception as exc:                      # noqa: BLE001
            status, reason = "error", f"{type(exc).__name__}: {exc}"
            module.on_skip(ctx, "error", reason)
        finally:
            ctx.end()

        ctx.record_outcome(ModuleOutcome(
            module.name, status, reason,
            requests=ctx.transport.used - before,
            seconds=round(time.perf_counter() - started, 2)))
