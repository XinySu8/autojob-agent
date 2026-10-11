"""REST API (FastAPI). Also serves the built React app when present."""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import __version__
from .agent import AgentUnavailable, JobAgent
from .config import Workspace
from .db import Database
from .evaluation import evaluate
from .models import Job, Run, Score
from .pipeline import Pipeline
from .repository import NotFound, Repository
from .schemas import (
    Bucket,
    DecisionIn,
    DecisionOut,
    EvalOut,
    JobDetail,
    JobPage,
    JobSummary,
    ReviewOut,
    RunOut,
    ScoreOut,
    Status,
    SystemMetrics,
)

STATIC_DIR = Path(__file__).parent / "static"


def _summary(job: Job, score: Score | None, run: Run | None) -> dict:
    d = job.decision
    return dict(
        id=job.id, company=job.company, title=job.title, location=job.location, url=job.url, source=job.source,
        posted_at=job.posted_at, first_seen_at=job.first_seen_at, is_open=job.is_open,
        is_new=bool(run and job.first_seen_at >= run.started_at),
        status=d.status if d else "new", label=d.label if d else None,
        score=ScoreOut.model_validate(score) if score else None,
        review_verdict=job.review.verdict if job.review and not job.review.fallback else None,
    )


def create_app(ws: Workspace, db: Database | None = None, pipeline: Pipeline | None = None,
               agent_factory: Callable[[], JobAgent] | None = None) -> FastAPI:
    db = db or ws.open_db()
    pipeline = pipeline or Pipeline(ws, db)
    agent_factory = agent_factory or (lambda: JobAgent.from_config(ws.cfg))
    run_lock = threading.Lock()

    app = FastAPI(title="AutoJob-Agent API", version=__version__)

    def repo() -> Iterator[Repository]:
        with db.session() as s:
            yield Repository(s)

    def session() -> Iterator[Session]:
        with db.session() as s:
            yield s

    @app.exception_handler(NotFound)
    def _not_found(_req, exc: NotFound):
        return JSONResponse(status_code=404, content={"detail": f"job not found: {exc}"})

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    # --- runs -------------------------------------------------------------
    @app.get("/api/runs", response_model=list[RunOut])
    def list_runs(r: Repository = Depends(repo)):
        return r.list_runs()

    @app.post("/api/runs", status_code=202)
    def start_run(background: BackgroundTasks) -> dict:
        if not run_lock.acquire(blocking=False):
            raise HTTPException(409, "a run is already in progress")

        def task():
            try:
                pipeline.run()
            finally:
                run_lock.release()

        background.add_task(task)
        return {"status": "started"}

    # --- jobs -------------------------------------------------------------
    @app.get("/api/jobs", response_model=JobPage)
    def list_jobs(bucket: Bucket | None = None, status: Status | None = None, q: str | None = None,
                  limit: int = Query(100, le=500), offset: int = 0, r: Repository = Depends(repo)):
        run = r.latest_run()
        if run is None:
            return JobPage(run=None, total=0, items=[])
        rows, total = r.ranked(run, bucket=bucket, status=status, q=q, limit=limit, offset=offset)
        return JobPage(run=RunOut.model_validate(run), total=total,
                       items=[JobSummary(**_summary(job, score, run)) for score, job in rows])

    @app.get("/api/jobs/{job_id}", response_model=JobDetail)
    def get_job(job_id: str, r: Repository = Depends(repo)):
        job, run = r.get_job(job_id), r.latest_run()
        current = next((sc for sc in job.scores if run and sc.run_id == run.id), None)
        return JobDetail(
            **_summary(job, current, run), departments=job.departments, content=job.content,
            note=job.decision.note if job.decision else "",
            history=[ScoreOut.model_validate(sc) for sc in job.scores],
            review=ReviewOut.model_validate(job.review) if job.review else None,
        )

    @app.patch("/api/jobs/{job_id}/decision", response_model=DecisionOut)
    def set_decision(job_id: str, body: DecisionIn, r: Repository = Depends(repo)):
        try:
            return r.set_decision(job_id, status=body.status, label=body.label, note=body.note,
                                  clear_label="label" in body.model_fields_set and body.label is None)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    @app.post("/api/jobs/{job_id}/review", response_model=ReviewOut)
    def review_job(job_id: str, force: bool = True, s: Session = Depends(session)):
        Repository(s).get_job(job_id)  # 404 early
        try:
            pipeline.review(agent_factory(), job_id=job_id, force=force)
        except AgentUnavailable as e:
            raise HTTPException(503, str(e)) from e
        s.expire_all()
        return Repository(s).get_job(job_id).review

    # --- evaluation -------------------------------------------------------
    @app.get("/api/eval", response_model=EvalOut)
    def get_eval(r: Repository = Depends(repo)):
        run = r.latest_run()
        rows = r.labeled(run) if run else []
        return EvalOut(
            run_id=run.id if run else None, labeled=len(rows),
            label_counts=dict(Counter(job.decision.label for _s, job in rows)),
            systems=[SystemMetrics(name=x.name, precision_at={str(k): v for k, v in x.precision_at.items()},
                                   bucket_accuracy=x.bucket_accuracy, agent_coverage=x.agent_coverage)
                     for x in evaluate(rows)],
        )

    # --- frontend (built React app) ----------------------------------------
    if (STATIC_DIR / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            return FileResponse(STATIC_DIR / "index.html")

    return app
