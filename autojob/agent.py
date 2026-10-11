"""LLM job reviewer: structured verdict with evidence, validated before it is trusted.

Guardrails
1. Output must parse into ``AgentVerdict`` (Pydantic schema, enforced by the model's JSON mode).
2. Every evidence quote must appear verbatim in the job description – catches hallucination.
3. On failure the agent is re-prompted with the concrete errors (up to ``max_retries``);
   if it still fails, the rule-based bucket is kept and the review is flagged ``fallback``.
"""

from __future__ import annotations

import re
from typing import Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field, ValidationError

from .models import AgentReview, Job, Score
from .util import sha1_text

SYSTEM_PROMPT = """You screen internship / early-career job postings for one candidate.
Decide whether the candidate should apply, using ONLY the candidate profile and the job description.

- verdict: "apply" (strong fit, meets the core requirements), "maybe" (partial fit), "skip" (poor fit or a blocker).
- matches: requirements the candidate meets. gaps: requirements they miss, and blockers (citizenship, degree, seniority).
- Each item's "quote" MUST be copied word-for-word from the JOB DESCRIPTION (5-25 words). Never quote the profile.
- Never invent skills or experience that the profile does not state.
- summary: at most 2 sentences."""

_WS = re.compile(r"\s+")


class Evidence(BaseModel):
    point: str = Field(description="One requirement and how the candidate relates to it")
    quote: str = Field(description="Exact words copied from the job description")


class AgentVerdict(BaseModel):
    verdict: Literal["apply", "maybe", "skip"]
    confidence: float = Field(ge=0, le=1)
    summary: str
    matches: list[Evidence] = Field(default_factory=list, max_length=6)
    gaps: list[Evidence] = Field(default_factory=list, max_length=6)


class AgentUnavailable(RuntimeError):
    """The model could not be reached at all (as opposed to giving a bad answer)."""


def _norm(s: str) -> str:
    return _WS.sub(" ", s).strip().lower().strip(".\"'“”")


class JobAgent:
    def __init__(self, llm: Runnable, model_name: str, max_retries: int = 2, max_jd_chars: int = 6000,
                 unavailable_errors: tuple[type[Exception], ...] = (ConnectionError,)):
        self.llm = llm  # a Runnable that returns AgentVerdict (or a dict matching it)
        self.model_name = model_name
        self.unavailable_errors = unavailable_errors  # client-specific "can't reach model" exceptions
        self.max_retries = max_retries
        self.max_jd_chars = max_jd_chars

    @classmethod
    def from_config(cls, cfg: dict, model: str | None = None) -> JobAgent:
        try:
            import httpx
            import ollama
            from langchain_ollama import ChatOllama
        except ImportError as e:
            raise AgentUnavailable("Agent needs the extra: pip install 'autojob-agent[agent]'") from e
        a = cfg["agent"]
        name = model or a["model"]
        llm = ChatOllama(model=name, base_url=a["ollama_url"], temperature=0, num_ctx=8192)
        # ResponseError covers "model not found – pull it first"; TransportError covers "server not running".
        return cls(llm.with_structured_output(AgentVerdict), name, int(a["max_retries"]),
                   unavailable_errors=(ConnectionError, httpx.TransportError, ollama.ResponseError))

    def input_hash(self, profile: str, job: Job) -> str:
        return sha1_text(f"{self.model_name}\n{profile}\n{job.title}\n{job.content}")

    def messages(self, profile: str, job: Job, score: Score | None) -> list[BaseMessage]:
        signals = ""
        if score is not None:
            hits = ", ".join(dict.fromkeys(sum(score.hits.values(), []))) or "none"
            signals = f"\n\nRULE-BASED SIGNALS (hints, not evidence): bucket={score.bucket}, score={score.score:.2f}, keyword hits: {hits}"
        jd = job.content[: self.max_jd_chars] or "(no description provided)"
        return [
            SystemMessage(SYSTEM_PROMPT),
            HumanMessage(f"CANDIDATE PROFILE:\n{profile}\n\nJOB: {job.title} at {job.company} ({job.location})\n\n"
                         f"JOB DESCRIPTION:\n{jd}{signals}"),
        ]

    def check(self, verdict: AgentVerdict, jd: str) -> list[str]:
        """Return guardrail violations (empty = trustworthy)."""
        haystack = _norm(jd)
        return [f'quote not found in job description: "{e.quote}"'
                for e in verdict.matches + verdict.gaps if _norm(e.quote) not in haystack]

    def review(self, profile: str, job: Job, score: Score | None) -> AgentReview:
        msgs = self.messages(profile, job, score)
        jd = job.content[: self.max_jd_chars]
        errors: list[str] = []
        for attempt in range(1, self.max_retries + 2):
            try:
                out = self.llm.invoke(msgs)
                verdict = out if isinstance(out, AgentVerdict) else AgentVerdict.model_validate(out)
                errors = self.check(verdict, jd)
            except (ValidationError, ValueError) as e:  # schema violation / unparsable output
                verdict, errors = None, [f"output did not match the schema: {str(e)[:300]}"]
            except self.unavailable_errors as e:
                raise AgentUnavailable(f"cannot use model '{self.model_name}' at Ollama: {e}") from e
            if not errors:
                return self._to_review(verdict, profile, job, attempt)
            msgs = [*msgs, AIMessage(verdict.model_dump_json() if verdict else "(invalid)"),
                    HumanMessage("Fix these problems and answer again:\n- " + "\n- ".join(errors))]

        fallback = AgentVerdict(verdict=score.bucket if score else "maybe", confidence=0.0,
                                summary="Agent output failed validation; kept the rule-based bucket. " + "; ".join(errors)[:300])
        review = self._to_review(fallback, profile, job, self.max_retries + 1)
        review.fallback = True
        return review

    def _to_review(self, v: AgentVerdict, profile: str, job: Job, attempts: int) -> AgentReview:
        return AgentReview(
            job_id=job.id, model=self.model_name, verdict=v.verdict, confidence=v.confidence, summary=v.summary,
            matches=[e.model_dump() for e in v.matches], gaps=[e.model_dump() for e in v.gaps],
            attempts=attempts, fallback=False, input_hash=self.input_hash(profile, job),
        )
