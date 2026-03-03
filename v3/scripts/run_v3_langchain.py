from __future__ import annotations
import argparse
import json
import os
from typing import Any, Dict, List

from tqdm import tqdm

from v3.langchain_agent.cli_ollama_llm import OllamaCLILLM
from v3.langchain_agent.runner import run_one_job


def load_candidates(path: str):
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, dict) and isinstance(raw.get("candidates"), list):
        return raw["candidates"]

    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        return raw["items"]

    if isinstance(raw, list):
        return raw

    raise ValueError(
        f"Unrecognized candidates.json format. type={type(raw)} keys={list(raw.keys()) if isinstance(raw, dict) else None}"
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True, help="Ollama model name, e.g. llama3.1:8b")
    p.add_argument("--candidates", default=os.path.join("v2", "output", "candidates.json"))
    p.add_argument("--out", default=os.path.join("v3", "output", "agent_results.json"))
    p.add_argument("--top_n", type=int, default=30)
    p.add_argument("--timeout_s", type=int, default=120)
    args = p.parse_args()

    jobs = load_candidates(args.candidates)[: args.top_n]

    llm = OllamaCLILLM(model=args.model, timeout_s=args.timeout_s)

    results = []
    for job in tqdm(jobs, desc="Agent triage"):
        # Normalize minimal required fields that prompt expects
        if "job_uid" not in job:
            # if candidates uses uid/id, try to map
            job["job_uid"] = job.get("uid") or job.get("id") or ""
        if "apply_url" not in job:
            job["apply_url"] = job.get("url") or job.get("job_url") or ""

        res = run_one_job(llm, job, max_retries=2)
        results.append(res.model_dump())

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(
            {
                "model": args.model,
                "candidates_path": args.candidates,
                "top_n": args.top_n,
                "items": results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"Wrote {len(results)} results -> {args.out}")


if __name__ == "__main__":
    main()