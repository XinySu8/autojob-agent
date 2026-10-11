"""Ranking: hard gates -> keyword score + semantic similarity -> apply / maybe / skip."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .semantic import get_backend
from .util import clean_text, compile_regexes, first_regex, first_term, has_term

# ----------------------------------------------------------------------------
# Location allowlist
# ----------------------------------------------------------------------------
_US_STATES = (
    "Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|"
    "Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|"
    "Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|"
    "North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|"
    "Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming"
)
_US_CODES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|"
    "NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC"
)
REGION_PATTERNS: dict[str, list[str]] = {
    "US": [
        r"\bUnited States\b", r"\bU\.S\.A?\.?(?![A-Za-z])", r"(?-i:\bUSA?\b)",
        rf"\b(?:{_US_STATES})\b", rf"(?-i:,\s*(?:{_US_CODES})\b)",
        r"\b(?:San Francisco|SF Bay Area|Bay Area|NYC|Seattle|Boston|Austin|Chicago|Los Angeles|Denver|Atlanta|"
        r"Palo Alto|Mountain View|Sunnyvale|San Jose|Menlo Park|Redwood City|Foster City|Pittsburgh|Miami)\b",
    ],
    "Canada": [r"\bCanada\b", r"\b(?:Ontario|Quebec|British Columbia|Alberta|Nova Scotia|Toronto|Vancouver|Montreal|Waterloo|Ottawa)\b",
               r"(?-i:,\s*(?:ON|QC|BC|AB|NS)\b)"],
    "China": [r"\bChina\b", r"\b(?:Beijing|Shanghai|Shenzhen|Hangzhou|Guangzhou|Hong\s*Kong)\b", "中国|北京|上海|深圳|杭州|广州|香港"],
    "Singapore": [r"\bSingapore\b", "新加坡"],
    "UK": [r"\bUnited Kingdom\b", r"(?-i:\bUK\b)", r"\b(?:London|England|Scotland|Cambridge, UK|Edinburgh|Manchester)\b"],
    "Remote": [r"\bRemote\b"],
}
# Location strings that carry no geography – fall back to the JD text for these.
_VAGUE_LOCATION = re.compile(r"^\s*(?:in[- ]?office|on[- ]?site|onsite|hybrid|remote|anywhere|\d+\s+locations?|multiple locations)\s*$", re.I)


def build_allowlist(cfg: dict) -> list[re.Pattern]:
    pats: list[str] = []
    for r in cfg.get("regions") or []:
        if r not in REGION_PATTERNS:
            raise ValueError(f"unknown region '{r}' in scoring.location_allowlist.regions (known: {', '.join(REGION_PATTERNS)})")
        pats.extend(REGION_PATTERNS[r])
    pats.extend(cfg.get("allow_regex") or [])
    return compile_regexes(pats)


def location_allowed(location: str, text: str, allow: list[re.Pattern], match_order: str) -> bool:
    loc = (location or "").strip()
    if match_order != "text_only" and loc and not _VAGUE_LOCATION.match(loc):
        return first_regex(loc, allow) is not None
    # Location empty / vague (e.g. "In-Office", "5 Locations"): look in the JD instead
    # of rejecting outright, which is what the config always claimed to do.
    return first_regex(f"{loc}\n{text}", allow) is not None


# ----------------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------------
class Scorable(Protocol):
    """Anything with these attributes can be scored (ORM ``Job`` or ``Posting``)."""

    id: str
    title: str
    location: str
    departments: list[str]
    content: str


@dataclass
class ScoreResult:
    job_id: str
    score: float
    keyword_score: float
    semantic_score: float
    gate: str | None
    hits: dict[str, list[str]] = field(default_factory=dict)
    bucket: str = "skip"
    reason: str = ""

    def row(self) -> dict:
        """Column values for a ``models.Score`` row."""
        return self.__dict__.copy()


def keyword_hits(text: str, weights: dict[str, float] | None) -> tuple[float, list[str]]:
    hits = [str(k) for k in (weights or {}) if has_term(text, str(k))]
    return sum(float(weights[k]) for k in hits), hits


def minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


class Scorer:
    """Compiles the ``scoring`` + ``triage`` config once, then scores batches of jobs."""

    def __init__(self, cfg: dict, cache_path: Path):
        sc = cfg["scoring"]
        allow_cfg = sc["location_allowlist"]
        self.allow = build_allowlist(allow_cfg) if allow_cfg.get("enabled") else []
        self.match_order = allow_cfg.get("match_order", "location_then_text")
        self.excl_phrases = sc.get("exclude_phrases") or []
        self.excl_regex = compile_regexes(sc.get("exclude_regex") or [])
        self.keywords = sc["keywords"]
        self.saturation = max(float(sc.get("hard_saturation") or 1.0), 1e-6)
        self.max_chars = int(sc["semantic"]["content_max_chars"])
        self.backend = get_backend(sc["semantic"]["backend"], sc["semantic"]["model_name"], cache_path)
        w_h, w_s = float(sc["weights"]["hard"]), float(sc["weights"]["semantic"])
        self.weights = (1.0, 0.0) if self.backend.name == "none" else (w_h, w_s)
        tri = cfg["triage"]
        self.th_apply, self.th_maybe = float(tri["thresholds"]["apply"]), float(tri["thresholds"]["maybe"])
        self.top_n = {k: int(v) for k, v in tri["top_n"].items()}

    def text(self, job: Scorable) -> str:
        return clean_text(f"{job.title}\n{' '.join(job.departments or [])}\n{job.content}")[: self.max_chars]

    def gate(self, job: Scorable, text: str) -> str | None:
        if self.allow and not location_allowed(job.location, text, self.allow, self.match_order):
            return "location not in allowlist"
        if ph := first_term(text, self.excl_phrases):
            return f"excluded phrase: {ph}"
        if rx := first_regex(text, self.excl_regex):
            return f"excluded pattern: {rx.pattern}"
        return None

    def score(self, jobs: list[Scorable], profile: str) -> list[ScoreResult]:
        results, open_texts, open_results = [], [], []
        for job in jobs:
            text = self.text(job)
            hits, total = {}, 0.0
            for part, weights, haystack in (("title", "title", job.title), ("must", "must_have", text),
                                            ("nice", "nice_to_have", text), ("negative", "negative", text)):
                pts, hits[part] = keyword_hits(haystack, self.keywords.get(weights))
                total += pts
            r = ScoreResult(job.id, 0.0, round(min(1.0, max(0.0, total / self.saturation)), 4), 0.0, self.gate(job, text), hits)
            results.append(r)
            if r.gate is None:
                open_texts.append(text)
                open_results.append(r)

        semantic = minmax(self.backend.score(profile, open_texts)) if open_texts else []
        w_h, w_s = self.weights
        for r, sem in zip(open_results, semantic):
            r.semantic_score = round(sem, 4)
            r.score = round(w_h * r.keyword_score + w_s * sem, 4)
        self.triage(results)
        return results

    def triage(self, results: list[ScoreResult]) -> None:
        """Assign buckets in place. Overflow beyond top_n is demoted, not dropped."""
        taken = {"apply": 0, "maybe": 0}
        for r in sorted(results, key=lambda x: x.score, reverse=True):
            if r.gate:
                r.bucket, r.reason = "skip", r.gate
                continue
            if r.score >= self.th_apply:
                r.bucket, r.reason = "apply", f"score {r.score:.2f} ≥ {self.th_apply}"
            elif r.score >= self.th_maybe:
                r.bucket, r.reason = "maybe", f"score {r.score:.2f} ≥ {self.th_maybe}"
            else:
                r.bucket, r.reason = "skip", f"score {r.score:.2f} < {self.th_maybe}"
            for b, nxt in (("apply", "maybe"), ("maybe", "skip")):
                if r.bucket == b and taken[b] >= self.top_n[b]:
                    r.bucket, r.reason = nxt, r.reason + f" (over top_n.{b})"
            if r.bucket in taken:
                taken[r.bucket] += 1
