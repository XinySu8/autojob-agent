import pytest

from autojob.config import init_workspace, load

GREENHOUSE = {
    "jobs": [
        {
            "id": 1, "title": "Software Engineer Intern", "absolute_url": "https://gh.example/1",
            "location": {"name": "San Francisco, CA"}, "updated_at": "2026-09-01T10:00:00-04:00",
            "departments": [{"name": "Engineering"}],
            "content": "&lt;p&gt;Build data pipelines in Python and SQL. Experience with Docker and cloud.&lt;/p&gt;",
        },
        {
            "id": 2, "title": "Senior Director of Sales", "absolute_url": "https://gh.example/2",
            "location": {"name": "New York, NY"}, "updated_at": "2026-09-02T00:00:00Z", "content": "sales",
        },
        {
            "id": 3, "title": "Machine Learning Intern", "absolute_url": "https://gh.example/3",
            "location": {"name": "London, UK"}, "updated_at": "2026-09-03T00:00:00Z",
            "content": "Machine learning with Python.",
        },
        {
            "id": 4, "title": "Data Engineering Intern", "absolute_url": "https://gh.example/4",
            "location": {"name": "In-Office"}, "updated_at": "2026-09-04T00:00:00Z",
            "content": "Work in our Seattle, WA office. Python, SQL. Active security clearance required.",
        },
        {
            "id": 5, "title": "Software Intern", "absolute_url": "https://gh.example/5",
            "location": {"name": "Austin, TX"}, "updated_at": "2026-09-05T00:00:00Z",
            "content": "You will report to the Director of Engineering. Python, React, storage systems required.",
        },
    ]
}
LEVER = [
    {
        "id": "abc", "text": "AI Research Intern", "hostedUrl": "https://lever.example/abc", "createdAt": 1767225600000,
        "categories": {"location": "Seattle, WA", "team": "Research"},
        "descriptionPlain": "LLM research using Python.", "lists": [{"text": "Requirements", "content": "<li>Git</li>"}],
    }
]
ASHBY = {
    "jobs": [
        {
            "title": "Product Engineer", "jobUrl": "https://ashby.example/1", "applyUrl": "https://ashby.example/1/apply",
            "location": "Remote", "employmentType": "Intern", "publishedAt": "2026-09-06T00:00:00Z",
            "descriptionPlain": "Build APIs in Python for users in the United States.",
        },
        {"title": "Hidden Intern", "jobUrl": "https://ashby.example/2", "isListed": False, "descriptionPlain": ""},
    ]
}


def fake_http(url, method="GET", data=None, **_):
    if "greenhouse" in url:
        return GREENHOUSE
    if "lever" in url:
        return LEVER
    if "ashby" in url:
        return ASHBY
    raise AssertionError(f"unexpected url {url}")


@pytest.fixture
def ws(tmp_path):
    init_workspace(tmp_path)
    cfg = (tmp_path / "autojob.yaml").read_text()
    start = cfg.index("  targets:\n")
    end = cfg.index("\n\n", start)
    cfg = cfg[:start] + (
        "  targets:\n"
        "    - { company: acme, source: greenhouse, board_token: acme }\n"
        "    - { company: lev, source: lever, lever_slug: lev }\n"
        "    - { company: ash, source: ashby, job_board_name: ash }\n"
        "    - { company: bad, source: smartrecruiters, token: x }\n"
    ) + cfg[end:]
    cfg = cfg.replace("backend: auto ", "backend: tfidf ")
    (tmp_path / "autojob.yaml").write_text(cfg)
    (tmp_path / "profile.md").write_text("Student skilled in Python, SQL, data pipelines, LLM tooling and APIs.")
    return load(tmp_path)
