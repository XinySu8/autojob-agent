"""The daily pipeline: fetch every board → keep internship-like postings → store → score."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from functools import partial

from .config import Workspace
from .db import Database
from .models import Run, Score
from .repository import Repository
from .scoring import Scorer
from .sources import FetchError, HttpFn, Posting, build_sources, http_json
from .util import first_term, has_term, utc_now

log = logging.getLogger(__name__)


class PostingFilter:
    """Fetch-time relevance filter configured by the ``filters`` section."""

    def __init__(self, filters: dict):
        self.internship_any = filters.get("internship_any") or []
        self.ashby_types = {str(x).lower() for x in filters.get("ashby_internship_types") or []}
        self.domain_any = filters.get("domain_any") or []
        self.exclude_title = filters.get("exclude_title_any") or []
        self.locations_any = filters.get("locations_any") or []
        self.cap = int(filters.get("max_jobs_per_company") or 0)

    def title_ok(self, title: str) -> bool:
        return not self.internship_any or first_term(title, self.internship_any) is not None

    def reject_reason(self, p: Posting) -> str | None:
        if not (str(p.employment_type or "").lower() in self.ashby_types or self.title_ok(p.title)):
            return "not_internship"
        if first_term(p.title, self.exclude_title):  # title only: JDs often mention "Director"
            return "excluded_title"
        if self.domain_any and not first_term(f"{p.title}\n{' '.join(p.departments)}\n{p.content}", self.domain_any):
            return "domain_mismatch"
        if self.locations_any and not any(has_term(p.location, x) for x in self.locations_any):
            return "location_mismatch"
        return None

    def apply(self, postings: list[Posting]) -> tuple[list[Posting], Counter]:
        kept, dropped, per_company = [], Counter(), Counter()
        for p in postings:
            reason = self.reject_reason(p)
            if reason is None and self.cap and per_company[p.company] >= self.cap:
                reason = "company_cap"
            if reason:
                dropped[reason] += 1
            else:
                per_company[p.company] += 1
                kept.append(p)
        return kept, dropped


@dataclass
class FetchResult:
    postings: list[Posting]
    complete_companies: set[str]
    fetched: int
    warnings: list[str]


class Pipeline:
    def __init__(self, ws: Workspace, db: Database, http: HttpFn | None = None,
                 progress: Callable[[str], None] | None = None):
        self.ws = ws
        self.db = db
        fcfg = ws.cfg["fetch"]
        self.http = partial(http or http_json, timeout=int(fcfg["timeout"]), retries=int(fcfg["retries"]))
        self.workers = max(1, int(fcfg["workers"]))
        self.filter = PostingFilter(ws.cfg["filters"])
        self.progress = progress or (lambda _msg: None)

    def run(self) -> Run:
        """Fetch + score as one recorded run. A failure marks the run failed and re-raises."""
        with self.db.session() as s:
            run_id = Repository(s).start_run().id
        try:
            fetched = self.fetch()
            with self.db.session() as s:
                repo = Repository(s)
                run = s.get(Run, run_id)
                run.fetched, run.matched, run.warnings = fetched.fetched, len(fetched.postings), fetched.warnings
                run.new_jobs = repo.upsert_postings(fetched.postings, fetched.complete_companies, utc_now())
                self.score(repo, run)
                run.status, run.finished_at = "succeeded", utc_now()
                return run
        except Exception as e:
            with self.db.session() as s:
                run = s.get(Run, run_id)
                run.status, run.finished_at, run.error = "failed", utc_now(), f"{type(e).__name__}: {e}"
            raise

    def fetch(self) -> FetchResult:
        sources, warnings = build_sources(self.ws.cfg["fetch"]["targets"], http=self.http)
        postings: dict[str, Posting] = {}
        complete: set[str] = set()
        with ThreadPoolExecutor(self.workers) as pool:
            futures = {pool.submit(src.fetch, self.filter.title_ok): src for src in sources}
            for fut in as_completed(futures):
                src = futures[fut]
                try:
                    got = fut.result()
                except FetchError as e:
                    warnings.append(f"{src}: {e}")
                    self.progress(f"  {src}: FAILED – {e}")
                    continue
                except Exception as e:  # one broken board must never abort the run
                    log.exception("unexpected error for %s", src)
                    warnings.append(f"{src}: unexpected {type(e).__name__}: {e}")
                    continue
                complete.add(src.company)
                self.progress(f"  {src}: {len(got)} postings")
                for p in got:
                    postings.setdefault(p.id, p)
        kept, dropped = self.filter.apply(list(postings.values()))
        log.info("dropped: %s", dict(dropped))
        return FetchResult(kept, complete, len(postings), sorted(warnings))

    def score(self, repo: Repository, run: Run) -> None:
        scorer = Scorer(self.ws.cfg, self.ws.cache_dir / "embeddings.json")
        results = scorer.score(repo.jobs_to_score(), self.ws.read_profile())
        repo.add_scores(run, [r.row() for r in results])
        run.counts = dict(Counter(r.bucket for r in results))
        run.semantic_backend = scorer.backend.name

    def review(self, agent, limit: int | None = None, job_id: str | None = None, force: bool = False) -> dict[str, int]:
        """Run the AI agent on one job, or on the top apply/maybe jobs of the latest run.
        Reviews are skipped when job text, profile and model are unchanged."""
        profile = self.ws.read_profile()
        counts = Counter()
        with self.db.session() as s:
            repo = Repository(s)
            run = repo.latest_run()
            if job_id:
                job = repo.get_job(job_id)
                score = next((sc for sc in job.scores if run and sc.run_id == run.id), None)
                targets = [(score, job)]
            else:
                if run is None:
                    raise RuntimeError("no successful run yet – run `autojob run` first")
                rows, _ = repo.ranked(run, limit=limit or int(self.ws.cfg["agent"]["limit"]))
                targets = [(sc, j) for sc, j in rows if sc.bucket != "skip"]
            # Reviews are committed one by one so a long batch survives interruption.
            ids = [(sc.id if sc else None, j.id) for sc, j in targets]
        for score_id, jid in ids:
            with self.db.session() as s:
                repo = Repository(s)
                job = repo.get_job(jid)
                score = s.get(Score, score_id) if score_id else None
                if not force and job.review and job.review.input_hash == agent.input_hash(profile, job):
                    counts["unchanged"] += 1
                    continue
                review = repo.save_review(job, agent.review(profile, job, score))
                counts["fallback" if review.fallback else "reviewed"] += 1
                self.progress(f"  {review.verdict:<5} {job.company} – {job.title}" + (" (fallback)" if review.fallback else ""))
        return dict(counts)
