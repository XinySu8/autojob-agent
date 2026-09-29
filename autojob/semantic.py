"""Semantic similarity backends.

* ``sentence-transformers`` – best quality, needs ``pip install autojob-agent[semantic]``
  (pulls in PyTorch, ~1–2 GB).
* ``tfidf`` – zero-dependency fallback, pure Python. Good enough to rank JDs
  against a profile and keeps the base install tiny.
* ``none`` – keyword scoring only.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from pathlib import Path

from .util import read_json, sha1_text, write_json

log = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#.\-]*[a-z0-9+#]|[a-z0-9]")
_STOP = set("""
a an and are as at be been by for from has have in is it its of on or our that the their this to we will with you your
they them who what which when where how all any can may must not but also about into more other such than these those
able work team teams role roles job jobs company help new use using well including across within per etc
""".split())


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP and len(t) > 1]


class TfidfBackend:
    name = "tfidf"

    def score(self, profile: str, docs: list[str]) -> list[float]:
        tokenised = [_tokens(d) for d in docs]
        n = len(docs) + 1
        df: Counter = Counter()
        for toks in tokenised:
            df.update(set(toks))
        df.update(set(_tokens(profile)))
        idf = {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}

        def vec(toks: list[str]) -> dict[str, float]:
            tf = Counter(toks)
            v = {t: (1 + math.log(c)) * idf.get(t, 1.0) for t, c in tf.items()}
            norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
            return {t: x / norm for t, x in v.items()}

        pv = vec(_tokens(profile))
        out = []
        for toks in tokenised:
            dv = vec(toks)
            out.append(sum(w * dv.get(t, 0.0) for t, w in pv.items()))
        return out


class SentenceTransformerBackend:
    name = "sentence-transformers"

    def __init__(self, model_name: str, cache_path: Path):
        from sentence_transformers import SentenceTransformer  # optional dependency

        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        self.cache_path = cache_path
        cache = read_json(cache_path, default={})
        # Cache is keyed by model; switching models no longer reuses stale vectors.
        self.cache: dict = cache if cache.get("model") == model_name else {"model": model_name, "vectors": {}}

    def score(self, profile: str, docs: list[str]) -> list[float]:
        import numpy as np

        pv = self.model.encode([profile], normalize_embeddings=True)[0]
        vectors = self.cache["vectors"]
        keys = [sha1_text(d) for d in docs]
        missing = [(k, d) for k, d in zip(keys, docs) if k not in vectors]
        if missing:
            enc = self.model.encode([d for _, d in missing], normalize_embeddings=True, batch_size=32)
            for (k, _), v in zip(missing, enc):
                vectors[k] = [round(float(x), 6) for x in v]
        # Prune vectors for postings that are gone so the cache doesn't grow forever.
        live = set(keys)
        self.cache["vectors"] = {k: v for k, v in vectors.items() if k in live}
        write_json(self.cache_path, self.cache)
        return [float(np.dot(pv, np.asarray(self.cache["vectors"][k], dtype=np.float32))) for k in keys]


class NoneBackend:
    name = "none"

    def score(self, profile: str, docs: list[str]) -> list[float]:
        return [0.0 for _ in docs]


def get_backend(kind: str, model_name: str, cache_path: Path):
    if kind == "none":
        return NoneBackend()
    if kind == "tfidf":
        return TfidfBackend()
    try:
        return SentenceTransformerBackend(model_name, cache_path)
    except ImportError as e:
        if kind == "sentence-transformers":
            raise RuntimeError(
                "scoring.semantic.backend is 'sentence-transformers' but the package is not installed. "
                "Run: pip install 'autojob-agent[semantic]'"
            ) from e
        log.info("sentence-transformers not installed; using built-in TF-IDF similarity")
        return TfidfBackend()
