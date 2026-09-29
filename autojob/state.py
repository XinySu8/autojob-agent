"""Per-job status tracking (new / applied / ignored / closed)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .util import read_json, utc_now, write_json

STATUSES = ("new", "applied", "ignored", "closed")
HIDDEN_STATUSES = {"applied", "ignored", "closed"}


def load_state(path: Path) -> dict[str, Any]:
    try:
        data = read_json(path, default={})
    except ValueError as e:
        # Corrupt file: keep a copy instead of silently wiping the user's marks.
        backup = path.with_suffix(".corrupt.json")
        path.replace(backup)
        raise RuntimeError(f"{path} is not valid JSON; moved to {backup}. Fix or delete it and re-run.") from e
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), dict):
        return {"version": 1, "jobs": {}}
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    write_json(path, state)


def status_of(state: dict, job_id: str) -> str:
    rec = state.get("jobs", {}).get(job_id) or {}
    return (rec.get("status") or "new").lower()


def find_job(state: dict, key: str, extra_jobs: list[dict] | None = None) -> str | None:
    """Resolve a URL, full id, or unique id prefix (>=6 chars) to a job id."""
    key = (key or "").strip()
    if not key:
        return None
    jobs = state.get("jobs", {})
    if key in jobs:
        return key
    for jid, rec in jobs.items():
        if isinstance(rec, dict) and (rec.get("url") or "").strip() == key:
            return jid
    for j in extra_jobs or []:
        if (j.get("url") or "").strip() == key:
            return j.get("id")
    if len(key) >= 6:
        matches = [jid for jid in jobs if jid.startswith(key)]
        if len(matches) == 1:
            return matches[0]
    return None


def set_status(state: dict, job_id: str, status: str, note: str = "") -> dict:
    status = status.lower()
    if status not in STATUSES:
        raise ValueError(f"invalid status '{status}', expected one of {', '.join(STATUSES)}")
    rec = state.setdefault("jobs", {}).setdefault(job_id, {})
    rec["status"] = status
    rec["status_updated_at_utc"] = utc_now().isoformat()
    if note:
        rec["note"] = note
    return rec
