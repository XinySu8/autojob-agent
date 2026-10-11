import pytest
from fastapi.testclient import TestClient
from langchain_core.runnables import RunnableLambda

from autojob.agent import JobAgent
from autojob.api import create_app


@pytest.fixture
def client(ws, db, pipeline):
    agent = JobAgent(RunnableLambda(lambda m: {"verdict": "apply", "confidence": 0.7, "summary": "ok", "matches": [], "gaps": []}), "fake")
    with TestClient(create_app(ws, db=db, pipeline=pipeline, agent_factory=lambda: agent)) as c:
        yield c


def test_empty_before_first_run(client):
    assert client.get("/api/jobs").json() == {"run": None, "total": 0, "items": []}


def test_run_list_detail_decide_review_eval(client):
    assert client.post("/api/runs").status_code == 202  # BackgroundTasks run synchronously in TestClient
    runs = client.get("/api/runs").json()
    assert runs[0]["status"] == "succeeded"

    page = client.get("/api/jobs", params={"bucket": "apply"}).json()
    assert page["total"] >= 1 and all(j["score"]["bucket"] == "apply" for j in page["items"])
    assert all(j["is_new"] for j in page["items"])
    jid = page["items"][0]["id"]

    assert client.get("/api/jobs", params={"q": "MACHINE"}).json()["items"][0]["title"] == "Machine Learning Intern"

    r = client.patch(f"/api/jobs/{jid}/decision", json={"status": "applied", "label": "apply", "note": "hi"})
    assert r.status_code == 200 and r.json()["label"] == "apply"
    assert client.patch(f"/api/jobs/{jid}/decision", json={"label": None}).json()["label"] is None
    assert client.patch(f"/api/jobs/{jid}/decision", json={"status": "bogus"}).status_code == 422
    assert client.get("/api/jobs", params={"status": "applied"}).json()["total"] == 1

    review = client.post(f"/api/jobs/{jid}/review").json()
    assert review["verdict"] == "apply" and review["model"] == "fake"

    detail = client.get(f"/api/jobs/{jid}").json()
    assert detail["content"] and len(detail["history"]) == 1 and detail["review"]["verdict"] == "apply"
    assert detail["status"] == "applied" and detail["note"] == "hi"

    client.patch(f"/api/jobs/{jid}/decision", json={"label": "apply"})
    ev = client.get("/api/eval").json()
    assert ev["labeled"] == 1 and [s["name"] for s in ev["systems"]] == ["keywords", "rules+semantic", "rules+agent"]


def test_unknown_job_is_404(client):
    client.post("/api/runs")
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.patch("/api/jobs/nope/decision", json={"status": "applied"}).status_code == 404
