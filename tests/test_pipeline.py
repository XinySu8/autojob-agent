import json

import pytest

from autojob import cli
from autojob.cards import build_prompt, generate_cards
from autojob.config import ConfigError, load, template_text
from autojob.fetch import apply_filters, fetch_all
from autojob.report import write_reports
from autojob.scoring import REGION_PATTERNS, build_allowlist, location_allowed, run_scoring, triage
from autojob.sources import _workday_parts, fetch_workday, normalize_targets
from autojob.state import find_job, load_state, set_status
from autojob.util import compile_regexes

from .conftest import fake_http


def titles(jobs):
    return sorted(j["title"] for j in jobs)


def test_fetch_filters_and_state(ws):
    payload = fetch_all(ws, http=fake_http)
    assert titles(payload["jobs"]) == [
        "AI Research Intern", "Data Engineering Intern", "Machine Learning Intern", "Product Engineer",
        "Software Engineer Intern", "Software Intern",
    ]
    # unsupported source is reported, not fatal
    assert any("smartrecruiters" in e for e in payload["errors"])
    # Lever epoch ms -> ISO
    lever = next(j for j in payload["jobs"] if j["source"] == "lever")
    assert lever["created_at"].startswith("2026-01-01")
    assert "Git" in lever["content_plain"]
    state = load_state(ws.state_path)
    assert len(state["jobs"]) == 6
    assert all(r["status"] == "new" for r in state["jobs"].values())


def test_exclude_title_only_checks_title():
    jobs = [
        {"id": "1", "title": "Software Intern", "content_plain": "report to the Director", "company": "x"},
        {"id": "2", "title": "Director Intern Programs", "content_plain": "", "company": "x"},
    ]
    kept, dropped = apply_filters(jobs, {"internship_any": ["intern"], "exclude_title_any": ["director"]})
    assert [j["id"] for j in kept] == ["1"]
    assert dropped[0]["reason"] == "excluded_title:director"


def test_one_failing_target_does_not_abort(ws):
    def flaky(url, **kw):
        if "lever" in url:
            raise RuntimeError("boom")
        return fake_http(url, **kw)

    payload = fetch_all(ws, http=flaky)
    assert any("lev (lever): unexpected RuntimeError" in e for e in payload["errors"])
    assert payload["count"] == 5


def test_scoring_gates_and_buckets(ws):
    fetch_all(ws, http=fake_http)
    res = run_scoring(ws)
    by_title = {r["title"]: r for b in res["buckets"].values() for r in b}

    assert by_title["Machine Learning Intern"]["gate"] == "location not in allowlist"  # London
    # "In-Office" falls back to JD text (Seattle, WA) -> passes allowlist, but clearance gate hits
    assert by_title["Data Engineering Intern"]["gate"].startswith("excluded")
    # "storage systems required" must NOT trip the "ms required" rule; "storage" is not "rag"
    swi = by_title["Software Intern"]
    assert swi["gate"] is None
    assert "rag" not in swi["hard"]["nice_hits"]
    # Best match should be apply
    assert by_title["Software Engineer Intern"]["bucket"] == "apply"
    assert (ws.candidates_path).exists()
    cands = json.loads(ws.candidates_path.read_text())["candidates"]
    assert cands and all(c["bucket"] in ("apply", "maybe") for c in cands)
    assert cands[0]["jd_excerpt"]


def test_marked_jobs_are_hidden_on_next_fetch(ws):
    fetch_all(ws, http=fake_http)
    state = load_state(ws.state_path)
    jid = find_job(state, "https://gh.example/1")
    assert jid and find_job(state, jid[:8]) == jid
    set_status(state, jid, "applied", "sent resume")
    ws.state_path.write_text(json.dumps(state))
    payload = fetch_all(ws, http=fake_http)
    assert jid not in {j["id"] for j in payload["jobs"]}
    assert load_state(ws.state_path)["jobs"][jid]["note"] == "sent resume"


def test_set_status_rejects_unknown():
    with pytest.raises(ValueError):
        set_status({"jobs": {}}, "x", "maybe")


@pytest.mark.parametrize(
    "loc,text,ok",
    [
        ("Foster City, CA", "", True),       # used to be rejected (only "California" was listed)
        ("Dallas, Texas", "", True),
        ("Toronto, ON", "", False),
        ("In-Office", "Our office in Austin, TX", True),
        ("5 Locations", "", False),
        ("Remote - US", "", True),
        ("London, UK", "We use US dollars", False),  # location wins when it is specific
        ("上海", "", True),
    ],
)
def test_location_allowlist(loc, text, ok):
    allow = build_allowlist({"regions": ["US", "China", "Singapore"]})
    assert location_allowed({"location": loc}, text, allow, "location_then_text") is ok


def test_unknown_region_is_an_error():
    with pytest.raises(ValueError):
        build_allowlist({"regions": ["Atlantis"]})
    assert set(REGION_PATTERNS) >= {"US", "China", "Singapore"}


