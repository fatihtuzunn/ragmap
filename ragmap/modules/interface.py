"""Level 1 - what we are talking to."""

from __future__ import annotations

from .. import findings, shapes
from ..context import Context
from ..registry import Module, register


@register
class InterfaceShape(Module):
    name = "interface.shape"
    section = "interface"
    level = 1
    cost = 3
    value = 6
    provides = ("iface.shape", "iface.answer_path", "iface.auth", "iface.model",
                "iface.product")
    description = "Detect request/response shape, auth, product"

    def run(self, ctx: Context) -> None:
        shape = ctx.shape
        if shape is None or not shape.detected:
            reason = ("endpoint requires authentication"
                      if shape is not None and shape.requires_auth
                      else "no candidate request shape produced an answer")
            for key in self.provides:
                ctx.skip_fact(key, status="not-applicable", reason=reason,
                              module=self)
            if shape is not None and shape.requires_auth:
                ctx.set_fact("iface.auth", "auth", True, display="required",
                             method="credential-less request rejected",
                             evidence=f"HTTP {shape.status}", kind="direct")
            return

        ctx.set_fact("iface.shape", "shape", shape.name, display=shape.name,
                     method="candidate request bodies tried until one answered",
                     evidence=_shape_evidence(shape), kind="direct")
        ctx.set_fact("iface.answer_path", "answer path", shape.answer_path_str,
                     display=shape.answer_path_str,
                     method="first extractable string field in the reply",
                     kind="direct")

        authed = bool(ctx.config.headers.get("Authorization")
                      or ctx.config.headers.get("authorization")
                      or any(k.lower() == "cookie" for k in ctx.config.headers))
        ctx.set_fact("iface.auth", "auth", authed,
                     display="supplied by operator" if authed else "none required",
                     method="credentials present in request configuration",
                     kind="direct")
        if not authed:
            ctx.add_finding(findings.make(
                "RAGMAP-010",
                "endpoint answered without credentials",
                evidence=f"HTTP {shape.status} with no Authorization header",
                facts=("iface.auth",)))

        if shape.model_name:
            ctx.set_fact("iface.model", "model", shape.model_name,
                         display=shape.model_name,
                         method="model field echoed in the response",
                         kind="direct")
        else:
            ctx.skip_fact("iface.model", status="not-applicable",
                          reason="response carries no model field", module=self)

        if shape.product_hints:
            ctx.set_fact("iface.product", "product",
                         shape.product_hints, display=", ".join(shape.product_hints),
                         method="product names matched in headers and body",
                         evidence=shape.server_header or "response body",
                         kind="heuristic")
        else:
            ctx.skip_fact("iface.product", status="not-applicable",
                          reason="no product fingerprint in headers or body",
                          module=self)


def _shape_evidence(shape) -> str:
    tried = len(shape.attempts)
    return f"{tried} shape{'s' if tried != 1 else ''} tried"


@register
class Streaming(Module):
    name = "interface.streaming"
    section = "interface"
    level = 1
    cost = 1
    value = 1
    requires = ("iface.shape",)
    provides = ("iface.streaming",)
    description = "Check whether the endpoint can stream"

    def run(self, ctx: Context) -> None:
        supported, evidence = shapes.check_streaming(ctx.transport, ctx.shape)
        ctx.set_fact("iface.streaming", "streaming", supported,
                     display="supported" if supported else "not supported",
                     method="same query requested with streaming enabled",
                     evidence=evidence, kind="direct")


@register
class TokenChannel(Module):
    name = "interface.tokens"
    section = "interface"
    level = 1
    cost = 0
    value = 2
    resettle = True
    requires = ("iface.shape",)
    provides = ("channel.tokens",)
    description = "Detect token accounting in responses"

    def run(self, ctx: Context) -> None:
        fields: list[str] = []
        for probe in ctx.probes:
            for field_name in probe.token_fields:
                if field_name not in fields:
                    fields.append(field_name)

        if not fields:
            ctx.set_fact("channel.tokens", "token counter", False,
                         display="not exposed",
                         method="token accounting fields searched in responses",
                         kind="direct")
            return

        ctx.set_fact("channel.tokens", "token counter", fields,
                     display=", ".join(fields[:3]),
                     method="token accounting fields present in responses",
                     evidence="context size is derivable from prompt tokens",
                     kind="direct")
        ctx.add_finding(findings.make(
            "RAGMAP-003",
            "prompt token counts returned to the caller",
            evidence=", ".join(fields[:5]),
            facts=("channel.tokens",)))
