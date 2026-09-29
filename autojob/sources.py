"""ATS connectors: Greenhouse, Lever, Ashby, Workday.

Each ``fetch_*`` returns a list of normalised job dicts:
    id, source, company, title, location, url, updated_at, created_at,
    departments, employment_type, content_plain
Job ids use the same hashing scheme as v0.x so an existing ``state.json``
(applied / ignored marks) keeps working after upgrading.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from . import __version__
from .util import clean_text, html_to_text, stable_id, to_iso

UA = f"autojob-agent/{__version__} (+https://github.com/XinySu8/autojob-agent)"
SUPPORTED = ("greenhouse", "lever", "ashby", "workday")
RETRY_STATUS = {429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    pass


def http_json(url: str, method: str = "GET", data: Any = None, timeout: int = 30, retries: int = 2) -> Any:
    """GET/POST JSON with retry + exponential backoff on transient failures."""
    headers = {"User-Agent": UA, "Accept": "application/json"}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    attempt = 0
    while True:
        try:
            req = Request(url, headers=headers, data=body, method=method)
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            if e.code in RETRY_STATUS and attempt < retries:
                attempt += 1
                time.sleep(min(2 ** attempt, 10))
                continue
            raise FetchError(f"HTTP {e.code} for {url}") from e
        except (URLError, TimeoutError, ConnectionError) as e:
            if attempt < retries:
                attempt += 1
                time.sleep(min(2 ** attempt, 10))
                continue
            raise FetchError(f"network error for {url}: {e}") from e
        except json.JSONDecodeError as e:
            raise FetchError(f"invalid JSON from {url}") from e


# ----------------------------------------------------------------------------
# Target normalisation
# ----------------------------------------------------------------------------
REQUIRED_KEY = {"greenhouse": "board_token", "lever": "lever_slug", "ashby": "job_board_name", "workday": "workday_url"}


def normalize_targets(raw: list[dict]) -> tuple[list[dict], list[str]]:
    """Validate + de-duplicate targets. Returns (targets, warnings)."""
    out, warnings, seen = [], [], set()
    for t in raw or []:
        if not isinstance(t, dict):
            warnings.append(f"target is not a mapping: {t!r}")
            continue
        t = dict(t)
        company = str(t.get("company") or "").strip()
        source = str(t.get("source") or "").strip().lower()
        if not company:
            warnings.append(f"target missing 'company': {t}")
            continue
        if t.get("enabled") is False:
            continue
        if source == "ashby" and "job_board_name" not in t and "board_token" in t:
            t["job_board_name"] = t["board_token"]
        if source not in SUPPORTED:
            warnings.append(f"{company}: unsupported source '{source}' (supported: {', '.join(SUPPORTED)})")
            continue
        key = REQUIRED_KEY[source]
        if not t.get(key):
            warnings.append(f"{company}: {source} target needs '{key}'")
            continue
        uniq = (source, str(t[key]).lower())
        if uniq in seen:
            continue
        seen.add(uniq)
        t["company"], t["source"] = company, source
        out.append(t)
    return out, warnings


# ----------------------------------------------------------------------------
# Fetchers
# ----------------------------------------------------------------------------
def fetch_greenhouse(t: dict, http: Callable = http_json, **_: Any) -> list[dict]:
    token = t["board_token"]
    data = http(f"https://boards-api.greenhouse.io/v1/boards/{quote(token)}/jobs?content=true")
    jobs = []
    for j in data.get("jobs", []) or []:
        url = j.get("absolute_url") or ""
        jobs.append({
            "id": stable_id("greenhouse", token, str(j.get("id", "")), url),
            "source": "greenhouse",
            "company": t["company"],
            "title": j.get("title") or "",
            "location": (j.get("location") or {}).get("name") or "",
            "url": url,
            "updated_at": to_iso(j.get("updated_at")),
            "created_at": to_iso(j.get("first_published") or j.get("created_at") or j.get("updated_at")),
            "departments": [d.get("name") for d in (j.get("departments") or []) if isinstance(d, dict) and d.get("name")],
            "employment_type": None,
            "content_plain": html_to_text(j.get("content")),
        })
    return jobs


def fetch_lever(t: dict, http: Callable = http_json, **_: Any) -> list[dict]:
    slug = t["lever_slug"]
    region = (t.get("region") or "").lower()
    host = "api.eu.lever.co" if region == "eu" else "api.lever.co"
    data = http(f"https://{host}/v0/postings/{quote(slug)}?mode=json")
    jobs = []
    for j in data if isinstance(data, list) else []:
        cat = j.get("categories") or {}
        url = j.get("hostedUrl") or ""
        lists = " ".join(
            f"{x.get('text', '')} {html_to_text(x.get('content'))}" for x in (j.get("lists") or []) if isinstance(x, dict)
        )
        content = clean_text(" ".join([j.get("descriptionPlain") or "", lists, j.get("additionalPlain") or ""]))
        all_locs = cat.get("allLocations") or []
        jobs.append({
            "id": stable_id("lever", slug, str(j.get("id", "")), url),
            "source": "lever",
            "company": t["company"],
            "title": j.get("text") or "",
            "location": " / ".join(all_locs) if all_locs else (cat.get("location") or ""),
            "url": url,
            "updated_at": to_iso(j.get("updatedAt") or j.get("createdAt")),
            "created_at": to_iso(j.get("createdAt")),
            "departments": [x for x in [cat.get("department"), cat.get("team")] if x],
            "employment_type": cat.get("commitment"),
            "content_plain": content,
        })
    return jobs


def _ashby_location(j: dict) -> str:
    parts = [j.get("location") or ""]
    for sec in j.get("secondaryLocations") or []:
        if isinstance(sec, dict) and sec.get("location"):
            parts.append(sec["location"])
    addr = ((j.get("address") or {}).get("postalAddress") or {})
    extra = ", ".join(x for x in [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")] if x)
    if extra:
        parts.append(extra)
    seen, out = set(), []
    for p in parts:
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return " / ".join(out)


def fetch_ashby(t: dict, http: Callable = http_json, **_: Any) -> list[dict]:
    board = t["job_board_name"]
    data = http(f"https://api.ashbyhq.com/posting-api/job-board/{quote(board)}?includeCompensation=false")
    jobs = []
    for j in data.get("jobs", []) or []:
        if j.get("isListed") is False:
            continue
        job_url, apply_url = j.get("jobUrl") or "", j.get("applyUrl") or ""
        title = j.get("title") or ""
        jobs.append({
            "id": stable_id("ashby", board, title, job_url, apply_url),
            "source": "ashby",
            "company": t["company"],
            "title": title,
            "location": _ashby_location(j),
            "url": job_url or apply_url,
            "updated_at": to_iso(j.get("publishedAt")),
            "created_at": to_iso(j.get("publishedAt")),
            "departments": [x for x in [j.get("department"), j.get("team")] if x],
            "employment_type": j.get("employmentType"),
            "content_plain": clean_text(j.get("descriptionPlain")) or html_to_text(j.get("descriptionHtml")),
        })
    return jobs


def _workday_parts(workday_url: str) -> tuple[str, str, str, str]:
    """https://salesforce.wd12.myworkdayjobs.com/en-US/Slack -> (origin, tenant, site, root)."""
    u = urlparse(workday_url)
    segs = [s for s in u.path.split("/") if s]
    if segs and len(segs[0]) == 5 and segs[0][2] == "-":  # locale prefix like en-US
        segs = segs[1:]
    site = segs[0] if segs else ""
    tenant = u.netloc.split(".")[0]
    origin = f"{u.scheme}://{u.netloc}"
    return origin, tenant, site, f"{origin}/{site}"


