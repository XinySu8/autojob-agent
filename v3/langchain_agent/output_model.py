from __future__ import annotations
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


Decision = Literal["apply", "maybe", "skip"]


class Evidence(BaseModel):
    field: str = Field(..., description="What this evidence refers to, e.g., 'jd_snippet', 'requirements'")
    snippet: str = Field(..., description="Short quote/excerpt from the JD supporting a reason")


class AgentResult(BaseModel):
    job_uid: str
    decision: Decision
    score: float = Field(..., ge=0.0, le=1.0, description="Agent confidence in decision, 0-1")
    reasons: List[str] = Field(default_factory=list, description="Short reason codes/phrases (keep stable)")
    missing_info: List[str] = Field(default_factory=list, description="Questions/unknowns blocking a confident decision")
    risk_flags: List[str] = Field(default_factory=list, description="e.g., clearance, visa, onsite, relocation, unpaid")
    evidence: List[Evidence] = Field(default_factory=list)
    notes: str = Field("", description="Short human-readable summary (1-3 sentences)")