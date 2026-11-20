"""Command line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from . import opsec as opsec_mod
from .config import DEFAULT_LEVEL, DEFAULT_SPEND, SPEND_TIERS, ScanConfig
from .paths import PathSpec
from .output import jsonout, terminal
from .scanner import default_out_dir, replay, scan

BANNER = r"""

   ragmap {version}  -  RAG reconnaissance scanner
"""

EPILOG = """\
levels:
  1  interface, retrieval presence, observability, top-k, token channel
  2  + corpus discovery, coarse threshold, routing, error verbosity
  3  + chunk size, retrieval mode, cache, determinism, verbatim leak  (default)
  4  + chunk overlap, reranker, fine threshold
  5  + embedding behaviour, long-context probes

spend tiers (--spend sets a level and a request ceiling together):
  peek       12 requests, level 1   is it a RAG, and what shows from outside
  quick      35 requests, level 2   + corpus topics, top-k, threshold
  standard   90 requests, level 3   + chunk size, mode, verbatim leak (default)
  deep      220 requests, level 4   + chunk overlap, reranker, fine threshold
  max       700 requests, level 5   everything

  Within a tier the scan buys detectors by information density - value per
  request, prerequisites included - so a small budget returns the facts most
  worth having rather than whichever ones came first. --level and --budget
  override the tier. --tokens is a hard ceiling in tokens, read from the
  target's own usage counters where it reports them and estimated otherwise;
  pair it with your provider's allowance.

examples:
  ragmap -u http://127.0.0.1:8099/v1/chat/completions
  ragmap -u https://host/api/chat -H "Authorization: Bearer TOKEN" --spend deep
  ragmap -u https://host/api/chat --spend quick --tokens 20000
  ragmap -u https://host/api/chat --topic "data retention" --dump-chunks
  ragmap --replay ragmap-20261116-224103

