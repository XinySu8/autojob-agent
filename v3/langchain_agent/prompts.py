from __future__ import annotations

SYSTEM_INSTRUCTIONS = """You are a careful job-triage agent.
You must output ONLY valid JSON, with no extra text, no markdown, no code fences.

Rules:
- Use ONLY the information provided in the input job posting text.
- Do NOT invent facts.
- If important info is missing, put it in missing_info.
- Keep reasons and risk_flags short and consistent.
"""

USER_TEMPLATE = """Analyze the job and return a JSON object with this shape:

{{
  "job_uid": "...",
  "decision": "apply|maybe|skip",
  "score": 0.0-1.0,
  "reasons": ["..."],
  "missing_info": ["..."],
  "risk_flags": ["..."],
  "evidence": [{{"field":"...","snippet":"..."}}],
  "notes": "..."
}}

Job UID: {job_uid}
Title: {title}
Company: {company}
Location: {location}
Apply URL: {apply_url}

Job Description:
{description}
"""