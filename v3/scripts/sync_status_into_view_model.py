import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # repo root
V3_ROOT = os.path.join(REPO_ROOT, "v3")

VIEW_PATH = os.path.join(V3_ROOT, "data", "view_model.json")
STATE_PATH = os.path.join(REPO_ROOT, "data", "state.json")

def main():
    with open(VIEW_PATH, "r", encoding="utf-8") as f:
        vm = json.load(f)

    if not os.path.exists(STATE_PATH):
        print(f"state.json not found: {STATE_PATH}")
        return

    with open(STATE_PATH, "r", encoding="utf-8") as f:
        state = json.load(f)

    # Compatible with state. json stateable {job_uid: {status:...}}  or {job_uid: "apply"}
    def get_status(uid: str):
        v = state.get(uid)
        if isinstance(v, str):
            return v
        if isinstance(v, dict):
            return v.get("status") or v.get("state") or "new"
        return "new"

    n = 0
    for it in vm.get("items", []):
        uid = it.get("job_uid", "")
        if uid:
            it["status"] = get_status(uid)
            n += 1

    with open(VIEW_PATH, "w", encoding="utf-8") as f:
        json.dump(vm, f, ensure_ascii=False, indent=2)

    print(f"Synced status for {n} items -> {VIEW_PATH}")

if __name__ == "__main__":
    main()