"""Stage 3: human-readable outputs (Markdown digest + self-contained HTML dashboard)."""

from __future__ import annotations

import json
from pathlib import Path

from .config import Workspace, template_text
from .state import load_state
from .util import read_json, write_text


def _md_item(r: dict) -> str:
    hits = ", ".join(dict.fromkeys(r["hard"].get("title_hits", []) + r["hard"]["must_hits"] + r["hard"]["nice_hits"])) or "—"
    neg = ", ".join(r["hard"]["neg_hits"])
    lines = [
        f"- **{r.get('company')}** · [{r.get('title')}]({r.get('url')}) · {r.get('location') or 'n/a'}",
        f"  - score {r['score']:.2f} (keywords {r['hard']['norm']:.2f}, semantic {r['semantic']['norm']:.2f}) · id `{r['id'][:10]}`",
        f"  - matched: {hits}" + (f" · negative: {neg}" if neg else ""),
    ]
    if r.get("bucket") == "skip":
        lines.append(f"  - reason: {r.get('reason')}")
    return "\n".join(lines)


def render_markdown(scored: dict, jobs_doc: dict, skip_limit: int = 100) -> str:
    meta = scored["meta"]
    by_bucket: dict[str, list] = {"apply": [], "maybe": [], "skip": []}
    for r in scored["jobs"]:
        by_bucket[r["bucket"]].append(r)
    c = meta["counts"]
    out = [
        "# AutoJob digest",
        "",
        f"Generated {meta['generated_at_utc'][:16].replace('T', ' ')} UTC · "
        f"{jobs_doc.get('fetched_count', '?')} fetched → {jobs_doc.get('count', '?')} open internships → "
        f"**{c['apply']} apply / {c['maybe']} maybe / {c['skip']} skip** · semantic backend: {meta['semantic_backend']}",
        "",
    ]
    if jobs_doc.get("errors"):
        out += ["<details><summary>Fetch warnings (%d)</summary>\n" % len(jobs_doc["errors"])]
        out += [f"- {e}" for e in jobs_doc["errors"]]
        out += ["", "</details>", ""]
    for name in ("apply", "maybe"):
        out += [f"## {name.title()} ({len(by_bucket[name])})", ""]
        out += [_md_item(r) for r in by_bucket[name]] or ["_None._"]
        out.append("")
    skip = by_bucket["skip"]
    out += [f"## Skip ({len(skip)})", ""]
    out += [_md_item(r) for r in skip[:skip_limit]] or ["_None._"]
    if len(skip) > skip_limit:
        out.append(f"\n_…and {len(skip) - skip_limit} more (see scored.json)._")
    return "\n".join(out) + "\n"


def dashboard_payload(ws: Workspace) -> dict:
    scored = read_json(ws.scored_path, default={})
    jobs_doc = read_json(ws.jobs_path, default={})
    state = load_state(ws.state_path).get("jobs", {})
    ids = {r["id"] for r in scored.get("jobs", [])}
    return {
        "status": {i: state[i]["status"] for i in ids if i in state and state[i].get("status", "new") != "new"},
        "meta": scored.get("meta", {}),
        "fetch": {k: jobs_doc.get(k) for k in ("generated_at_utc", "fetched_count", "count", "today_utc", "errors")},
        "jobs": scored.get("jobs", []),
    }


def render_html(payload: dict, live: bool = False) -> str:
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return (
        template_text("dashboard.html")
        .replace("/*__DATA__*/null", data)
        .replace("/*__LIVE__*/false", "true" if live else "false")
    )


def write_reports(ws: Workspace) -> dict[str, Path]:
    scored = read_json(ws.scored_path, default={})
    if not scored:
        raise RuntimeError(f"{ws.scored_path} not found – run `autojob score` first.")
    jobs_doc = read_json(ws.jobs_path, default={})
    md_path = ws.reports_dir / "digest.md"
    html_path = ws.reports_dir / "dashboard.html"
    write_text(md_path, render_markdown(scored, jobs_doc))
    write_text(html_path, render_html(dashboard_payload(ws)))
    return {"markdown": md_path, "html": html_path}
