from autojob.pipeline import PostingFilter
from autojob.sources import Posting, WorkdaySource, build_sources

from .conftest import fake_http


def test_build_sources_validates_and_dedupes():
    sources, warnings = build_sources([
        {"company": "a", "source": "Greenhouse", "board_token": "a"},
        {"company": "a2", "source": "greenhouse", "board_token": "A"},  # duplicate board
        {"company": "c", "source": "lever"},                            # missing key
        {"company": "d", "source": "lever", "lever_slug": "d", "enabled": False},
        {"company": "e", "source": "lever", "lever_slug": "e", "region": "eu"},
        {"company": "f", "source": "taleo", "x": 1},
    ])
    assert [repr(s) for s in sources] == ["a (greenhouse)", "e (lever)"]
    assert sources[1].options == {"region": "eu"}
    assert any("needs 'lever_slug'" in w for w in warnings) and any("unsupported source 'taleo'" in w for w in warnings)


def test_sources_normalise_postings():
    (gh, lever, ashby), _ = build_sources([
        {"company": "acme", "source": "greenhouse", "board_token": "acme"},
        {"company": "lev", "source": "lever", "lever_slug": "lev"},
        {"company": "ash", "source": "ashby", "job_board_name": "ash"},
    ], http=fake_http)
    g = gh.fetch()[0]
    assert g.content.startswith("Build data pipelines") and g.posted_at == "2026-09-01T14:00:00+00:00"
    lv = lever.fetch()[0]
    assert lv.posted_at.startswith("2026-01-01") and "Git" in lv.content and lv.departments == ["Research"]
    ash = ashby.fetch()
    assert [p.title for p in ash] == ["Product Engineer"]  # unlisted posting skipped


def test_workday_posts_and_fetches_details_only_for_relevant_titles():
    calls = []

    def http(url, method="GET", data=None, **_):
        calls.append((method, url, data))
        if url.endswith("/jobs"):
            return {"total": 2, "jobPostings": [
                {"title": "Software Engineering Intern", "externalPath": "/job/SF/Intern_1", "locationsText": "2 Locations"},
                {"title": "Senior Engineer", "externalPath": "/job/SF/Senior_2", "locationsText": "SF"},
            ]}
        return {"jobPostingInfo": {"location": "San Francisco, CA", "jobDescription": "<p>Python</p>"}}

    src = WorkdaySource("s", "https://t.wd1.myworkdayjobs.com/en-US/Site", http=http)
    jobs = src.fetch(title_filter=lambda t: "intern" in t.lower())
    assert calls[0][0] == "POST" and calls[0][1] == "https://t.wd1.myworkdayjobs.com/wday/cxs/t/Site/jobs"
    assert sum(1 for c in calls if "/job/" in c[1]) == 1
    assert jobs[0].location == "San Francisco, CA" and jobs[0].content == "Python"


def P(title, content="", **kw):
    return Posting(id=title, source="x", company=kw.pop("company", "c"), title=title, url="u", content=content, **kw)


def test_filter_checks_exclusions_on_title_only():
    f = PostingFilter({"internship_any": ["intern"], "exclude_title_any": ["director"], "domain_any": ["software"]})
    kept, dropped = f.apply([
        P("Software Intern", "You report to the Director"),
        P("Director Intern Programs", "software"),
        P("Marketing Intern", "brand"),
        P("Software Engineer"),
        P("Product Engineer", "software", employment_type="Intern"),
    ])
    assert [p.title for p in kept] == ["Software Intern"]
    assert dropped == {"excluded_title": 1, "domain_mismatch": 1, "not_internship": 2}
    f.ashby_types = {"intern"}  # structured employment type counts as internship
    assert f.reject_reason(P("Product Engineer", "software", employment_type="Intern")) is None


def test_filter_company_cap():
    f = PostingFilter({"max_jobs_per_company": 1})
    kept, dropped = f.apply([P("A Intern"), P("B Intern"), P("C Intern", company="other")])
    assert len(kept) == 2 and dropped == {"company_cap": 1}
