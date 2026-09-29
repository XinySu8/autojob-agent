"""Workspace + configuration loading.

A *workspace* is a directory holding ``autojob.yaml`` and ``profile.md``.
Every path in the config is resolved relative to the workspace, so the tool
behaves the same no matter which directory it is launched from.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

CONFIG_NAME = "autojob.yaml"
ENV_CONFIG = "AUTOJOB_CONFIG"

DEFAULTS: dict[str, Any] = {
    "profile": "profile.md",
    "data_dir": "data",
    "fetch": {"timeout": 30, "workers": 8, "retries": 2, "workday_details": True, "targets": []},
    "filters": {
        "internship_any": [],
        "ashby_internship_types": [],
        "domain_any": [],
        "exclude_title_any": [],
        "locations_any": [],
        "max_jobs_per_company": 500,
    },
    "scoring": {
        "location_allowlist": {"enabled": False, "regions": [], "allow_regex": [], "match_order": "location_then_text"},
        "exclude_phrases": [],
        "exclude_regex": [],
        "keywords": {"title": {}, "must_have": {}, "nice_to_have": {}, "negative": {}},
        "hard_saturation": 10.0,
        "semantic": {
            "backend": "auto",
            "model_name": "sentence-transformers/all-MiniLM-L6-v2",
            "content_max_chars": 8000,
        },
        "weights": {"hard": 0.45, "semantic": 0.55},
    },
    "triage": {
        "thresholds": {"apply": 0.60, "maybe": 0.35},
        "top_n": {"apply": 50, "maybe": 120, "candidates": 150},
        "excerpt_chars": 600,
    },
    "cards": {
        "model": "qwen2.5:3b",
        "ollama_url": "http://localhost:11434",
        "timeout": 240,
        "limit": 20,
    },
}


class ConfigError(RuntimeError):
    pass


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class Workspace:
    root: Path
    cfg: dict[str, Any]

    # --- paths -------------------------------------------------------------
    @property
    def config_path(self) -> Path:
        return self.root / CONFIG_NAME

    @property
    def profile_path(self) -> Path:
        return self.root / self.cfg["profile"]

    @property
    def data_dir(self) -> Path:
        return self.root / self.cfg["data_dir"]

    @property
    def state_path(self) -> Path:
        return self.data_dir / "state.json"

    @property
    def jobs_path(self) -> Path:
        return self.data_dir / "jobs.json"

    @property
    def scored_path(self) -> Path:
        return self.data_dir / "scored.json"

    @property
    def candidates_path(self) -> Path:
        return self.data_dir / "candidates.json"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def archive_dir(self) -> Path:
        return self.data_dir / "archive"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def cards_dir(self) -> Path:
        return self.data_dir / "cards"

    def read_profile(self) -> str:
        if not self.profile_path.exists():
            raise ConfigError(f"Profile not found: {self.profile_path}. Run `autojob init` first.")
        return self.profile_path.read_text(encoding="utf-8-sig")


def find_config(start: str | Path | None = None) -> Path:
    """Locate autojob.yaml: explicit path > $AUTOJOB_CONFIG > walk up from cwd."""
    if start:
        p = Path(start).expanduser()
        if p.is_dir():
            p = p / CONFIG_NAME
        if not p.exists():
            raise ConfigError(f"Config not found: {p}")
        return p.resolve()

    env = os.environ.get(ENV_CONFIG)
    if env:
        return find_config(env)

    cur = Path.cwd().resolve()
    for d in [cur, *cur.parents]:
        if (d / CONFIG_NAME).exists():
            return d / CONFIG_NAME
    raise ConfigError(
        f"No {CONFIG_NAME} found in {cur} or its parents. "
        "Run `autojob init` to create a workspace, or pass --config."
    )


def validate(cfg: dict[str, Any]) -> list[str]:
    """Return a list of human-readable problems (empty list = OK)."""
    problems = []
    w = cfg["scoring"]["weights"]
    try:
        if abs(float(w["hard"]) + float(w["semantic"]) - 1.0) > 1e-6:
            problems.append("scoring.weights.hard + scoring.weights.semantic should sum to 1.0")
    except (KeyError, TypeError, ValueError):
        problems.append("scoring.weights must contain numeric 'hard' and 'semantic'")
    th = cfg["triage"]["thresholds"]
    if float(th["maybe"]) > float(th["apply"]):
        problems.append("triage.thresholds.maybe must be <= triage.thresholds.apply")
    backend = cfg["scoring"]["semantic"]["backend"]
    if backend not in ("auto", "sentence-transformers", "tfidf", "none"):
        problems.append(f"scoring.semantic.backend '{backend}' is not one of auto|sentence-transformers|tfidf|none")
    if not cfg["fetch"]["targets"]:
        problems.append("fetch.targets is empty – nothing will be fetched")
    return problems


def load(config: str | Path | None = None) -> Workspace:
    path = find_config(config)
    with open(path, encoding="utf-8-sig") as f:
        user_cfg = yaml.safe_load(f) or {}
    if not isinstance(user_cfg, dict):
        raise ConfigError(f"{path} must be a YAML mapping")
    cfg = _deep_merge(DEFAULTS, user_cfg)
    problems = validate(cfg)
    fatal = [p for p in problems if "empty" not in p]
    if fatal:
        raise ConfigError("Invalid config:\n  - " + "\n  - ".join(fatal))
    return Workspace(root=path.parent, cfg=cfg)


def template_text(name: str) -> str:
    return resources.files("autojob.templates").joinpath(name).read_text(encoding="utf-8")


def init_workspace(target: str | Path, force: bool = False) -> list[Path]:
    """Copy starter config + profile into ``target``. Returns created files."""
    root = Path(target).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    created = []
    for name in (CONFIG_NAME, "profile.md"):
        dst = root / name
        if dst.exists() and not force:
            continue
        dst.write_text(template_text(name), encoding="utf-8")
        created.append(dst)
    gi = root / ".gitignore"
    if not gi.exists():
        gi.write_text("data/\n", encoding="utf-8")
        created.append(gi)
    return created
