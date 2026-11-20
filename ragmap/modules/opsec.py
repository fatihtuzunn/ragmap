"""What this scan would look like in the target's monitoring.

The meter does the counting (see ``ragmap/opsec.py``); this turns the
tally into facts, so the scan's own noise is reported in the same place,
in the same shape, and with the same reticence as everything else it
measures.

It sends nothing. It runs again at the end of the scan, because the
footprint of a scan is only known once the scan is over - and because
every other free inventory detector does the same.

Nothing here is a finding. A finding describes the target; this describes
us. Confusing the two would put "ragmap asked four loud questions" in a
client's list of their own problems.
"""

from __future__ import annotations

from ..context import Context
from ..registry import Module, register


@register
class Footprint(Module):
    name = "opsec.footprint"
    section = "opsec"
    # Level 1: an operator deciding whether to go deeper wants to know what
    # the first few requests already cost them in visibility.
    level = 1
    cost = 0
    value = 4
    resettle = True
    requires = ("iface.shape",)
    provides = ("opsec.footprint", "opsec.pacing")
    description = "Count what the scan's own traffic would trip"

    def run(self, ctx: Context) -> None:
        meter = getattr(ctx.transport, "opsec", None)
        if meter is None or not meter.categories:
            for key in self.provides:
                ctx.skip_fact(key, status="not-applicable",
                              reason="no detection ruleset is loaded",
                              module=self)
            return

        self._footprint(ctx, meter)
        self._pacing(ctx)

    def _footprint(self, ctx: Context, meter) -> None:
        rows = meter.ranked()
        if not rows:
            ctx.set_fact(
                "opsec.footprint", "footprint", 0,
                display=f"clean over {meter.seen} queries", section="opsec",
                method="every query sent, matched against the shipped "
                       "detection patterns",
                kind="direct")
            return

        worst, worst_count = rows[0]
        ctx.set_fact(
            "opsec.footprint", "footprint", meter.total,
            display=meter.summary(), section="opsec",
            method="every query sent, matched against the shipped detection "
                   "patterns; rate-based rules counted only once their own "
                   "threshold was reached",
            evidence=f'worst: {worst.name} ({worst.severity}) '
                     f'x{worst_count}, e.g. "{meter.examples.get(worst.name, "")}"',
            kind="direct")

        if worst.advice:
            ctx.note(f"OPSEC: {worst_count} quer"
                     f"{'y' if worst_count == 1 else 'ies'} this scan sent "
                     f"would match a {worst.name} rule ({worst.severity}). "
                     f"{worst.advice}", key="opsec.worst")

    def _pacing(self, ctx: Context) -> None:
        transport = ctx.transport
        jitter = getattr(transport, "jitter", 0.0)
        rotations = getattr(transport, "rotations", 0)
        base = transport.base_delay

        parts = [f"{base:g}s" + (f" +-{jitter:g}s" if jitter else " fixed")]
        if rotations:
            parts.append(f"{rotations} session id rotations")
        if getattr(transport, "proxy", None):
            parts.append("through a proxy")

        ctx.set_fact(
            "opsec.pacing", "pacing", base, display=", ".join(parts),
            section="opsec",
            method="the pace this scan actually ran at",
            evidence=("a fixed interval is a straight line in a request log; "
                      "--jitter spreads it" if not jitter else ""),
            kind="direct")
