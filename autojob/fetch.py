"""Stage 1: fetch postings from all targets, filter, update state, write jobs.json."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .config import Workspace
from .sources import FETCHERS, FetchError, http_json, normalize_targets
from .state import HIDDEN_STATUSES, load_state, save_state, status_of
from .util import first_term, has_term, iso_sort_key, utc_now, write_json

log = logging.getLogger(__name__)


def is_internship(job: dict, filters: dict) -> bool:
    ashby_types = {str(x).lower() for x in filters.get("ashby_internship_types") or []}
    et = str(job.get("employment_type") or "").lower()
    if et and et in ashby_types:
        return True
    keywords = filters.get("internship_any") or []
    if not keywords:
        return True
    return first_term(job.get("title") or "", keywords) is not None


def apply_filters(jobs: list[dict], filters: dict) -> tuple[list[dict], list[dict]]:
    """Returns (kept, dropped). Each dropped item carries a ``reason``."""
    domain_any = filters.get("domain_any") or []
    exclude_title = filters.get("exclude_title_any") or []
    locations_any = filters.get("locations_any") or []
    cap = filters.get("max_jobs_per_company")

    kept, dropped, per_company = [], [], {}

    def drop(j: dict, reason: str) -> None:
        dropped.append({"id": j.get("id"), "company": j.get("company"), "title": j.get("title"), "reason": reason})

    for j in jobs:
        title = j.get("title") or ""
        if not is_internship(j, filters):
            drop(j, "not_internship")
            continue
        # Exclusions look at the TITLE only. v0.x matched the whole JD, so any
        # intern posting that mentioned "director" or "principal" was dropped.
        hit = first_term(title, exclude_title)
        if hit:
            drop(j, f"excluded_title:{hit}")
            continue
        haystack = f"{title}\n{' '.join(j.get('departments') or [])}\n{j.get('content_plain') or ''}"
        if domain_any and not first_term(haystack, domain_any):
            drop(j, "domain_mismatch")
            continue
        if locations_any and not any(has_term(j.get("location") or "", x) for x in locations_any):
            drop(j, "location_mismatch")
            continue
        if cap:
            c = j.get("company") or "unknown"
            if per_company.get(c, 0) >= int(cap):
                drop(j, "company_cap")
                continue
            per_company[c] = per_company.get(c, 0) + 1
        kept.append(j)
    return kept, dropped


def fetch_all(ws: Workspace, http: Callable | None = None, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    fcfg = ws.cfg["fetch"]
    filters = ws.cfg["filters"]
    targets, warnings = normalize_targets(fcfg["targets"])
    errors = [f"[config] {w}" for w in warnings]

    http = functools.partial(http or http_json, timeout=int(fcfg["timeout"]), retries=int(fcfg["retries"]))
    title_ok = lambda title: is_internship({"title": title}, filters)  # noqa: E731

    all_jobs: list[dict] = []
    per_target: dict[str, int] = {}

    def run(t: dict) -> list[dict]:
        fn = FETCHERS[t["source"]]
        return fn(t, http=http, title_filter=title_ok, details=bool(fcfg["workday_details"]))

    with ThreadPoolExecutor(max_workers=max(1, int(fcfg["workers"]))) as pool:
        futures = {pool.submit(run, t): t for t in targets}
        for fut in as_completed(futures):
            t = futures[fut]
            label = f"{t['company']} ({t['source']})"
            try:
                got = fut.result()
                all_jobs.extend(got)
                per_target[label] = len(got)
                if progress:
                    progress(f"  {label}: {len(got)} postings")
            except FetchError as e:
                errors.append(f"{label}: {e}")
                if progress:
                    progress(f"  {label}: FAILED – {e}")
            except Exception as e:  # never let one bad target kill the whole run
                log.exception("unexpected error for %s", label)
                errors.append(f"{label}: unexpected {type(e).__name__}: {e}")

    # De-duplicate by id (same posting reachable via two boards).
    uniq = {}
    for j in all_jobs:
        uniq.setdefault(j["id"], j)
    all_jobs = list(uniq.values())

    fetched = len(all_jobs)
    kept, dropped = apply_filters(all_jobs, filters)
    kept.sort(key=lambda j: iso_sort_key(j.get("updated_at") or j.get("created_at")), reverse=True)

    now = utc_now()
    today = now.strftime("%Y-%m-%d")
    state = load_state(ws.state_path)
    jobs_state = state.setdefault("jobs", {})
    for j in kept:
        rec = jobs_state.setdefault(j["id"], {})
        rec.setdefault("first_seen_date_utc", today)
        rec["last_seen_at_utc"] = now.isoformat()
        rec.update({"company": j.get("company"), "title": j.get("title"), "url": j.get("url")})
        rec.setdefault("status", "new")
        j["first_seen_date_utc"] = rec["first_seen_date_utc"]
        j["status"] = rec["status"]
    save_state(ws.state_path, state)

    visible = [j for j in kept if status_of(state, j["id"]) not in HIDDEN_STATUSES]
    today_count = sum(1 for j in visible if j["first_seen_date_utc"] == today)

    reasons: dict[str, int] = {}
    for d in dropped:
        r = d["reason"].split(":")[0]
        reasons[r] = reasons.get(r, 0) + 1

    payload = {
        "generated_at_utc": now.isoformat(),
        "today_utc": today,
        "targets": len(targets),
        "fetched_count": fetched,
        "filtered_count": len(kept),
        "count": len(visible),
        "today_count": today_count,
        "per_target": dict(sorted(per_target.items())),
        "dropped_by_reason": reasons,
        "errors": errors,
        "jobs": visible,
    }
    write_json(ws.jobs_path, payload)
    write_json(ws.archive_dir / f"jobs.{today}.json", {k: v for k, v in payload.items() if k != "jobs"}
               | {"job_ids": [j["id"] for j in visible]})
    return payload
