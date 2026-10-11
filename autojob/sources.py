"""ATS adapters. Each ``Source`` turns one company's job board into ``Posting`` objects.

Adding a new ATS = subclass ``Source``, set ``kind`` / ``key`` and implement ``fetch``.
Job ids use the same hashing scheme as v0/v1 so existing ids stay stable.
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from . import __version__
from .util import clean_text, html_to_text, stable_id, to_iso

UA = f"autojob-agent/{__version__} (+https://github.com/XinySu8/autojob-agent)"
RETRY_STATUS = {429, 500, 502, 503, 504}

HttpFn = Callable[..., Any]


class FetchError(RuntimeError):
    pass


def http_json(url: str, method: str = "GET", data: Any = None, timeout: int = 30, retries: int = 2) -> Any:
    """GET/POST JSON with retry + exponential backoff on transient failures."""
    headers = {"User-Agent": UA, "Accept": "application/json"}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    for attempt in range(retries + 1):
        try:
            with urlopen(Request(url, headers=headers, data=body, method=method), timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            if e.code not in RETRY_STATUS or attempt == retries:
                raise FetchError(f"HTTP {e.code} for {url}") from e
        except (URLError, TimeoutError, ConnectionError) as e:
            if attempt == retries:
                raise FetchError(f"network error for {url}: {e}") from e
        except json.JSONDecodeError as e:
            raise FetchError(f"invalid JSON from {url}") from e
        time.sleep(min(2 ** (attempt + 1), 10))
    raise AssertionError("unreachable")


@dataclass
class Posting:
    id: str
    source: str
    company: str
    title: str
    url: str
    location: str = ""
    posted_at: str | None = None
    departments: list[str] = field(default_factory=list)
    employment_type: str | None = None
    content: str = ""


class Source(ABC):
    kind: ClassVar[str]
    key: ClassVar[str]  # required config field, e.g. board_token

    def __init__(self, company: str, token: str, http: HttpFn = http_json, options: dict | None = None):
        self.company = company
        self.token = token
        self.http = http
        self.options = options or {}

    @abstractmethod
    def fetch(self, title_filter: Callable[[str], bool] | None = None) -> list[Posting]:
        """Return every posting on the board. ``title_filter`` lets expensive
        sources skip detail requests for irrelevant postings."""

    def __repr__(self) -> str:
        return f"{self.company} ({self.kind})"


class GreenhouseSource(Source):
    kind, key = "greenhouse", "board_token"

    def fetch(self, title_filter=None):
        data = self.http(f"https://boards-api.greenhouse.io/v1/boards/{quote(self.token)}/jobs?content=true")
        return [
            Posting(
                id=stable_id("greenhouse", self.token, str(j.get("id", "")), j.get("absolute_url") or ""),
                source=self.kind,
                company=self.company,
                title=j.get("title") or "",
                url=j.get("absolute_url") or "",
                location=(j.get("location") or {}).get("name") or "",
                posted_at=to_iso(j.get("first_published") or j.get("updated_at")),
                departments=[d["name"] for d in j.get("departments") or [] if isinstance(d, dict) and d.get("name")],
                content=html_to_text(j.get("content")),
            )
            for j in data.get("jobs") or []
        ]


class LeverSource(Source):
    kind, key = "lever", "lever_slug"

    def fetch(self, title_filter=None):
        host = "api.eu.lever.co" if self.options.get("region") == "eu" else "api.lever.co"
        data = self.http(f"https://{host}/v0/postings/{quote(self.token)}?mode=json")
        out = []
        for j in data if isinstance(data, list) else []:
            cat = j.get("categories") or {}
            lists = " ".join(f"{x.get('text', '')} {html_to_text(x.get('content'))}" for x in j.get("lists") or [])
            out.append(Posting(
                id=stable_id("lever", self.token, str(j.get("id", "")), j.get("hostedUrl") or ""),
                source=self.kind,
                company=self.company,
                title=j.get("text") or "",
                url=j.get("hostedUrl") or "",
                location=" / ".join(cat.get("allLocations") or []) or cat.get("location") or "",
                posted_at=to_iso(j.get("createdAt")),
                departments=[x for x in (cat.get("department"), cat.get("team")) if x],
                employment_type=cat.get("commitment"),
                content=clean_text(f"{j.get('descriptionPlain') or ''} {lists} {j.get('additionalPlain') or ''}"),
            ))
        return out


class AshbySource(Source):
    kind, key = "ashby", "job_board_name"

    @staticmethod
    def _location(j: dict) -> str:
        addr = (j.get("address") or {}).get("postalAddress") or {}
        parts = [j.get("location") or ""]
        parts += [s.get("location") for s in j.get("secondaryLocations") or [] if isinstance(s, dict)]
        parts.append(", ".join(x for x in (addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")) if x))
        return " / ".join(dict.fromkeys(p for p in parts if p))

    def fetch(self, title_filter=None):
        data = self.http(f"https://api.ashbyhq.com/posting-api/job-board/{quote(self.token)}?includeCompensation=false")
        return [
            Posting(
                id=stable_id("ashby", self.token, j.get("title") or "", j.get("jobUrl") or "", j.get("applyUrl") or ""),
                source=self.kind,
                company=self.company,
                title=j.get("title") or "",
                url=j.get("jobUrl") or j.get("applyUrl") or "",
                location=self._location(j),
                posted_at=to_iso(j.get("publishedAt")),
                departments=[x for x in (j.get("department"), j.get("team")) if x],
                employment_type=j.get("employmentType"),
                content=clean_text(j.get("descriptionPlain")) or html_to_text(j.get("descriptionHtml")),
            )
            for j in data.get("jobs") or []
            if j.get("isListed") is not False
        ]


class WorkdaySource(Source):
    """Workday CXS API: the listing needs a POST with appliedFacets/searchText, and
    has no description, so details are fetched for postings passing ``title_filter``."""

    kind, key = "workday", "workday_url"
    PAGE = 20

    def _endpoints(self) -> tuple[str, str]:
        u = urlparse(self.token)
        segs = [s for s in u.path.split("/") if s]
        if segs and len(segs[0]) == 5 and segs[0][2] == "-":  # locale prefix like en-US
            segs = segs[1:]
        if not segs:
            raise FetchError(f"invalid workday_url: {self.token}")
        origin, tenant, site = f"{u.scheme}://{u.netloc}", u.netloc.split(".")[0], segs[0]
        return f"{origin}/wday/cxs/{tenant}/{site}", f"{origin}/{site}"

    def fetch(self, title_filter=None):
        api, site_root = self._endpoints()
        out, offset = [], 0
        while True:
            body = {"appliedFacets": {}, "limit": self.PAGE, "offset": offset, "searchText": self.options.get("search_text", "")}
            data = self.http(f"{api}/jobs", method="POST", data=body)
            page = data.get("jobPostings") or []
            for p in page:
                path = p.get("externalPath") or ""
                url = site_root + (path if path.startswith("/") else "/" + path)
                post = Posting(
                    id=stable_id("workday", api.split("/")[-2], api.split("/")[-1], p.get("title") or "", url),
                    source=self.kind, company=self.company, title=p.get("title") or "", url=url,
                    location=p.get("locationsText") or "",
                )
                if path and (title_filter is None or title_filter(post.title)):
                    self._add_details(post, f"{api}{path}")
                out.append(post)
            offset += len(page)
            total = data.get("total")
            if len(page) < self.PAGE or (isinstance(total, int) and offset >= total):
                return out

    def _add_details(self, post: Posting, url: str) -> None:
        try:
            info = (self.http(url) or {}).get("jobPostingInfo") or {}
        except FetchError:
            return
        post.location = " / ".join(x for x in [info.get("location"), *(info.get("additionalLocations") or [])] if x) or post.location
        post.content = html_to_text(info.get("jobDescription"))
        post.posted_at = to_iso(info.get("startDate"))
        post.employment_type = info.get("timeType")


SOURCES: dict[str, type[Source]] = {cls.kind: cls for cls in (GreenhouseSource, LeverSource, AshbySource, WorkdaySource)}


def build_sources(targets: list[dict], http: HttpFn = http_json) -> tuple[list[Source], list[str]]:
    """Validate + de-duplicate config targets. Returns (sources, warnings)."""
    sources, warnings, seen = [], [], set()
    for t in targets or []:
        if not isinstance(t, dict) or t.get("enabled") is False:
            continue
        company, kind = str(t.get("company") or "").strip(), str(t.get("source") or "").strip().lower()
        cls = SOURCES.get(kind)
        if not company:
            warnings.append(f"target missing 'company': {t}")
        elif cls is None:
            warnings.append(f"{company}: unsupported source '{kind}' (supported: {', '.join(SOURCES)})")
        elif not t.get(cls.key):
            warnings.append(f"{company}: {kind} target needs '{cls.key}'")
        elif (kind, str(t[cls.key]).lower()) not in seen:
            seen.add((kind, str(t[cls.key]).lower()))
            options = {k: v for k, v in t.items() if k not in ("company", "source", cls.key)}
            sources.append(cls(company, str(t[cls.key]), http=http, options=options))
    return sources, warnings
