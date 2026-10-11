"""API request/response models. The frontend's TypeScript types are generated from these
(via the OpenAPI schema), so this file is the single source of truth for the contract."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

Bucket = Literal["apply", "maybe", "skip"]
Status = Literal["new", "applied", "ignored", "closed"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RunOut(ORM):
    id: int
    started_at: datetime
    finished_at: datetime | None
    status: Literal["running", "succeeded", "failed"]
    fetched: int
    matched: int
    new_jobs: int
    counts: dict[str, int]
    semantic_backend: str | None
    warnings: list[str]
    error: str | None


class ScoreOut(ORM):
    run_id: int
    bucket: Bucket
    score: float
    keyword_score: float
    semantic_score: float
    gate: str | None
    hits: dict[str, list[str]]
    reason: str


class Evidence(BaseModel):
    point: str
    quote: str


class ReviewOut(ORM):
    model: str
    verdict: Bucket
    confidence: float
    summary: str
    matches: list[Evidence]
    gaps: list[Evidence]
    attempts: int
    fallback: bool
    created_at: datetime


class DecisionIn(BaseModel):
    status: Status | None = None
    label: Bucket | None = None  # send null to clear
    note: str | None = None


class DecisionOut(ORM):
    status: Status
    label: Bucket | None
    note: str
    updated_at: datetime


class JobSummary(BaseModel):
    id: str
    company: str
    title: str
    location: str
    url: str
    source: str
    posted_at: str | None
    first_seen_at: datetime
    is_new: bool  # first seen in the run being shown
    is_open: bool
    status: Status
    label: Bucket | None
    score: ScoreOut | None
    review_verdict: Bucket | None


class JobDetail(JobSummary):
    departments: list[str]
    content: str
    note: str
    history: list[ScoreOut]  # one entry per run, oldest first
    review: ReviewOut | None


class JobPage(BaseModel):
    run: RunOut | None
    total: int
    items: list[JobSummary]


class SystemMetrics(BaseModel):
    name: str
    precision_at: dict[str, float | None]
    bucket_accuracy: float | None
    agent_coverage: float | None


class EvalOut(BaseModel):
    run_id: int | None
    labeled: int
    label_counts: dict[str, int]
    systems: list[SystemMetrics]
