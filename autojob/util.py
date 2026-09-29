"""Shared helpers: file IO, text cleanup, keyword matching, time parsing."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

_WS_RE = re.compile(r"\s+")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
_TAG_RE = re.compile(r"<[^>]+>")


# ----------------------------------------------------------------------------
# File IO
# ----------------------------------------------------------------------------
def read_json(path: str | Path, default: Any = None) -> Any:
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        if default is not None:
            return default
        raise


def write_json(path: str | Path, obj: Any) -> None:
    """Atomic JSON write (temp file + rename) so a crash never leaves a half file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def write_text(path: str | Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8-sig")


# ----------------------------------------------------------------------------
# Text
# ----------------------------------------------------------------------------
def html_to_text(s: str | None) -> str:
    if not s:
        return ""
    # Greenhouse returns HTML-escaped HTML, so unescape first, then strip tags,
    # then unescape again for entities that were inside the markup.
    s = html.unescape(s)
    s = _TAG_RE.sub(" ", s)
    s = html.unescape(s)
    return clean_text(s)


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = _CONTROL_RE.sub(" ", s)
    s = s.replace(" ", " ")
    return _WS_RE.sub(" ", s).strip()


def sha1_text(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def stable_id(*parts: str) -> str:
    return hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()[:16]


# ----------------------------------------------------------------------------
# Keyword matching
# ----------------------------------------------------------------------------
@lru_cache(maxsize=4096)
def term_regex(term: str) -> re.Pattern:
    """Whole-term, case-insensitive matcher.

    Plain substring matching produced many false positives in earlier versions
    ("rag" in "storage", "git" in "digital", "ms required" in "systems required").
    Boundaries are "not a letter/digit", so hyphenated or dotted terms
    ("co-op", "vue.js", "c++") still work.
    """
    t = re.escape(term.strip())
    t = t.replace(r"\ ", r"\s+")  # tolerate any whitespace inside phrases
    return re.compile(r"(?<![A-Za-z0-9])" + t + r"(?![A-Za-z0-9])", re.IGNORECASE)


def has_term(text: str, term: str) -> bool:
    return bool(term and term.strip() and term_regex(term).search(text or ""))


def first_term(text: str, terms: Iterable[str]) -> str | None:
    for t in terms or []:
        if isinstance(t, str) and t.strip() and has_term(text, t):
            return t
    return None


def compile_regexes(patterns: Iterable[str]) -> list[re.Pattern]:
    out = []
    for p in patterns or []:
        if isinstance(p, str) and p.strip():
            out.append(re.compile(p, re.IGNORECASE))
    return out


def first_regex(text: str, regexes: Iterable[re.Pattern]) -> re.Pattern | None:
    for rx in regexes:
        if rx.search(text or ""):
            return rx
    return None


# ----------------------------------------------------------------------------
# Time
# ----------------------------------------------------------------------------
def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: Any) -> str | None:
    """Normalise timestamps from different ATS APIs to ISO-8601 UTC strings.

    Lever returns epoch milliseconds (int) while others return ISO strings;
    mixing them used to break sorting.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        ts = value / 1000.0 if value > 1e11 else float(value)
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    if isinstance(value, str):
        v = value.strip()
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            return v  # e.g. Workday "Posted 3 Days Ago" – keep as-is
    return str(value)


def iso_sort_key(value: Any) -> str:
    """Sort key that puts real ISO timestamps before free-form strings."""
    if isinstance(value, str) and value[:4].isdigit():
        return value
    return ""
