"""All database reads/writes go through ``Repository`` so the API, CLI and
pipeline never build queries themselves."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .models import BUCKETS, STATUSES, AgentReview, Decision, Job, Run, Score
from .sources import Posting
from .util import utc_now

HIDDEN = ("applied", "ignored", "closed")


class NotFound(LookupError):
    pass


class Repository:
    def __init__(self, session: Session):
        self.s = session

    # --- runs -----------------------------------------------------------------
    def start_run(self) -> Run:
        run = Run()
        self.s.add(run)
        self.s.flush()
        return run

    def latest_run(self) -> Run | None:
        return self.s.scalar(select(Run).where(Run.status == "succeeded").order_by(Run.id.desc()).limit(1))

    def list_runs(self, limit: int = 30) -> list[Run]:
        return list(self.s.scalars(select(Run).order_by(Run.id.desc()).limit(limit)))

    # --- jobs -----------------------------------------------------------------
    def upsert_postings(self, postings: Iterable[Posting], complete_companies: set[str], now: datetime) -> int:
        """Insert/refresh postings; close jobs that vanished from boards we fetched
        successfully (a failed fetch must not close a company's jobs). Returns #new."""
        postings = list(postings)
        existing = {j.id: j for j in self.s.scalars(select(Job).where(Job.id.in_([p.id for p in postings])))}
        new = 0
        for p in postings:
            job = existing.get(p.id)
            if job is None:
                job = Job(id=p.id, first_seen_at=now)
                self.s.add(job)
                new += 1
            for f in ("source", "company", "title", "url", "location", "posted_at", "departments", "employment_type", "content"):
                setattr(job, f, getattr(p, f))
            job.last_seen_at, job.is_open = now, True
        if complete_companies:
            seen = {p.id for p in postings}
            stale = select(Job).where(Job.is_open, Job.company.in_(complete_companies), Job.id.not_in(seen))
            for job in self.s.scalars(stale):
                job.is_open = False
        self.s.flush()
        return new

    def jobs_to_score(self) -> list[Job]:
        """Open jobs you haven't marked applied / ignored / closed."""
        q = (select(Job).outerjoin(Decision)
             .where(Job.is_open, or_(Decision.status.is_(None), Decision.status.not_in(HIDDEN))))
        return list(self.s.scalars(q))

    def get_job(self, job_id: str) -> Job:
        job = self.s.get(Job, job_id, options=[selectinload(Job.scores), selectinload(Job.decision), selectinload(Job.review)])
        if job is None:
            raise NotFound(job_id)
        return job

    def find_job(self, key: str) -> Job:
        """Resolve a full id, a unique id prefix (>= 6 chars) or a URL."""
        key = key.strip()
        if job := self.s.get(Job, key):
            return job
        if job := self.s.scalar(select(Job).where(Job.url == key).limit(1)):
            return job
        if len(key) >= 6:
            matches = list(self.s.scalars(select(Job).where(Job.id.startswith(key)).limit(2)))
            if len(matches) == 1:
                return matches[0]
        raise NotFound(key)

    # --- scores ---------------------------------------------------------------
    def add_scores(self, run: Run, rows: list[dict]) -> None:
        self.s.add_all(Score(run_id=run.id, **row) for row in rows)
        self.s.flush()

    def ranked(self, run: Run, bucket: str | None = None, status: str | None = None, q: str | None = None,
               limit: int = 200, offset: int = 0) -> tuple[list[tuple[Score, Job]], int]:
        """Jobs scored in ``run``, best first, with optional filters. Returns (rows, total)."""
        stmt = (select(Score, Job).join(Job).outerjoin(Decision)
                .where(Score.run_id == run.id)
                .options(selectinload(Job.decision), selectinload(Job.review)))
        if bucket:
            stmt = stmt.where(Score.bucket == bucket)
        if status == "new":
            stmt = stmt.where(or_(Decision.status.is_(None), Decision.status == "new"))
        elif status:
            stmt = stmt.where(Decision.status == status)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(or_(func.lower(Job.title).like(like), func.lower(Job.company).like(like),
                                  func.lower(Job.location).like(like)))
        total = self.s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.s.execute(stmt.order_by(Score.score.desc(), Job.id).limit(limit).offset(offset)).all()
        return [(r[0], r[1]) for r in rows], total

    # --- decisions ------------------------------------------------------------
    def set_decision(self, job_id: str, status: str | None = None, label: str | None = None,
                     note: str | None = None, clear_label: bool = False) -> Decision:
        if status is not None and status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        if label is not None and label not in BUCKETS:
            raise ValueError(f"label must be one of {', '.join(BUCKETS)}")
        job = self.get_job(job_id)
        d = job.decision or Decision(job_id=job_id)
        if status is not None:
            d.status = status
        if label is not None or clear_label:
            d.label = label
        if note is not None:
            d.note = note
        d.updated_at = utc_now()
        job.decision = d
        self.s.flush()
        return d

    def labeled(self, run: Run) -> list[tuple[Score, Job]]:
        stmt = (select(Score, Job).join(Job).join(Decision)
                .where(Score.run_id == run.id, Decision.label.is_not(None))
                .options(selectinload(Job.decision), selectinload(Job.review)))
        return [(r[0], r[1]) for r in self.s.execute(stmt).all()]

    # --- agent reviews --------------------------------------------------------
    def save_review(self, job: Job, review: AgentReview) -> AgentReview:
        if job.review is not None:
            self.s.delete(job.review)
            self.s.flush()
        job.review = review
        self.s.flush()
        return review
