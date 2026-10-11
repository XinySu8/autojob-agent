from autojob import cli
from autojob.evaluation import evaluate, precision_at_k
from autojob.models import Job, Run
from autojob.report import render_digest
from autojob.repository import NotFound, Repository

from .conftest import fake_http


def test_run_stores_jobs_scores_and_warnings(pipeline, db):
    run = pipeline.run()
    assert run.status == "succeeded" and run.matched == 6 and run.new_jobs == 6
    assert any("smartrecruiters" in w for w in run.warnings)
    assert sum(run.counts.values()) == 6 and run.semantic_backend == "tfidf"
    with db.session() as s:
        rows, total = Repository(s).ranked(run)
        assert total == 6
        titles = {j.title: sc for sc, j in rows}
        assert titles["Machine Learning Intern"].gate == "location not in allowlist"  # London
        assert titles["Data Engineering Intern"].gate.startswith("excluded")          # clearance
        assert titles["Software Engineer Intern"].bucket == "apply"
        assert titles["Software Intern"].gate is None  # "storage systems required" must not trip degree rules


def test_second_run_keeps_history_and_hides_marked_jobs(pipeline, db):
    pipeline.run()
    with db.session() as s:
        repo = Repository(s)
        jid = repo.find_job("https://gh.example/1").id
        assert repo.find_job(jid[:8]).id == jid
        repo.set_decision(jid, status="applied", note="referral")
    run2 = pipeline.run()
    assert run2.new_jobs == 0
    with db.session() as s:
        repo = Repository(s)
        ids = {j.id for _sc, j in repo.ranked(run2)[0]}
        assert jid not in ids                       # applied jobs are not re-scored
        other = next(iter(ids))
        assert len(repo.get_job(other).scores) == 2  # one score per run = history


def test_failed_board_does_not_close_its_jobs(ws, db):
    from autojob.pipeline import Pipeline

    Pipeline(ws, db, http=fake_http).run()

    def lever_down(url, **kw):
        if "lever" in url:
            raise RuntimeError("boom")
        return fake_http(url, **kw)

    run = Pipeline(ws, db, http=lever_down).run()
    assert any("lev (lever): unexpected RuntimeError" in w for w in run.warnings)
    with db.session() as s:
        assert all(j.is_open for j in s.query(Job).filter_by(company="lev"))

    def acme_job_gone(url, **kw):
        data = fake_http(url, **kw)
        return {"jobs": data["jobs"][1:]} if "greenhouse" in url else data

    Pipeline(ws, db, http=acme_job_gone).run()
    with db.session() as s:
        closed = [j.url for j in s.query(Job).filter_by(is_open=False)]
    assert closed == ["https://gh.example/1"]


def test_failed_run_is_recorded(ws, db, monkeypatch):
    from autojob.pipeline import Pipeline

    p = Pipeline(ws, db, http=fake_http)
    monkeypatch.setattr(p, "score", lambda *a: (_ for _ in ()).throw(RuntimeError("scoring broke")))
    try:
        p.run()
    except RuntimeError:
        pass
    with db.session() as s:
        run = s.query(Run).one()
    assert run.status == "failed" and "scoring broke" in run.error


def test_decision_validation(pipeline, db):
    pipeline.run()
    with db.session() as s:
        repo = Repository(s)
        jid = repo.find_job("https://gh.example/1").id
        for bad in ({"status": "maybe"}, {"label": "applied"}):
            try:
                repo.set_decision(jid, **bad)
                raise AssertionError("should fail")
            except ValueError:
                pass
        try:
            repo.find_job("nope")
            raise AssertionError("should fail")
        except NotFound:
            pass


def test_precision_at_k():
    assert precision_at_k(["apply", "skip", "apply", "maybe"], 2) == 0.5
    assert precision_at_k(["apply"], 5) is None  # too few labels -> no number rather than a misleading one


def test_evaluate_compares_systems(pipeline, db):
    run = pipeline.run()
    with db.session() as s:
        repo = Repository(s)
        for _sc, job in repo.ranked(run)[0]:
            repo.set_decision(job.id, label="apply" if "Engineer" in job.title else "skip")
        results = {r.name: r for r in evaluate(repo.labeled(run), ks=(1, 2))}
    assert set(results) == {"keywords", "rules+semantic", "rules+agent"}
    assert results["rules+semantic"].precision_at[1] == 1.0
    assert results["keywords"].bucket_accuracy is None
    assert results["rules+agent"].agent_coverage == 0.0


def test_digest(pipeline, db):
    pipeline.run()
    with db.session() as s:
        md = render_digest(Repository(s))
    assert "## Apply" in md and "Software Engineer Intern" in md and "🆕" in md


def test_cli_end_to_end(ws, monkeypatch, capsys):
    monkeypatch.setattr("autojob.sources.http_json", fake_http)
    monkeypatch.setattr("autojob.pipeline.http_json", fake_http)
    root = str(ws.root)
    assert cli.main(["run", "-c", root]) == 0
    assert cli.main(["list", "-c", root, "-u"]) == 0
    assert "https://gh.example/1" in capsys.readouterr().out
    assert cli.main(["mark", "applied", "https://gh.example/1", "-c", root]) == 0
    assert cli.main(["label", "apply", "https://gh.example/1", "-c", root]) == 0
    assert cli.main(["mark", "applied", "nope", "-c", root]) == 1
    assert cli.main(["eval", "-c", root]) == 0
    capsys.readouterr()
    assert cli.main(["run", "-c", root]) == 0
    cli.main(["list", "-c", root, "-u"])
    assert "https://gh.example/1" not in capsys.readouterr().out
    assert cli.main(["doctor", "-c", root]) == 0
    out = ws.root / "d.md"
    assert cli.main(["digest", "-c", root, "-o", str(out)]) == 0 and "AutoJob digest" in out.read_text()
