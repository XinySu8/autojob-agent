import json
import os
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # repo root
V3_ROOT = os.path.join(REPO_ROOT, "v3")
V2_CAND = os.path.join(REPO_ROOT, "v2", "output", "candidates.json")

AGENT_IN = os.path.join(V3_ROOT, "output", "agent_results.normalized.json")
OUT_VIEW = os.path.join(V3_ROOT, "data", "view_model.json")

def now_utc():
    return datetime.now(timezone.utc).isoformat()

def load_candidates(path: str):
    # NOTE: V2 candidates.json is { "meta": ..., "candidates": [...] } in your repo.
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, dict):
        if "candidates" in raw and isinstance(raw["candidates"], list):
            items = raw["candidates"]
        elif "items" in raw and isinstance(raw["items"], list):
            items = raw["items"]
        else:
            raise ValueError(f"Unrecognized candidates dict format. keys={list(raw.keys())}")
    elif isinstance(raw, list):
        items = raw
    else:
        raise ValueError(f"Unrecognized candidates format: {type(raw)}")

    by_uid = {}
    for j in items:
        if isinstance(j, dict):
            uid = str(j.get("job_uid") or j.get("uid") or j.get("id") or "")
            if uid:
                by_uid[uid] = j
    return by_uid

def main():
    os.makedirs(os.path.dirname(OUT_VIEW), exist_ok=True)

    cand_by_uid = load_candidates(V2_CAND)

    with open(AGENT_IN, "r", encoding="utf-8") as f:
        agent = json.load(f)

    out_items = []
    for it in agent.get("items", []):
        uid = it["job_uid"]
        j = cand_by_uid.get(uid, {})

        out_items.append({
            "job_uid": uid,
            "title": str(j.get("title","")),
            "company": str(j.get("company","")),
            "location": str(j.get("location","")),
           "apply_url": str(j.get("url") or j.get("apply_url") or j.get("job_url") or ""),

            "decision": it["decision"],
            "score": it["score"],
            "reasons": it.get("reasons", []),
            "evidence": it.get("evidence", []),

            "status": "new",
            "matched_keywords": j.get("matched_keywords", []),
            "missing_keywords": j.get("missing_keywords", []),
            "tags": j.get("tags", [])
        })

    view = {
        "generated_at_utc": now_utc(),
        "source": {
            "candidates_path": "v2/output/candidates.json",
            "agent_results_path": "v3/output/agent_results.normalized.json"
        },
        "items": out_items
    }

    with open(OUT_VIEW, "w", encoding="utf-8") as f:
        json.dump(view, f, ensure_ascii=False, indent=2)

    print(f"Wrote view_model -> {OUT_VIEW} ({len(out_items)} items)")

if __name__ == "__main__":
    main()