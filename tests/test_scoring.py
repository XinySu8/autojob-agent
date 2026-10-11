import pytest

from autojob.config import DEFAULTS
from autojob.scoring import REGION_PATTERNS, Scorer, build_allowlist, location_allowed
from autojob.sources import Posting
from autojob.util import compile_regexes


@pytest.mark.parametrize(
    "loc,text,ok",
    [
        ("Foster City, CA", "", True),
        ("Dallas, Texas", "", True),
        ("Toronto, ON", "", False),
        ("In-Office", "Our office in Austin, TX", True),  # vague location -> look in JD
        ("5 Locations", "", False),
        ("Remote - US", "", True),
        ("London, UK", "We pay in US dollars", False),    # specific location wins over JD text
        ("上海", "", True),
    ],
)
def test_location_allowlist(loc, text, ok):
    allow = build_allowlist({"regions": ["US", "China", "Singapore"]})
    assert location_allowed(loc, text, allow, "location_then_text") is ok


def test_unknown_region_rejected():
    with pytest.raises(ValueError):
        build_allowlist({"regions": ["Atlantis"]})
    assert {"US", "China", "Singapore"} <= set(REGION_PATTERNS)


def test_exclude_regex_needs_word_boundaries():
    rx = compile_regexes(["\\b(master'?s|m\\.s\\.)\\s+(degree\\s+)?(required|only)\\b"])[0]
    assert not rx.search("teams only work remotely") and rx.search("Master's degree required")


def _cfg(**triage):
    import copy

    cfg = copy.deepcopy(DEFAULTS)
    cfg["scoring"]["semantic"]["backend"] = "tfidf"
    cfg["scoring"]["keywords"] = {"title": {"software engineer": 3}, "must_have": {"python": 3, "sql": 2},
                                  "nice_to_have": {"rag": 2}, "negative": {"5+ years": -2}}
    cfg["scoring"]["exclude_phrases"] = ["security clearance"]
    cfg["triage"].update(triage)
    return cfg


def J(id, title, content, location="Seattle, WA"):
    return Posting(id=id, source="x", company="c", title=title, url="u", location=location, content=content)


def test_scorer_gates_hits_and_buckets(tmp_path):
    scorer = Scorer(_cfg(), tmp_path / "cache.json")
    res = {r.job_id: r for r in scorer.score([
        J("a", "Software Engineer Intern", "Python and SQL data pipelines with RAG"),
        J("b", "Data Intern", "Object storage, Python. 5+ years experience"),
        J("c", "Intern", "Active security clearance needed. Python"),
        J("d", "Intern", "Marketing and events"),
    ], "Python SQL data pipelines RAG LLM")}
    assert res["a"].hits == {"title": ["software engineer"], "must": ["python", "sql"], "nice": ["rag"], "negative": []}
    assert res["a"].bucket == "apply" and res["a"].score == 1.0
    assert "rag" not in res["b"].hits["nice"] and res["b"].hits["negative"] == ["5+ years"]  # "storage" is not "rag"
    assert res["c"].gate == "excluded phrase: security clearance" and res["c"].bucket == "skip"
    assert res["d"].bucket == "skip" and res["d"].reason.startswith("score")


def test_triage_demotes_overflow(tmp_path):
    scorer = Scorer(_cfg(top_n={"apply": 1, "maybe": 1}, thresholds={"apply": 0.0, "maybe": 0.0}), tmp_path / "c.json")
    res = scorer.score([J(str(i), "Intern", f"python {'sql ' * i}") for i in range(3)], "python sql")
    by = sorted(res, key=lambda r: -r.score)
    assert [r.bucket for r in by] == ["apply", "maybe", "skip"]
    assert "over top_n.apply" in by[1].reason
