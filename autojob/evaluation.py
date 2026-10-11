"""Offline evaluation against your own labels (Decision.label).

Compares three rankers on the same labeled jobs:
  keywords          – keyword score only
  rules+semantic    – production score (keywords + semantic similarity)
  rules+agent       – agent verdict where a review exists, rules otherwise
Metrics: precision@k (relevant = labeled "apply") and bucket accuracy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .models import Job, Score

_RANK = {"apply": 2, "maybe": 1, "skip": 0}
Row = tuple[Score, Job]


@dataclass
class SystemResult:
    name: str
    precision_at: dict[int, float | None]
    bucket_accuracy: float | None
    agent_coverage: float | None = None


def precision_at_k(ranked_labels: list[str], k: int) -> float | None:
    if len(ranked_labels) < k:
        return None  # not enough labeled jobs for this k – don't report a misleading number
    return sum(lbl == "apply" for lbl in ranked_labels[:k]) / k


def _agent_bucket(score: Score, job: Job) -> str:
    r = job.review
    return r.verdict if r is not None and not r.fallback else score.bucket


def _agent_key(row: Row) -> tuple:
    score, job = row
    r = job.review
    if r is not None and not r.fallback:
        return (_RANK[r.verdict], r.confidence, score.score)
    return (_RANK[score.bucket], 0.5, score.score)


SYSTEMS: dict[str, tuple[Callable[[Row], tuple], Callable[[Score, Job], str] | None]] = {
    "keywords": (lambda row: (row[0].keyword_score,), None),
    "rules+semantic": (lambda row: (row[0].score,), lambda s, _j: s.bucket),
    "rules+agent": (_agent_key, _agent_bucket),
}


def evaluate(rows: list[Row], ks: tuple[int, ...] = (5, 10, 20)) -> list[SystemResult]:
    results = []
    for name, (key, bucket_of) in SYSTEMS.items():
        ranked = sorted(rows, key=key, reverse=True)
        labels = [job.decision.label for _s, job in ranked]
        acc = None
        if bucket_of and rows:
            acc = sum(bucket_of(s, j) == j.decision.label for s, j in rows) / len(rows)
        coverage = None
        if name == "rules+agent" and rows:
            coverage = sum(1 for _s, j in rows if j.review is not None and not j.review.fallback) / len(rows)
        results.append(SystemResult(name, {k: precision_at_k(labels, k) for k in ks}, acc, coverage))
    return results