Only scan systems you are authorised to test.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ragmap",
        description="Reconnaissance scanner for Retrieval-Augmented Generation systems.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)

    target = parser.add_argument_group("target")
    target.add_argument("-u", "--url", help="chat endpoint URL")
    target.add_argument("-H", "--header", action="append", default=[],
                        metavar="'K: V'", help="extra request header (repeatable)")
    target.add_argument("--cookie", help="Cookie header value")
    target.add_argument("--auth-bearer", metavar="TOKEN",
                        help="shorthand for Authorization: Bearer TOKEN")
    target.add_argument("--insecure", action="store_true",
                        help="do not verify TLS certificates")
    target.add_argument("--proxy", metavar="URL",
                        help="send every request through this proxy, "
                             "e.g. http://127.0.0.1:8080")
    target.add_argument("--vector-store", metavar="URL",
                        help="address of the vector database, when it is "
                             "not on the target's own host. Without this "
                             "ragmap tries the default ports of the host "
                             "already given; --skip store turns that off")
    target.add_argument("--model", default="ragmap",
                        help="model name to send in OpenAI-shaped bodies")

    scan_group = parser.add_argument_group("scan")
    scan_group.add_argument("--spend", choices=sorted(SPEND_TIERS),
                            default=DEFAULT_SPEND, metavar="TIER",
                            help="how much to spend: peek, quick, standard, "
                                 f"deep, max (default {DEFAULT_SPEND})")
    scan_group.add_argument("--level", type=int, choices=range(1, 6),
                            default=None, metavar="1-5",
                            help="detection depth; overrides the spend tier")
    scan_group.add_argument("--budget", type=int, default=0, metavar="N",
                            help="hard request ceiling; overrides the tier")
    scan_group.add_argument("--tokens", type=int, default=0, metavar="N",
                            dest="token_budget",
                            help="hard token ceiling, measured from the "
                                 "target's usage counters where it has them")
    scan_group.add_argument("--delay", type=float, default=0.5, metavar="SEC",
                            help="pause between requests (default 0.5)")
    scan_group.add_argument("--jitter", type=float, default=0.0, metavar="SEC",
                            help="randomise the pause by +/- this much, so "
                                 "the scan is not a straight line in the "
                                 "target's request log")
    scan_group.add_argument("--timeout", type=int, default=90, metavar="SEC")
    scan_group.add_argument("--only", default="", metavar="MOD[,MOD]",
                            help="run only these modules or module groups")
    scan_group.add_argument("--skip", default="", metavar="MOD[,MOD]",
                            help="skip these modules or module groups")
    scan_group.add_argument("--list-modules", action="store_true",
                            help="print the module table and exit")

    shape = parser.add_argument_group("shape overrides")
    shape.add_argument("--shape", help="force a request shape by name")
    shape.add_argument("--query-field", metavar="NAME",
                       help="field that carries the question")
    shape.add_argument("--source-path", metavar="PATH", default="",
                       help="where the retrieved passages are, as a dot "
                            "path with [] for an array, e.g. 'results[]' "
                            "or 'data.hits[]'")
    shape.add_argument("--answer-path", metavar="PATH", default="",
                       help="where the generated answer is")
    shape.add_argument("--text-path", metavar="PATH", default="",
                       help="passage text, within one source item")
    shape.add_argument("--title-path", metavar="PATH", default="",
                       help="document title, within one source item")
    shape.add_argument("--chunk-id-path", metavar="PATH", default="",
                       help="chunk identifier, within one source item")
    shape.add_argument("--doc-id-path", metavar="PATH", default="",
                       help="document identifier, within one source item")
    shape.add_argument("--score-path", metavar="PATH", default="",
                       help="similarity score, within one source item")
    shape.add_argument("--page-path", metavar="PATH", default="",
                       help="page or location, within one source item")

    opsec = parser.add_argument_group("opsec")
    opsec.add_argument("--rotate-every", type=int, default=0, metavar="N",
                       help="carry a session id in the body and change it "
                            "every N requests (off by default)")
    opsec.add_argument("--session-field", default="session_id",
                       metavar="NAME",
                       help="body field the session id goes in "
                            "(default session_id)")
    opsec.add_argument("--opsec-rules", metavar="FILE",
                       help="extra detection patterns, in the shape of "
                            "ragmap/data/opsec.json; merged with the "
                            "shipped ones")

    disco = parser.add_argument_group("discovery overrides")
    disco.add_argument("--topic", help="a subject known to be in the corpus")
    disco.add_argument("--second-topic", help="another in-corpus subject")
    disco.add_argument("--absent-topic", help="a subject known to be absent")
    disco.add_argument("--rare-token", help="a rare literal present in the corpus")
    disco.add_argument("--seed-queries", metavar="FILE",
                       help="file of discovery queries, one per line")

    out = parser.add_argument_group("output")
    out.add_argument("-oJ", "--json-out", metavar="FILE", help="write JSON report")
    out.add_argument("-oN", "--text-out", metavar="FILE", help="write text report")
    out.add_argument("-o", "--out-dir", metavar="DIR",
                     help="results directory (default ragmap-<timestamp>)")
    out.add_argument("--no-out-dir", action="store_true",
                     help="do not write anything to disk")
    out.add_argument("--dump-chunks", action="store_true",
                     help="print retrieved passages in full")
    out.add_argument("--max-chunk-chars", type=int, default=200, metavar="N",
                     help="terminal truncation width (default 200)")
    out.add_argument("--no-color", action="store_true")
    out.add_argument("-v", "--verbose", action="count", default=0)
    out.add_argument("--replay", metavar="DIR",
                     help="re-analyse a previous scan without sending requests")
    out.add_argument("--version", action="version",
                     version=f"ragmap {__version__}")
    return parser


def parse_headers(values: list[str], cookie: str | None,
                  bearer: str | None) -> dict:
    headers: dict[str, str] = {}
    for item in values:
        if ":" not in item:
            raise SystemExit(f"bad header (expected 'Name: value'): {item}")
        name, _, value = item.partition(":")
        headers[name.strip()] = value.strip()
    if cookie:
        headers["Cookie"] = cookie
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    return headers


def config_from_args(args) -> ScanConfig:
    seeds: list[str] = []
    if args.seed_queries:
        seeds = [line.strip() for line
                 in Path(args.seed_queries).read_text(encoding="utf-8").splitlines()
                 if line.strip()]

    out_dir = None
    if not args.no_out_dir and not args.replay:
        out_dir = Path(args.out_dir) if args.out_dir else default_out_dir(args.url)

    return ScanConfig(
        url=args.url or "",
        headers=parse_headers(args.header, args.cookie, args.auth_bearer),
        # The tier sets the depth unless the operator named one outright.
        level=(args.level if args.level is not None
               else SPEND_TIERS.get(args.spend, {}).get("level", DEFAULT_LEVEL)),
        budget=args.budget,
        token_budget=args.token_budget,
        spend=args.spend,
        delay=args.delay,
        jitter=args.jitter,
        timeout=args.timeout,
        verify_tls=not args.insecure,
        model=args.model,
        proxy=args.proxy,
        rotate_every=args.rotate_every,
        session_field=args.session_field,
        opsec_rules=Path(args.opsec_rules) if args.opsec_rules else None,
        only={s.strip() for s in args.only.split(",") if s.strip()},
        skip={s.strip() for s in args.skip.split(",") if s.strip()},
        shape=args.shape,
        query_field=args.query_field,
        vector_store=args.vector_store,
        paths=PathSpec(
            source_path=args.source_path, answer_path=args.answer_path,
            text_path=args.text_path, title_path=args.title_path,
            chunk_id_path=args.chunk_id_path, doc_id_path=args.doc_id_path,
            score_path=args.score_path, page_path=args.page_path),
        topic=args.topic,
        second_topic=args.second_topic,
        absent_topic=args.absent_topic,
        rare_token=args.rare_token,
        seed_queries=seeds,
        out_dir=out_dir,
        json_out=Path(args.json_out) if args.json_out else None,
        text_out=Path(args.text_out) if args.text_out else None,
        replay_dir=Path(args.replay) if args.replay else None,
        dump_chunks=args.dump_chunks,
        max_chunk_chars=args.max_chunk_chars,
        color=not args.no_color,
        verbosity=args.verbose,
    )


