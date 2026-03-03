from __future__ import annotations
import subprocess
from typing import Any, List, Optional
import os

from langchain_core.language_models.llms import LLM


class OllamaCLILLM(LLM):
    model: str
    timeout_s: int = 600

    @property
    def _llm_type(self) -> str:
        return "ollama_cli"

    @property
    def _identifying_params(self) -> dict:
        return {"model": self.model, "timeout_s": self.timeout_s}

    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> str:
        # One-shot CLI call (avoid interactive mode)
        proc = subprocess.run(
            ["ollama", "run", self.model, "--", prompt],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout_s,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        )

        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()

        if proc.returncode != 0:
            raise RuntimeError(
                f"ollama CLI failed rc={proc.returncode} stderr={err[:500]} stdout={out[:200]}"
            )

        # Apply stop sequences if provided
        if stop:
            for s in stop:
                if s and s in out:
                    out = out.split(s)[0]

        return out
    

    