def test_exclude_regex_word_boundaries():
    rx = compile_regexes(["\\b(master'?s|m\\.s\\.)\\s+(degree\\s+)?(required|only)\\b"])
    assert not rx[0].search("teams only work remotely")
    assert rx[0].search("Master's degree required")


def test_triage_top_n_demotes_overflow():
    cfg = {"triage": {"thresholds": {"apply": 0.5, "maybe": 0.2}, "top_n": {"apply": 1, "maybe": 5}}}
    recs = [{"gate": None, "score": s} for s in (0.9, 0.8, 0.3, 0.1)]
    b = triage(recs, cfg)
    assert [r["score"] for r in b["apply"]] == [0.9]
    assert [r["score"] for r in b["maybe"]] == [0.8, 0.3]
    assert "over top_n.apply" in b["maybe"][0]["reason"]


def test_reports_render(ws):
    fetch_all(ws, http=fake_http)
    run_scoring(ws)
    paths = write_reports(ws)
    html = paths["html"].read_text()
    assert "/*__DATA__*/" not in html and "Software Engineer Intern" in html
    md = paths["markdown"].read_text()
    assert "## Apply" in md and "## Skip" in md


def test_normalize_targets():
    t, w = normalize_targets([
        {"company": "a", "source": "Greenhouse", "board_token": "a"},
        {"company": "a2", "source": "greenhouse", "board_token": "A"},  # dup (case-insensitive)
        {"company": "b", "source": "ashby", "board_token": "b"},        # auto-fixed key
        {"company": "c", "source": "lever"},                            # missing key
        {"company": "d", "source": "lever", "lever_slug": "d", "enabled": False},
    ])
    assert [x["company"] for x in t] == ["a", "b"]
    assert t[1]["job_board_name"] == "b"
    assert any("needs 'lever_slug'" in x for x in w)


def test_workday_uses_post_and_details():
    calls = []

    def http(url, method="GET", data=None, **_):
        calls.append((method, url, data))
        if url.endswith("/jobs"):
            return {"total": 2, "jobPostings": [
                {"title": "Software Engineering Intern", "externalPath": "/job/SF/Intern_1", "locationsText": "2 Locations"},
                {"title": "Senior Engineer", "externalPath": "/job/SF/Senior_2", "locationsText": "SF"},
            ]}
        return {"jobPostingInfo": {"location": "San Francisco, CA", "jobDescription": "<p>Python</p>", "startDate": "2026-09-01"}}

    jobs = fetch_workday({"company": "s", "workday_url": "https://t.wd1.myworkdayjobs.com/en-US/Site"},
                         http=http, title_filter=lambda t: "intern" in t.lower())
    assert calls[0][0] == "POST" and calls[0][2]["searchText"] == ""
    assert sum(1 for c in calls if "/job/" in c[1]) == 1  # details only for the intern posting
    assert jobs[0]["location"] == "San Francisco, CA" and jobs[0]["content_plain"] == "Python"
    assert _workday_parts("https://t.wd1.myworkdayjobs.com/en-US/Site")[1:3] == ("t", "Site")


def test_card_prompt_survives_braces(ws):
    c = {"id": "x1", "title": "T", "company": "C", "score": 0.7, "jd_excerpt": "use {curly} braces", "hard": {}}
    p = build_prompt("rules", template_text("card_template.md"), "profile", c)
    assert "use {curly} braces" in p and "{title}" not in p


def test_generate_cards_incremental(ws):
    fetch_all(ws, http=fake_http)
    run_scoring(ws)
    calls = []

    def gen(url, model, prompt, timeout):
        calls.append(model)
        return "# card"

    first = generate_cards(ws, limit=2, generate=gen, progress=lambda *_: None)
    second = generate_cards(ws, limit=2, generate=gen, progress=lambda *_: None)
    assert first["generated"] == 2 and second == {"generated": 0, "skipped": 2, "failed": 0}
    third = generate_cards(ws, model="other", limit=2, generate=gen, progress=lambda *_: None)
    assert third["generated"] == 2  # model change invalidates cache


def test_config_validation(tmp_path):
    (tmp_path / "autojob.yaml").write_text("scoring:\n  weights: {hard: 0.9, semantic: 0.9}\n")
    with pytest.raises(ConfigError, match="sum to 1.0"):
        load(tmp_path)


def test_cli_end_to_end(ws, monkeypatch, capsys):
    monkeypatch.setattr("autojob.sources.http_json", fake_http)
    monkeypatch.setattr("autojob.fetch.http_json", fake_http)
    assert cli.main(["run", "-c", str(ws.root)]) == 0
    assert cli.main(["list", "-c", str(ws.root), "-u"]) == 0
    out = capsys.readouterr().out
    assert "Software Engineer Intern" in out and "https://gh.example/1" in out
    assert cli.main(["mark", "applied", "https://gh.example/1", "-c", str(ws.root)]) == 0
    assert cli.main(["mark", "applied", "nope", "-c", str(ws.root)]) == 1
    assert cli.main(["run", "-c", str(ws.root)]) == 0
    capsys.readouterr()
    cli.main(["list", "-c", str(ws.root), "-u"])
    assert "https://gh.example/1" not in capsys.readouterr().out
