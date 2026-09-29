"""Stage 4 (optional, local): generate Markdown "job cards" with a local Ollama model."""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Workspace, template_text
from .util import read_json, sha1_text, utc_now, write_json, write_text

# Only these fields are sent to the model: keeps prompts short and evidence-bound.
_EVIDENCE_KEYS = ("id", "company", "title", "location", "url", "score", "reason", "hard", "jd_excerpt")


class OllamaError(RuntimeError):
    pass


def ollama_generate(base_url: str, model: str, prompt: str, timeout: int) -> str:
    """Call Ollama's HTTP API (works on every platform, unlike piping to `ollama run`,
    which prints spinner/ANSI codes and depends on the CLI being on PATH)."""
    body = json.dumps({"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.2}}).encode()
    req = Request(f"{base_url.rstrip('/')}/api/generate", data=body, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return (json.loads(resp.read().decode("utf-8")).get("response") or "").strip()
    except HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        if e.code == 404 and "model" in detail:
            raise OllamaError(f"model '{model}' not found – run: ollama pull {model}") from e
        raise OllamaError(f"Ollama HTTP {e.code}: {detail}") from e
    except (URLError, ConnectionError) as e:
        raise OllamaError(f"cannot reach Ollama at {base_url} – is `ollama serve` running? ({e})") from e


def _fmt_signals(c: dict) -> str:
    h = c.get("hard") or {}
    lines = [f"- must-have hits: {', '.join(h.get('must_hits') or []) or 'none'}",
             f"- nice-to-have hits: {', '.join(h.get('nice_hits') or []) or 'none'}",
             f"- negative hits: {', '.join(h.get('neg_hits') or []) or 'none'}"]
    return "\n".join(lines)


def build_prompt(rules: str, template: str, profile: str, c: dict) -> str:
    filled = template
    for k, v in {
        "title": c.get("title") or "Unknown title",
        "company": c.get("company") or "Unknown company",
        "job_uid": c.get("id"),
        "location": c.get("location") or "Not specified in evidence.",
        "url": c.get("url") or "Not specified in evidence.",
        "overall_score": f"{c.get('score', 0):.2f}",
        "hard_gate_summary": "No hard-gate hit.",
        "why_selected": c.get("reason") or "Not specified in evidence.",
        "jd_excerpt": c.get("jd_excerpt") or "Not specified in evidence.",
        "signals_dump": _fmt_signals(c),
    }.items():
        # str.replace instead of str.format: JD text containing "{" or "}" crashed format().
        filled = filled.replace("{" + k + "}", str(v))
    evidence = {k: c.get(k) for k in _EVIDENCE_KEYS}
    return (
        f"# SYSTEM RULES\n{rules}\n\n# USER PROFILE (evidence)\n{profile}\n\n"
        f"# CANDIDATE JSON (evidence)\n{json.dumps(evidence, ensure_ascii=False, indent=2)}\n\n"
        f"# TASK\nFill the Markdown template below. Do NOT add sections. Do NOT fabricate.\n\n# TEMPLATE\n{filled}\n"
    )


def generate_cards(
    ws: Workspace,
    model: str | None = None,
    limit: int | None = None,
    force: bool = False,
    generate: Callable[[str, str, str, int], str] = ollama_generate,
    progress: Callable[[str], None] = print,
) -> dict[str, int]:
    cc = ws.cfg["cards"]
    model = model or cc["model"]
    limit = cc["limit"] if limit is None else limit
    doc = read_json(ws.candidates_path, default={})
    if not doc:
        raise RuntimeError(f"{ws.candidates_path} not found – run `autojob score` first.")
    candidates = doc.get("candidates", [])
    if limit and limit > 0:
        candidates = candidates[:limit]

    rules, template, profile = template_text("card_prompt.md"), template_text("card_template.md"), ws.read_profile()
    index_path = ws.cards_dir / "index.json"
    index = read_json(index_path, default={"items": {}})
    profile_hash = sha1_text(profile)[:12]

    counts = {"generated": 0, "skipped": 0, "failed": 0}
    for c in candidates:
        cid = c["id"]
        out = ws.cards_dir / f"{cid}.md"
        # Regenerate when the posting, the profile or the model changes.
        key = sha1_text(json.dumps([c.get("jd_excerpt"), c.get("title"), profile_hash, model]))[:16]
        if not force and out.exists() and index["items"].get(cid, {}).get("key") == key:
            counts["skipped"] += 1
            continue
        try:
            md = generate(cc["ollama_url"], model, build_prompt(rules, template, profile, c), int(cc["timeout"]))
            write_text(out, md + "\n")
            index["items"][cid] = {"key": key, "model": model, "updated_at": utc_now().isoformat(), "file": out.name}
            counts["generated"] += 1
            progress(f"  ✓ {c.get('company')} – {c.get('title')}")
        except OllamaError as e:
            counts["failed"] += 1
            progress(f"  ✗ {c.get('company')} – {c.get('title')}: {e}")
            if "cannot reach" in str(e) or "not found" in str(e):
                break  # no point trying the rest
    write_json(index_path, index)
    return counts
