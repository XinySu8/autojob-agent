"""Command-line interface: `autojob <command>`."""

from __future__ import annotations

import argparse
import logging
import sys
import webbrowser
from pathlib import Path

from . import __version__
from .config import ConfigError, Workspace, init_workspace, load, validate
from .util import read_json


def _ws(args) -> Workspace:
    return load(args.config)


def _say(msg: str) -> None:
    print(msg, flush=True)


# ----------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------
def cmd_init(args) -> int:
    created = init_workspace(args.dir, force=args.force)
    root = Path(args.dir).resolve()
    if created:
        for p in created:
            _say(f"created {p}")
    else:
        _say(f"{root} already initialised (use --force to overwrite)")
    _say(f"\nNext:\n  1. Edit {root / 'profile.md'} – describe yourself (used for semantic matching)\n"
         f"  2. Edit {root / 'autojob.yaml'} – companies, keywords, locations\n"
         f"  3. cd {root} && autojob run")
    return 0


def cmd_fetch(args) -> int:
    from .fetch import fetch_all

    ws = _ws(args)
    _say(f"Fetching {len(ws.cfg['fetch']['targets'])} targets…")
    p = fetch_all(ws, progress=_say if args.verbose else None)
    _say(f"Fetched {p['fetched_count']} postings → {p['filtered_count']} internships "
         f"({p['count']} open, {p['today_count']} new today).")
    if p["errors"]:
        _say(f"{len(p['errors'])} warning(s):")
        for e in p["errors"]:
            _say(f"  ! {e}")
    return 0


def cmd_score(args) -> int:
    from .report import write_reports
    from .scoring import run_scoring

    ws = _ws(args)
    res = run_scoring(ws)
    c = res["meta"]["counts"]
    _say(f"Scored with '{res['meta']['semantic_backend']}': {c['apply']} apply / {c['maybe']} maybe / {c['skip']} skip")
    paths = write_reports(ws)
    _say(f"Report: {paths['html']}")
    return 0


def cmd_run(args) -> int:
    rc = cmd_fetch(args) or cmd_score(args)
    if rc == 0 and args.open:
        ws = _ws(args)
        webbrowser.open((ws.reports_dir / "dashboard.html").as_uri())
    return rc


def cmd_list(args) -> int:
    ws = _ws(args)
    doc = read_json(ws.scored_path, default={})
    if not doc:
        _say("No scores yet – run `autojob run` first.")
        return 1
    rows = [r for r in doc["jobs"] if r["bucket"] == args.bucket][: args.limit]
    if not rows:
        _say(f"No jobs in '{args.bucket}'.")
    for r in rows:
        _say(f"{r['score']:.2f}  {r['id'][:10]}  {r['company'][:14]:<14}  {r['title'][:60]:<60}  {(r.get('location') or '')[:30]}")
        if args.urls:
            _say(f"      {r['url']}")
    return 0


def cmd_mark(args) -> int:
    from .state import find_job, load_state, save_state, set_status

    ws = _ws(args)
    state = load_state(ws.state_path)
    jobs = read_json(ws.jobs_path, default={}).get("jobs", [])
    rc = 0
    for key in args.jobs:
        jid = find_job(state, key, jobs)
        if not jid:
            _say(f"✗ no job matches '{key}' (use a URL, or an id / id prefix from `autojob list`)")
            rc = 1
            continue
        rec = set_status(state, jid, args.status, args.note or "")
        _say(f"✓ {jid[:10]} {rec.get('company', '')} – {rec.get('title', '')} → {args.status}")
    save_state(ws.state_path, state)
    return rc


def cmd_cards(args) -> int:
    from .cards import generate_cards

    ws = _ws(args)
    counts = generate_cards(ws, model=args.model, limit=args.limit, force=args.force, progress=_say)
    _say(f"Cards: {counts['generated']} generated, {counts['skipped']} unchanged, {counts['failed']} failed → {ws.cards_dir}")
    return 1 if counts["failed"] else 0


def cmd_serve(args) -> int:
    from .server import serve

    ws = _ws(args)

    def pipeline():
        from .fetch import fetch_all
        from .report import write_reports
        from .scoring import run_scoring

        fetch_all(ws)
        run_scoring(ws)
        write_reports(ws)

    if args.open:
        webbrowser.open(f"http://{args.host}:{args.port}")
    serve(ws, args.host, args.port, pipeline)
    return 0


def cmd_doctor(args) -> int:
    ok = True
    _say(f"autojob {__version__}  python {sys.version.split()[0]}")
    try:
        ws = _ws(args)
        _say(f"✓ config   {ws.config_path}")
    except ConfigError as e:
        _say(f"✗ config   {e}")
        return 1
    for p in validate(ws.cfg):
        _say(f"! config   {p}")
    _say(("✓" if ws.profile_path.exists() else "✗") + f" profile  {ws.profile_path}")
    ok &= ws.profile_path.exists()
    try:
        import sentence_transformers  # noqa: F401
        _say("✓ semantic sentence-transformers installed")
    except ImportError:
        _say("· semantic sentence-transformers not installed → using built-in TF-IDF "
             "(optional: pip install 'autojob-agent[semantic]')")
    from urllib.request import urlopen
    try:
        urlopen(ws.cfg["cards"]["ollama_url"] + "/api/tags", timeout=2).close()
        _say(f"✓ ollama   reachable at {ws.cfg['cards']['ollama_url']}")
    except Exception:
        _say(f"· ollama   not reachable at {ws.cfg['cards']['ollama_url']} (only needed for `autojob cards`)")
    return 0 if ok else 1


# ----------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="autojob", description="Fetch, score and triage internship postings from company ATS boards.")
    p.add_argument("--version", action="version", version=f"autojob {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-c", "--config", help="path to autojob.yaml or its folder (default: search upward from cwd, or $AUTOJOB_CONFIG)")
    common.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<command>")

    s = sub.add_parser("init", help="create a workspace with starter config + profile")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("--force", action="store_true", help="overwrite existing files")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("run", parents=[common], help="fetch + score + report (the daily command)")
    s.add_argument("--open", action="store_true", help="open the HTML dashboard afterwards")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("fetch", parents=[common], help="fetch postings from all targets")
    s.set_defaults(fn=cmd_fetch)

    s = sub.add_parser("score", parents=[common], help="score + triage fetched jobs and write reports")
    s.set_defaults(fn=cmd_score)

    s = sub.add_parser("list", parents=[common], help="print ranked jobs in the terminal")
    s.add_argument("bucket", nargs="?", default="apply", choices=["apply", "maybe", "skip"])
    s.add_argument("-n", "--limit", type=int, default=30)
    s.add_argument("-u", "--urls", action="store_true", help="also print URLs")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("mark", parents=[common], help="mark jobs applied / ignored / closed / new")
    s.add_argument("status", choices=["applied", "ignored", "closed", "new"])
    s.add_argument("jobs", nargs="+", help="job URL, id, or id prefix (see `autojob list`)")
    s.add_argument("--note", default="")
    s.set_defaults(fn=cmd_mark)

    s = sub.add_parser("cards", parents=[common], help="generate job cards with a local Ollama model")
    s.add_argument("--model")
    s.add_argument("--limit", type=int)
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_cards)

    s = sub.add_parser("serve", parents=[common], help="local dashboard with mark-as-applied buttons")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--open", action="store_true")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("doctor", parents=[common], help="check config, profile and optional dependencies")
    s.set_defaults(fn=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if getattr(args, "verbose", False) else logging.WARNING,
                        format="%(levelname)s %(message)s")
    try:
        return args.fn(args)
    except (ConfigError, RuntimeError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
