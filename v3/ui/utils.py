import json
import os
from pathlib import Path
from typing import Any, Dict


REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = REPO_ROOT / "data" / "state.json"

def load_state() -> Dict[str, Any]:
    # Load state.json; if missing, return empty dict.
    if not STATE_PATH.exists():
        return {}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state: Dict[str, Any]) -> None:
    # Write atomically to reduce risk of partial writes.
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)

def set_status(job_uid: str, status: str) -> None:
    # Minimal mapping {job_uid: status}.
    state = load_state()
    state[job_uid] = status
    save_state(state)