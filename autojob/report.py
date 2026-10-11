"""Markdown digest of the latest run (used for the GitHub Actions run summary)."""

from __future__ import annotations

from .repository import Repository


def render_digest(repo: Repository, skip_limit: int = 30) -> str:
    run = repo.latest_run()
    if run is None:
        return "# AutoJob digest\n\n_No successful run yet._\n"
    c = run.counts
    out = [
        "# AutoJob digest", "",
        f"Run #{run.id} · {run.started_at:%Y-%m-%d %H:%M} UTC · {run.fetched} fetched → {run.matched} relevant "
        f"({run.new_jobs} new) → **{c.get('apply', 0)} apply / {c.get('maybe', 0)} maybe / {c.get('skip', 0)} skip**",
        "",
    ]
    if run.warnings:
        out += [f"<details><summary>{len(run.warnings)} fetch warning(s)</summary>", ""]
        out += [f"- {w}" for w in run.warnings] + ["", "</details>", ""]
    for bucket in ("apply", "maybe", "skip"):
        rows, total = repo.ranked(run, bucket=bucket, status="new", limit=skip_limit if bucket == "skip" else 500)
        out += [f"## {bucket.title()} ({total})", ""]
        for score, job in rows:
            hits = ", ".join(dict.fromkeys(score.hits.get("title", []) + score.hits.get("must", []) + score.hits.get("nice", [])))
            new = " 🆕" if job.first_seen_at >= run.started_at else ""
            out.append(f"- **{job.company}** · [{job.title}]({job.url}) · {job.location or 'n/a'}{new}")
            out.append(f"  - {score.score:.2f} · `{job.id[:10]}` · {score.reason if bucket == 'skip' else hits or '—'}")
        if total > len(rows):
            out.append(f"- _…and {total - len(rows)} more_")
        out.append("")
    return "\n".join(out)