def list_modules() -> None:
    from .registry import all_modules
    rows = sorted(all_modules(), key=lambda m: (m.level, m.name))
    print(f"{'module':<24} {'lvl':<4} {'cost':<5} {'value':<6} {'v/req':<6} requires")
    print("-" * 94)
    for module in rows:
        requires = ", ".join(module.requires) or "-"
        density = (f"{module.value / module.cost:.2f}" if module.cost else "free")
        print(f"{module.name:<24} {module.level:<4} {module.cost:<5} "
              f"{module.value:<6} {density:<6} {requires}")
    print("\ncost is requests; value is how much a reader learns, 1-10.")
    print("A tight --budget buys the highest value per request first.")


def _warn_about_supplied_text(config: ScanConfig) -> None:
    """Check the operator's own words before any of them are sent.

    The footprint meter counts what the scan sent, which is the right unit
    for a report and the wrong one for a warning: by the time a probe value
    appears in the tally it is already in the target's logs. Anything the
    operator supplied is therefore checked up front, and only the
    categories that would be an escalation of scope are worth stopping for.
    """
    supplied = [value for value in (config.topic, config.second_topic,
                                    config.absent_topic, config.rare_token)
                if value]
    supplied += list(config.seed_queries)
    if not supplied:
        return

    meter = opsec_mod.load(config.opsec_rules)
    seen: set[str] = set()
    for text in supplied:
        for category in meter.check(text):
            # Only the categories that describe text ragmap would never
            # generate itself. A probe value matching a corpus-enumeration
            # pattern is the scan working as designed and belongs in the
            # footprint tally, not in a warning the operator must dismiss.
            if not category.operator_supplied:
                continue
            if category.name in seen:
                continue
            seen.add(category.name)
            print(f"[!] opsec: text you supplied matches a "
                  f"{category.name} rule ({category.severity}): "
                  f'"{text[:60]}"', file=sys.stderr)
            if category.advice:
                print(f"    {category.advice}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_modules:
        list_modules()
        return 0

    if not args.url and not args.replay:
        parser.error("either -u/--url or --replay is required")

    config = config_from_args(args)
    _warn_about_supplied_text(config)

    print(BANNER.format(version=__version__).rstrip())
    if config.replay_dir:
        print(f"[*] replay   {config.replay_dir}")
    else:
        print(f"[*] target   {config.url}")
        print(f"[*] level {config.level}  budget {config.effective_budget()}"
              f"  delay {config.delay}s")

    def on_event(kind: str, value: str) -> None:
        if kind == "module" and args.verbose:
            print(f"[>] {value}")
        elif kind == "shape":
            print(f"[*] shape detected: {value}")
        elif kind == "error":
            print(f"[!] {value}")

    try:
        result = replay(config) if config.replay_dir else scan(config, on_event=on_event)
    except KeyboardInterrupt:
        print("\n[!] interrupted", file=sys.stderr)
        return 2

    terminal.render(result, color=config.color, dump_chunks=config.dump_chunks,
                    max_chunk_chars=config.max_chunk_chars)

    if config.out_dir:
        jsonout.write(result, config.out_dir / "ragmap.json")
        # The same report the terminal just printed, without the colour
        # codes. A scan worth keeping is usually one someone else has to
        # read, and the JSON is for tooling rather than for reading.
        with (config.out_dir / "ragmap.txt").open("w", encoding="utf-8") as fh:
            terminal.render(result, color=False, dump_chunks=config.dump_chunks,
                            max_chunk_chars=config.max_chunk_chars, stream=fh)
    if config.json_out:
        jsonout.write(result, config.json_out)
    if config.text_out:
        config.text_out.parent.mkdir(parents=True, exist_ok=True)
        with config.text_out.open("w", encoding="utf-8") as handle:
            terminal.render(result, color=False, dump_chunks=config.dump_chunks,
                            max_chunk_chars=config.max_chunk_chars, stream=handle)

    return 1 if result.findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