def fetch_workday(
    t: dict,
    http: Callable = http_json,
    title_filter: Callable[[str], bool] | None = None,
    details: bool = True,
    **_: Any,
) -> list[dict]:
    """Workday CXS API. The listing needs a POST with appliedFacets/searchText
    (a bare GET returns 400, which is why Slack always failed before).
    Listings don't include the description or a real location, so for postings
    that pass ``title_filter`` we fetch the detail endpoint too.
    """
    origin, tenant, site, root = _workday_parts(t["workday_url"])
    if not tenant or not site:
        raise FetchError(f"invalid workday_url: {t['workday_url']}")
    api = f"{origin}/wday/cxs/{tenant}/{site}"
    search = t.get("search_text", "")

    jobs, offset, limit = [], 0, 20
    for _page in range(100):
        data = http(f"{api}/jobs", method="POST",
                    data={"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": search})
        postings = data.get("jobPostings") or []
        for p in postings:
            title = p.get("title") or ""
            path = p.get("externalPath") or ""
            url = root + (path if path.startswith("/") else "/" + path)
            job = {
                "id": stable_id("workday", tenant, site, title, url),
                "source": "workday",
                "company": t["company"],
                "title": title,
                "location": p.get("locationsText") or "",
                "url": url,
                "updated_at": None,
                "created_at": None,
                "departments": [],
                "employment_type": None,
                "content_plain": "",
                "posted_on": p.get("postedOn"),
            }
            if details and path and (title_filter is None or title_filter(title)):
                try:
                    info = (http(f"{api}{path}") or {}).get("jobPostingInfo") or {}
                    locs = [info.get("location")] + list(info.get("additionalLocations") or [])
                    job["location"] = " / ".join(x for x in locs if x) or job["location"]
                    job["content_plain"] = html_to_text(info.get("jobDescription"))
                    job["created_at"] = job["updated_at"] = to_iso(info.get("startDate"))
                    job["employment_type"] = info.get("timeType")
                except FetchError:
                    pass
            jobs.append(job)
        offset += len(postings)
        total = data.get("total")
        if not postings or (isinstance(total, int) and offset >= total) or len(postings) < limit:
            break
    return jobs


FETCHERS: dict[str, Callable[..., list[dict]]] = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "workday": fetch_workday,
}
