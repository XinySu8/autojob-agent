"""Command-line interface: `autojob <command>`."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, Workspace, init_workspace, load, validate
from .repository import NotFound, Repository


def _say(msg: str = "") -> None:
    print(msg, flush=True)


def _ws(args) -> Workspace:
    return load(args.config)


def cmd_init(args) -> int:
    root = Path(args.dir).resolve()
    created = init_workspace(root, force=args.force)
    for p in created:
        _say(f"created {p}")
    if not created:
        _say(f"{root} already initialised (use --force to overwrite)")
    _say(f"\nNext: edit {root / 'profile.md'} and {root / 'autojob.yaml'}, then `cd {root} && autojob run`")
    return 0


def cmd_run(args) -> int:
    from .pipeline import Pipeline

    ws = _ws(args)
    _say(f"Fetching {len(ws.cfg['fetch']['targets'])} targets…")
    run = Pipeline(ws, ws.open_db(), progress=_say if args.verbose else None).run()
    c = run.counts
    _say(f"Run #{run.id}: {run.fetched} postings → {run.matched} relevant ({run.new_jobs} new) → "
         f"{c.get('apply', 0)} apply / {c.get('maybe', 0)} maybe / {c.get('skip', 0)} skip  [semantic: {run.semantic_backend}]")
    for w in run.warnings:
        _say(f"  ! {w}")
    return 0


def cmd_list(args) -> int:
    ws = _ws(args)
    with ws.open_db().session() as s:
        repo = Repository(s)
        run = repo.latest_run()
        if run is None:
            _say("No runs yet – run `autojob run` first.")
            return 1
        rows, total = repo.ranked(run, bucket=args.bucket, status="new", limit=args.limit)
        for score, job in rows:
            verdict = f" agent:{job.review.verdict}" if job.review and not job.review.fallback else ""
            _say(f"{score.score:.2f}  {job.id[:10]}  {job.company[:14]:<14}  {job.title[:58]:<58}  {job.location[:28]}{verdict}")
            if args.urls:
                _say(f"      {job.url}")
        _say(f"({len(rows)} of {total} in '{args.bucket}')")
    return 0


def cmd_mark(args) -> int:
    """`mark` sets your status; `label` records the correct bucket for evaluation."""
    ws = _ws(args)
    rc = 0
    with ws.open_db().session() as s:
        repo = Repository(s)
        for key in args.jobs:
            try:
                job = repo.find_job(key)
            except NotFound:
                _say(f"✗ no job matches '{key}' (use a URL, id or id prefix from `autojob list`)")
                rc = 1
                continue
            if args.cmd == "mark":
                repo.set_decision(job.id, status=args.value, note=args.note)
            else:
                repo.set_decision(job.id, label=args.value, note=args.note)
            _say(f"✓ {job.id[:10]} {job.company} – {job.title} → {args.value}")
    return rc


def cmd_review(args) -> int:
    from .agent import JobAgent
    from .pipeline import Pipeline

    ws = _ws(args)
    agent = JobAgent.from_config(ws.cfg, model=args.model)
    job_id = None
    db = ws.open_db()
    if args.job:
        with db.session() as s:
            job_id = Repository(s).find_job(args.job).id
    _say(f"Reviewing with {agent.model_name}…")
    counts = Pipeline(ws, db, progress=_say).review(agent, limit=args.limit, job_id=job_id, force=args.force)
    _say(f"Done: {counts}")
    return 0


def cmd_eval(args) -> int:
    from .evaluation import evaluate

    ws = _ws(args)
    with ws.open_db().session() as s:
        repo = Repository(s)
        run = repo.latest_run()
        rows = repo.labeled(run) if run else []
        if not rows:
            _say("No labeled jobs yet. Label some with `autojob label apply|maybe|skip <id>` or in the web UI.")
            return 1
        results = evaluate(rows)
        ks = list(results[0].precision_at)
        _say(f"{len(rows)} labeled jobs ({sum(1 for _s, j in rows if j.decision.label == 'apply')} labeled apply)\n")
        _say(f"{'system':<16}" + "".join(f"{'P@' + str(k):>8}" for k in ks) + f"{'bucket acc':>12}")
        fmt = lambda v: f"{v:.2f}" if v is not None else "–"  # noqa: E731
        for r in results:
            extra = f"   (agent coverage {r.agent_coverage:.0%})" if r.agent_coverage is not None else ""
            _say(f"{r.name:<16}" + "".join(f"{fmt(r.precision_at[k]):>8}" for k in ks) + f"{fmt(r.bucket_accuracy):>12}{extra}")
    return 0


def cmd_digest(args) -> int:
    from .report import render_digest

    ws = _ws(args)
    with ws.open_db().session() as s:
        text = render_digest(Repository(s))
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        _say(text)
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from .api import STATIC_DIR, create_app

    ws = _ws(args)
    if not (STATIC_DIR / "index.html").exists():
        _say("Note: web UI not built (cd web && npm install && npm run build). Serving the API only – see /docs.")
    _say(f"AutoJob: http://{args.host}:{args.port}")
    uvicorn.run(create_app(ws), host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_doctor(args) -> int:
    _say(f"autojob {__version__}  python {sys.version.split()[0]}")
    try:
        ws = _ws(args)
    except ConfigError as e:
        _say(f"✗ config   {e}")
        return 1
    _say(f"✓ config   {ws.config_path}")
    for p in validate(ws.cfg):
        _say(f"! config   {p}")
    ok = ws.profile_path.exists()
    _say(("✓" if ok else "✗") + f" profile  {ws.profile_path}")
    try:
        ws.open_db()
        _say(f"✓ database {ws.database_url.split('@')[-1]}")
    except Exception as e:
        _say(f"✗ database {e}")
        ok = False
    for mod, extra, purpose in (("sentence_transformers", "semantic", "better semantic matching"),
                                ("langchain_ollama", "agent", "AI agent review")):
        try:
            __import__(mod)
            _say(f"✓ {extra:<8} installed")
        except ImportError:
            _say(f"· {extra:<8} not installed – optional, for {purpose}: pip install 'autojob-agent[{extra}]'")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="autojob", description="Fetch, rank and review internship postings.")
    p.add_argument("--version", action="version", version=f"autojob {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-c", "--config", help="autojob.yaml or its folder (default: search upward, or $AUTOJOB_CONFIG)")
    common.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<command>")

    s = sub.add_parser("init", help="create a workspace with starter config + profile")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)

    sub.add_parser("run", parents=[common], help="fetch all boards and score (the daily command)").set_defaults(fn=cmd_run)

    s = sub.add_parser("list", parents=[common], help="print ranked jobs from the latest run")
    s.add_argument("bucket", nargs="?", default="apply", choices=["apply", "maybe", "skip"])
    s.add_argument("-n", "--limit", type=int, default=30)
    s.add_argument("-u", "--urls", action="store_true")
    s.set_defaults(fn=cmd_list)

    for name, choices, help_ in (("mark", ["applied", "ignored", "closed", "new"], "set your status for jobs"),
                                 ("label", ["apply", "maybe", "skip"], "record the correct bucket (for `autojob eval`)")):
        s = sub.add_parser(name, parents=[common], help=help_)
        s.add_argument("value", choices=choices)
        s.add_argument("jobs", nargs="+", help="job URL, id or id prefix")
        s.add_argument("--note")
        s.set_defaults(fn=cmd_mark)

    s = sub.add_parser("review", parents=[common], help="AI agent review of top jobs (needs Ollama)")
    s.add_argument("--job", help="review a single job (id, prefix or URL)")
    s.add_argument("--limit", type=int)
    s.add_argument("--model")
    s.add_argument("--force", action="store_true", help="re-review even if nothing changed")
    s.set_defaults(fn=cmd_review)

    sub.add_parser("eval", parents=[common], help="precision@k of each ranker against your labels").set_defaults(fn=cmd_eval)

    s = sub.add_parser("digest", parents=[common], help="Markdown summary of the latest run")
    s.add_argument("-o", "--output")
    s.set_defaults(fn=cmd_digest)

    s = sub.add_parser("serve", parents=[common], help="web UI + REST API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)

    sub.add_parser("doctor", parents=[common], help="check config, database and optional extras").set_defaults(fn=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if getattr(args, "verbose", False) else logging.WARNING,
                        format="%(levelname)s %(message)s")
    try:
        return args.fn(args)
    except (ConfigError, RuntimeError, ValueError, NotFound) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
