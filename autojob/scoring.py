"""Stage 2: hard gates + keyword score + semantic similarity -> apply / maybe / skip."""

from __future__ import annotations

import re
from typing import Any

from .config import Workspace
from .semantic import get_backend
from .util import clean_text, compile_regexes, first_regex, first_term, has_term, read_json, utc_now, write_json

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


def location_allowed(job: dict, text: str, allow: list[re.Pattern], match_order: str) -> bool:
    loc = (job.get("location") or "").strip()
    if match_order != "text_only" and loc and not _VAGUE_LOCATION.match(loc):
        return first_regex(loc, allow) is not None
    # Location empty / vague (e.g. "In-Office", "5 Locations"): look in the JD instead
    # of rejecting outright, which is what the config always claimed to do.
    return first_regex(f"{loc}\n{text}", allow) is not None


# ----------------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------------
def keyword_hits(text: str, weights: dict[str, float]) -> tuple[float, list[str]]:
    score, hits = 0.0, []
    for k, w in (weights or {}).items():
        if has_term(text, str(k)):
            score += float(w)
            hits.append(str(k))
    return score, hits


def minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def job_text(job: dict, max_chars: int) -> str:
    parts = [job.get("title") or "", " ".join(job.get("departments") or []), job.get("content_plain") or ""]
    return clean_text("\n".join(parts))[:max_chars]


def score_jobs(jobs: list[dict], profile: str, cfg: dict, cache_path) -> list[dict]:
    sc = cfg["scoring"]
    allow_cfg = sc["location_allowlist"]
    allow = build_allowlist(allow_cfg) if allow_cfg.get("enabled") else []
    excl_phrases = sc.get("exclude_phrases") or []
    excl_regex = compile_regexes(sc.get("exclude_regex") or [])
    kw = sc["keywords"]
    sat = max(float(sc.get("hard_saturation") or 1.0), 1e-6)
    max_chars = int(sc["semantic"]["content_max_chars"])

    records, open_idx, open_texts = [], [], []
    for job in jobs:
        text = job_text(job, max_chars)
        gate = None
        if allow and not location_allowed(job, text, allow, allow_cfg.get("match_order", "location_then_text")):
            gate = "location not in allowlist"
        if gate is None:
            ph = first_term(text, excl_phrases)
            if ph:
                gate = f"excluded phrase: {ph}"
            else:
                rx = first_regex(text, excl_regex)
                if rx:
                    gate = f"excluded pattern: {rx.pattern}"

        title_score, title_hits = keyword_hits(job.get("title") or "", kw.get("title"))
        must, must_hits = keyword_hits(text, kw.get("must_have"))
        nice, nice_hits = keyword_hits(text, kw.get("nice_to_have"))
        neg, neg_hits = keyword_hits(text, kw.get("negative"))
        hard_raw = title_score + must + nice + neg
        rec = {
            "id": job["id"],
            "company": job.get("company"),
            "title": job.get("title"),
            "location": job.get("location"),
            "url": job.get("url"),
            "source": job.get("source"),
            "updated_at": job.get("updated_at"),
            "first_seen_date_utc": job.get("first_seen_date_utc"),
            "gate": gate,
            "hard": {"raw": hard_raw, "norm": min(1.0, max(0.0, hard_raw / sat)),
                     "title_hits": title_hits, "must_hits": must_hits, "nice_hits": nice_hits, "neg_hits": neg_hits},
            "semantic": {"raw": 0.0, "norm": 0.0},
            "score": 0.0,
        }
        records.append(rec)
        if gate is None:
            open_idx.append(len(records) - 1)
            open_texts.append(text)

    sem_cfg = sc["semantic"]
    backend = get_backend(sem_cfg["backend"], sem_cfg["model_name"], cache_path)
    raw = backend.score(profile, open_texts) if open_texts else []
    norm = minmax(raw)

    w_h, w_s = float(sc["weights"]["hard"]), float(sc["weights"]["semantic"])
    if backend.name == "none":
        w_h, w_s = 1.0, 0.0
    for i, r_raw, r_norm in zip(open_idx, raw, norm):
        rec = records[i]
        rec["semantic"] = {"raw": round(r_raw, 4), "norm": round(r_norm, 4)}
        rec["score"] = round(w_h * rec["hard"]["norm"] + w_s * r_norm, 4)
    for rec in records:
        rec["semantic_backend"] = backend.name
    return records


def triage(records: list[dict], cfg: dict) -> dict[str, list[dict]]:
    tri = cfg["triage"]
    th_apply, th_maybe = float(tri["thresholds"]["apply"]), float(tri["thresholds"]["maybe"])
    buckets: dict[str, list[dict]] = {"apply": [], "maybe": [], "skip": []}
    for r in sorted(records, key=lambda x: x["score"], reverse=True):
        if r["gate"]:
            r["bucket"], r["reason"] = "skip", r["gate"]
        elif r["score"] >= th_apply:
            r["bucket"], r["reason"] = "apply", f"score {r['score']:.2f} ≥ {th_apply}"
        elif r["score"] >= th_maybe:
            r["bucket"], r["reason"] = "maybe", f"score {r['score']:.2f} ≥ {th_maybe}"
        else:
            r["bucket"], r["reason"] = "skip", f"score {r['score']:.2f} < {th_maybe}"
        buckets[r["bucket"]].append(r)
    # Overflow beyond top_n is demoted, not silently dropped.
    for name, nxt in (("apply", "maybe"), ("maybe", "skip")):
        limit = int(tri["top_n"][name])
        overflow = buckets[name][limit:]
        buckets[name] = buckets[name][:limit]
        for r in overflow:
            r["bucket"], r["reason"] = nxt, r["reason"] + f" (over top_n.{name})"
        buckets[nxt] = sorted(overflow + buckets[nxt], key=lambda x: x["score"], reverse=True)
    return buckets


def run_scoring(ws: Workspace) -> dict[str, Any]:
    jobs_doc = read_json(ws.jobs_path, default={})
    if not jobs_doc:
        raise RuntimeError(f"{ws.jobs_path} not found – run `autojob fetch` first.")
    jobs = jobs_doc.get("jobs", [])
    profile = ws.read_profile()

    records = score_jobs(jobs, profile, ws.cfg, ws.cache_dir / "embeddings.json")
    buckets = triage(records, ws.cfg)

    by_id = {j["id"]: j for j in jobs}
    excerpt_chars = int(ws.cfg["triage"]["excerpt_chars"])
    top_total = int(ws.cfg["triage"]["top_n"]["candidates"])
    candidates = []
    for r in (buckets["apply"] + buckets["maybe"])[:top_total]:
        c = dict(r)
        c["jd_excerpt"] = clean_text(by_id.get(r["id"], {}).get("content_plain"))[:excerpt_chars]
        candidates.append(c)

    now = utc_now().isoformat()
    meta = {
        "generated_at_utc": now,
        "jobs_total": len(jobs),
        "counts": {k: len(v) for k, v in buckets.items()},
        "semantic_backend": records[0]["semantic_backend"] if records else None,
        "thresholds": ws.cfg["triage"]["thresholds"],
    }
    write_json(ws.scored_path, {"meta": meta, "jobs": buckets["apply"] + buckets["maybe"] + buckets["skip"]})
    write_json(ws.candidates_path, {"meta": meta, "candidates": candidates})
    return {"meta": meta, "buckets": buckets}
