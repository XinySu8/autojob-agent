from __future__ import annotations
import json
import re
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from .cli_ollama_llm import OllamaCLILLM
from .prompts import SYSTEM_INSTRUCTIONS, USER_TEMPLATE
from .output_model import AgentResult


def _extract_first_json(text: str) -> str:
    """
    Model may accidentally add extra text. We extract the first {...} block.
    This is a best-effort safety net.
    """
    text = text.strip()

    # Fast path: already JSON
    if text.startswith("{") and text.endswith("}"):
        return text

    # Find first JSON object by brace matching (simple heuristic)
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in model output")

    # heuristic scan for matching braces
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    raise ValueError("Unbalanced JSON braces in model output")


def run_one_job(
    llm: OllamaCLILLM,
    job: Dict[str, Any],
    max_retries: int = 2,
) -> AgentResult:
    prompt = SYSTEM_INSTRUCTIONS + "\n\n" + USER_TEMPLATE.format(
        job_uid=str(job.get("job_uid", "")),
        title=str(job.get("title", "")),
        company=str(job.get("company", "")),
        location=str(job.get("location", "")),
        apply_url=str(job.get("apply_url", "")),
        description=str(job.get("description", "") or job.get("jd", "") or ""),
    )

    last_err: Optional[str] = None

    for attempt in range(max_retries + 1):
        raw = llm.invoke(prompt)
        try:
            json_str = _extract_first_json(raw)
            data = json.loads(json_str)

            # Ensure job_uid present even if model forgets
            if "job_uid" not in data or not data["job_uid"]:
                data["job_uid"] = str(job.get("job_uid", ""))

            res = AgentResult.model_validate(data)

            # clamp score defensively
            if res.score < 0.0:
                res.score = 0.0
            if res.score > 1.0:
                res.score = 1.0
            return res

        except (json.JSONDecodeError, ValueError, ValidationError) as e:
            last_err = str(e)
            # Retry with a stricter reminder
            prompt = (
                SYSTEM_INSTRUCTIONS
                + "\n\nIMPORTANT: Your last output was invalid. Output ONLY valid JSON matching the schema.\n\n"
                + USER_TEMPLATE.format(
                    job_uid=str(job.get("job_uid", "")),
                    title=str(job.get("title", "")),
                    company=str(job.get("company", "")),
                    location=str(job.get("location", "")),
                    apply_url=str(job.get("apply_url", "")),
                    description=str(job.get("description", "") or job.get("jd", "") or ""),
                )
            )

    raise RuntimeError(f"Failed to get valid JSON after retries. Last error: {last_err}")