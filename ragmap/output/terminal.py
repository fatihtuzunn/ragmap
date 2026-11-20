"""Terminal report."""

from __future__ import annotations

import sys

from ..model import Fact, ScanResult

SECTIONS = [
    ("interface", "interface"),
    ("retrieval", "retrieval"),
    ("corpus", "corpus"),
    ("store", "vector store"),
    ("generation", "generation"),
    # Last on purpose: it describes the scan, not the target, and a reader
    # should reach the target's facts first.
    ("opsec", "opsec"),
]

LABEL_W = 18
VALUE_W = 26

SEVERITY_COLOR = {"high": "31", "medium": "33", "low": "36", "info": "37"}


class Printer:
    def __init__(self, color: bool = True, stream=None):
        self.stream = stream or sys.stdout
        self.color = color and getattr(self.stream, "isatty", lambda: False)()

    def paint(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def _safe_write(self, text: str) -> None:
        """Never let an un-encodable character kill a finished report.

        The console code page is not always UTF-8 - cp1254 on this machine -
        and passages echoed back from the target can contain anything at all.
        """
        stream = self.stream
        try:
            print(text, file=stream)
            return
        except UnicodeEncodeError:
            pass
        encoding = getattr(stream, "encoding", None) or "ascii"
        print(text.encode(encoding, "replace").decode(encoding, "replace"),
              file=stream)

    def line(self, text: str = "") -> None:
        self._safe_write(text)


def render(result: ScanResult, *, color: bool = True, dump_chunks: bool = False,
           max_chunk_chars: int = 200, stream=None) -> None:
    p = Printer(color, stream)

    p.line()
    for key, title in SECTIONS:
        facts = [f for f in result.facts.values() if f.section == key]
        if not facts:
            continue
        p.line(p.paint("[+] ", "32") + title)
        for fact in _ordered(facts):
            p.line(_fact_line(p, fact))
        p.line()

    _render_chunks(p, result, dump_chunks, max_chunk_chars)
    _render_findings(p, result)
    _render_notes(p, result)

    summary = (f"{len(result.findings)} finding"
               f"{'s' if len(result.findings) != 1 else ''} | "
               f"{result.requests_used} requests")
    if result.requests_saved:
        summary += f" (+{result.requests_saved} reused)"
    if result.tokens_used:
        label = "tokens" if result.tokens_measured else "tokens est."
        summary += f" | {result.tokens_used} {label}"
        if result.token_budget:
            summary += f"/{result.token_budget}"
    summary += f" | {_duration(result.duration_s)}"
    if result.out_dir_label:
        summary += f" | results -> {result.out_dir_label}"
    p.line(p.paint("[*] ", "34") + summary)


def _ordered(facts: list[Fact]) -> list[Fact]:
    measured = [f for f in facts if f.ok]
    other = [f for f in facts if not f.ok]
    return measured + other


VALUE_CAP = 52
EVIDENCE_CAP = 110


def _cap(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _fact_line(p: Printer, fact: Fact) -> str:
    # Truncate one short of the column so a long label can never run into
    # the value it belongs to.
    label = fact.label[:LABEL_W - 1].ljust(LABEL_W)
    value = _cap(fact.rendered(), VALUE_CAP)
    bits: list[str] = []
    if fact.ok:
        if fact.evidence:
            bits.append(_cap(fact.evidence, EVIDENCE_CAP))
        note = fact.confidence.render()
        if note:
            bits.append(note)
    elif fact.reason:
        bits.append(fact.reason)

    painted_value = value if fact.ok else p.paint(value, "90")
    pad = max(0, VALUE_W - len(value))
    tail = f"  [{' | '.join(bits)}]" if bits else ""
    if not fact.ok:
        tail = f"  {' | '.join(bits)}" if bits else ""
        tail = p.paint(tail, "90") if tail else ""
    return f"    {label}{painted_value}{' ' * pad}{tail}".rstrip()


def _render_chunks(p: Printer, result: ScanResult, dump: bool, width: int) -> None:
    if not result.chunks:
        return
    # A target at O2 names passages it will not show. Those are real
    # disclosures and the identifier detectors read them, but there is no
    # text to print, so they are counted here rather than listed as blanks.
    shown = [c for c in result.chunks if (c.text or "").strip()]
    named_only = len(result.chunks) - len(shown)
    if not shown:
        p.line(p.paint("[+] ", "32")
               + f"chunks ({named_only} named by the target, none shown)")
        p.line()
        return

    header = f"chunks ({len(shown)} observed"
    if named_only:
        header += f", {named_only} more named but not shown"
    header += ")" if dump else f", first {width} chars; --dump-chunks for full)"
    p.line(p.paint("[+] ", "32") + header)

    for index, chunk in enumerate(shown, start=1):
        meta = chunk.source_label
        if chunk.score is not None:
            meta += f"  score {chunk.score:.3f}"
        p.line(f"    [{index:02d}] {meta}")
        text = " ".join(chunk.text.split())
        if not dump and len(text) > width:
            text = text[:width] + "..."
        for wrapped in _wrap(text, 72):
            p.line(f"         {wrapped}")
    p.line()


def _render_findings(p: Printer, result: ScanResult) -> None:
    findings = result.sorted_findings()
    if not findings:
        p.line(p.paint("[*] ", "34") + "no findings")
        p.line()
        return
    p.line(p.paint("[!] ", "31") + "findings")
    for finding in findings:
        severity = p.paint(finding.severity.ljust(7),
                           SEVERITY_COLOR.get(finding.severity, "37"))
        p.line(f"    {finding.id}  {severity} {finding.title}")
        p.line(f"                         {finding.summary}")
    p.line()


def _render_notes(p: Printer, result: ScanResult) -> None:
    if not result.notes:
        return
    p.line(p.paint("[*] ", "34") + "notes")
    for note in result.notes:
        for i, wrapped in enumerate(_wrap(note, 72)):
            prefix = "    - " if i == 0 else "      "
            p.line(prefix + wrapped)
    p.line()


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            if current:
                lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines or [""]


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
