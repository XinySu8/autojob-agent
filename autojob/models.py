"""Database schema.

jobs ──< scores >── runs        one score row per job per pipeline run (history)
  ├── decision                   your status (applied / ignored …) + eval label
  └── review                     latest AI-agent verdict
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime, TypeDecorator

from .util import utc_now

BUCKETS = ("apply", "maybe", "skip")
STATUSES = ("new", "applied", "ignored", "closed")


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend (SQLite drops tzinfo otherwise)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source: Mapped[str] = mapped_column(String(20))
    company: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(1000))
    location: Mapped[str] = mapped_column(String(500), default="")
    posted_at: Mapped[str | None] = mapped_column(String(40))
    departments: Mapped[list[str]] = mapped_column(JSON, default=list)
    employment_type: Mapped[str | None] = mapped_column(String(50))
    content: Mapped[str] = mapped_column(Text, default="")
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    decision: Mapped[Decision | None] = relationship(back_populates="job", cascade="all, delete-orphan")
    review: Mapped[AgentReview | None] = relationship(back_populates="job", cascade="all, delete-orphan")
    scores: Mapped[list[Score]] = relationship(back_populates="job", order_by="Score.run_id", cascade="all, delete-orphan")

    @property
    def status(self) -> str:
        return self.decision.status if self.decision else "new"


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | succeeded | failed
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    matched: Mapped[int] = mapped_column(Integer, default=0)
    new_jobs: Mapped[int] = mapped_column(Integer, default=0)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)  # {"apply": n, "maybe": n, "skip": n}
    semantic_backend: Mapped[str | None] = mapped_column(String(40))
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text)


class Score(Base):
    __tablename__ = "scores"
    __table_args__ = (UniqueConstraint("run_id", "job_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    bucket: Mapped[str] = mapped_column(String(10))
    score: Mapped[float] = mapped_column(Float)
    keyword_score: Mapped[float] = mapped_column(Float)
    semantic_score: Mapped[float] = mapped_column(Float)
    gate: Mapped[str | None] = mapped_column(String(200))
    hits: Mapped[dict] = mapped_column(JSON, default=dict)  # {"title": [...], "must": [...], "nice": [...], "negative": [...]}
    reason: Mapped[str] = mapped_column(String(300))

    job: Mapped[Job] = relationship(back_populates="scores")


class Decision(Base):
    __tablename__ = "decisions"

    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(10), default="new")
    label: Mapped[str | None] = mapped_column(String(10))  # ground truth for evaluation: apply | maybe | skip
    note: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now)

    job: Mapped[Job] = relationship(back_populates="decision")


class AgentReview(Base):
    __tablename__ = "agent_reviews"

    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    model: Mapped[str] = mapped_column(String(100))
    verdict: Mapped[str] = mapped_column(String(10))
    confidence: Mapped[float] = mapped_column(Float)
    summary: Mapped[str] = mapped_column(Text)
    matches: Mapped[list[dict]] = mapped_column(JSON, default=list)  # [{"point": .., "quote": ..}]
    gaps: Mapped[list[dict]] = mapped_column(JSON, default=list)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    fallback: Mapped[bool] = mapped_column(Boolean, default=False)  # True = agent failed validation, rule bucket used
    input_hash: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    job: Mapped[Job] = relationship(back_populates="review")
