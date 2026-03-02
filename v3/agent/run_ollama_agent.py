# v3/agent/run_ollama_agent.py
import argparse
import json
import re
import subprocess
import sys
import hashlib
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]  # repo root

# Inputs produced by v2
DEFAULT_CANDIDATES = ROOT / "v2" / "output" / "candidates.json"
DEFAULT_PROFILE = ROOT / "v2" / "config" / "profile.md"

# v3-owned assets + outputs
DEFAULT_PROMPT_RULES = ROOT / "v3" / "agent" / "agent_prompt.md"
DEFAULT_TEMPLATE = ROOT / "v3" / "agent" / "card_template.md"
DEFAULT_CARDS_DIR = ROOT / "v3" / "cards"
DEFAULT_INDEX = ROOT / "v3" / "agent" / ".cache" / "card_index.json"


def read_text(path: Path) -> str:
    # utf-8-sig will transparently handle files that start with a UTF-8 BOM
    return path.read_text(encoding="utf-8-sig")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_json(path: Path):
    return json.loads(read_text(path))


def dump_json(path: Path, obj) -> None:
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2))


def safe_get(d: dict, keys, default=""):
    cur = d
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur if cur is not None else default


def normalize_filename(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)


def compute_text_hash(candidate: dict) -> str:
    basis = {
        "job_uid": safe_get(candidate, ["job_uid"], safe_get(candidate, ["uid"], "")),
        "title": safe_get(candidate, ["title"], ""),
        "company": safe_get(candidate, ["company"], ""),
        "jd_excerpt": safe_get(candidate, ["jd_excerpt"], safe_get(candidate, ["excerpt"], "")),
        "signals": safe_get(candidate, ["signals"], safe_get(candidate, ["reasons"], [])),
        "scores": safe_get(candidate, ["scores"], {}),
    }
    raw = json.dumps(basis, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def format_signals(signals) -> str:
    if signals is None:
        return "Not specified in evidence."
    if isinstance(signals, str):
        return signals
    if isinstance(signals, list):
        lines = []
        for x in signals:
            if isinstance(x, str):
                lines.append(f"- {x}")
            elif isinstance(x, dict):
                msg = x.get("text") or x.get("signal") or x.get("reason") or json.dumps(x, ensure_ascii=False)
                lines.append(f"- {msg}")
            else:
                lines.append(f"- {str(x)}")
        return "\n".join(lines) if lines else "Not specified in evidence."
    if isinstance(signals, dict):
        return json.dumps(signals, ensure_ascii=False, indent=2)
    return str(signals)


def build_prompt(prompt_rules: str, template: str, profile: str, candidate: dict) -> str:
    title = safe_get(candidate, ["title"], "Unknown title")
    company = safe_get(candidate, ["company"], "Unknown company")
    job_uid = safe_get(candidate, ["job_uid"], safe_get(candidate, ["uid"], "unknown_uid"))
    location = safe_get(candidate, ["location"], safe_get(candidate, ["loc"], "Not specified in evidence."))
    url = safe_get(candidate, ["url"], safe_get(candidate, ["job_url"], "Not specified in evidence."))
    jd_excerpt = safe_get(candidate, ["jd_excerpt"], safe_get(candidate, ["excerpt"], "Not specified in evidence."))
    scores = safe_get(candidate, ["scores"], {})
    overall_score = (
        scores.get("final")
        or scores.get("overall")
        or scores.get("total")
        or safe_get(candidate, ["overall_score"], "Not specified in evidence.")
    )

    hard_gate = safe_get(candidate, ["hard_gate"], safe_get(candidate, ["gate"], {}))

    if isinstance(hard_gate, dict):
        hit = hard_gate.get("hit")
        reason = (hard_gate.get("reason") or "").strip()
        if hit is False and reason == "":
            hard_gate_summary = "No hard-gate hit."
        elif hit is True:
            hard_gate_summary = f"Hard-gate hit: {reason or 'Reason not specified in evidence.'}"
        else:
            hard_gate_summary = json.dumps(hard_gate, ensure_ascii=False)
    else:
        hard_gate_summary = hard_gate if hard_gate else "Not specified in evidence."

    why_selected = (
        safe_get(candidate, ["final_reason"], "")
        or safe_get(candidate, ["why"], "")
        or safe_get(candidate, ["selection_reason"], "")
        or "Not specified in evidence."
    )
    signals = safe_get(candidate, ["signals"], safe_get(candidate, ["reasons"], []))
    signals_dump = format_signals(signals)

    filled = template.format(
        title=title,
        company=company,
        job_uid=job_uid,
        location=location,
        url=url,
        overall_score=overall_score,
        hard_gate_summary=hard_gate_summary,
        why_selected=why_selected,
        jd_excerpt=jd_excerpt,
        signals_dump=signals_dump,
    )

    prompt = f"""# SYSTEM RULES
{prompt_rules}

# USER PROFILE (evidence)
{profile}

# CANDIDATE JSON (evidence)
{json.dumps(candidate, ensure_ascii=False, indent=2)}

# TASK
Fill the Markdown template below. Do NOT add sections. Do NOT fabricate.

# TEMPLATE
{filled}
"""
    return prompt


def ollama_run(model: str, prompt: str, timeout: int = 240) -> str:
    # Use STDIN for maximum compatibility (since -p may not exist)
    cmd = ["ollama", "run", model]
    proc = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "Ollama returned non-zero exit code.")
    return proc.stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen2.5:3b", help="Set this to the small model that runs on your RAM")
    ap.add_argument("--candidates", default=str(DEFAULT_CANDIDATES))
    ap.add_argument("--profile", default=str(DEFAULT_PROFILE))
    ap.add_argument("--prompt_rules", default=str(DEFAULT_PROMPT_RULES))
    ap.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    ap.add_argument("--cards_dir", default=str(DEFAULT_CARDS_DIR))
    ap.add_argument("--index", default=str(DEFAULT_INDEX))
    ap.add_argument("--limit", type=int, default=0, help="0 = no limit")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args()

    candidates_path = Path(args.candidates)
    profile_path = Path(args.profile)
    rules_path = Path(args.prompt_rules)
    template_path = Path(args.template)
    cards_dir = Path(args.cards_dir)
    index_path = Path(args.index)

    if not candidates_path.exists():
        print(f"[ERROR] Missing candidates file: {candidates_path}", file=sys.stderr)
        sys.exit(1)
    if not profile_path.exists():
        print(f"[ERROR] Missing profile file: {profile_path}", file=sys.stderr)
        sys.exit(1)

    candidates_obj = load_json(candidates_path)
    if isinstance(candidates_obj, dict) and "candidates" in candidates_obj:
        candidates = candidates_obj["candidates"]
    elif isinstance(candidates_obj, list):
        candidates = candidates_obj
    else:
        print("[ERROR] candidates.json must be a list or {candidates:[...]}", file=sys.stderr)
        sys.exit(1)

    if args.limit and args.limit > 0:
        candidates = candidates[: args.limit]

    prompt_rules = read_text(rules_path)
    template = read_text(template_path)
    profile = read_text(profile_path)

    if index_path.exists():
        index = load_json(index_path)
    else:
        index = {"version": 1, "updated_at": None, "items": {}}

    items = index.get("items", {})
    changed = 0
    skipped = 0
    failed = 0

    for c in candidates:
        job_uid = safe_get(c, ["job_uid"], safe_get(c, ["uid"], None))
        if not job_uid:
            job_uid = compute_text_hash(c)
        else:
            job_uid = str(job_uid)

        uid_safe = normalize_filename(job_uid)
        out_path = cards_dir / f"{uid_safe}.md"

        text_hash = compute_text_hash(c)
        prev = items.get(job_uid, {})

        if (not args.force) and prev.get("text_hash") == text_hash and out_path.exists():
            skipped += 1
            continue

        try:
            prompt = build_prompt(prompt_rules, template, profile, c)
            md = ollama_run(args.model, prompt, timeout=args.timeout)
            write_text(out_path, md)

            items[job_uid] = {
                "text_hash": text_hash,
                "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "file": str(out_path.relative_to(ROOT)).replace("\\", "/"),
                "model": args.model,
            }
            changed += 1
            print(f"[OK] {job_uid} -> {out_path}")
        except Exception as e:
            failed += 1
            print(f"[FAIL] {job_uid}: {e}", file=sys.stderr)

    index["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    index["items"] = items
    dump_json(index_path, index)

    print(f"\nDone. changed={changed}, skipped={skipped}, failed={failed}")
    if failed > 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
