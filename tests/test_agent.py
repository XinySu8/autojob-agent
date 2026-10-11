from langchain_core.runnables import RunnableLambda

from autojob.agent import AgentUnavailable, AgentVerdict, JobAgent
from autojob.models import Job, Score

JD = "Build data pipelines in Python and SQL. Experience with Docker and cloud. Must be enrolled in a BS program."
GOOD = {"verdict": "apply", "confidence": 0.8, "summary": "Strong fit.",
        "matches": [{"point": "Python pipelines", "quote": "Build data pipelines in Python and SQL."}],
        "gaps": [{"point": "Docker", "quote": "experience with   docker"}]}  # case/whitespace-insensitive
HALLUCINATED = {**GOOD, "matches": [{"point": "x", "quote": "5 years of Kubernetes"}]}


def scripted(*outputs):
    """Fake LLM returning the given outputs in order; records the prompts it saw."""
    seen = []

    def call(msgs):
        seen.append(msgs)
        out = outputs[len(seen) - 1]
        if isinstance(out, Exception):
            raise out
        return out

    return RunnableLambda(call), seen


def job():
    return Job(id="j1", company="acme", title="Data Intern", location="SF", content=JD)


def score():
    return Score(bucket="maybe", score=0.5, hits={"must": ["python"]})


def test_valid_answer_accepted_first_try():
    llm, seen = scripted(GOOD)
    review = JobAgent(llm, "m").review("profile", job(), score())
    assert (review.verdict, review.attempts, review.fallback) == ("apply", 1, False)
    assert "RULE-BASED SIGNALS" in seen[0][1].content and "bucket=maybe" in seen[0][1].content


def test_hallucinated_quote_triggers_retry_with_feedback():
    llm, seen = scripted(HALLUCINATED, AgentVerdict.model_validate(GOOD))
    review = JobAgent(llm, "m").review("profile", job(), score())
    assert review.attempts == 2 and not review.fallback
    assert 'quote not found in job description: "5 years of Kubernetes"' in seen[1][-1].content


def test_schema_violation_retries_then_falls_back_to_rules():
    llm, _ = scripted({"verdict": "definitely"}, HALLUCINATED, {"confidence": 3})
    review = JobAgent(llm, "m", max_retries=2).review("profile", job(), score())
    assert review.fallback and review.verdict == "maybe" and review.attempts == 3


def test_unreachable_model_raises():
    llm, _ = scripted(ConnectionError("refused"))
    try:
        JobAgent(llm, "m").review("profile", job(), None)
        raise AssertionError("should raise")
    except AgentUnavailable:
        pass


def test_pipeline_review_is_incremental(pipeline):
    pipeline.run()
    calls = []

    def answer(msgs):
        calls.append(1)
        return {"verdict": "skip", "confidence": 0.9, "summary": "no", "matches": [], "gaps": []}

    agent = JobAgent(RunnableLambda(answer), "m")
    first = pipeline.review(agent, limit=10)
    assert first["reviewed"] >= 1
    assert pipeline.review(agent, limit=10) == {"unchanged": first["reviewed"]}
    assert pipeline.review(JobAgent(RunnableLambda(answer), "other-model"), limit=10)["reviewed"] == first["reviewed"]


def test_from_config_maps_ollama_down_to_unavailable(ws):
    agent = JobAgent.from_config({"agent": {"model": "m", "ollama_url": "http://127.0.0.1:9", "max_retries": 0}})
    try:
        agent.review("profile", job(), None)
        raise AssertionError("should raise")
    except AgentUnavailable as e:
        assert "cannot use model 'm'" in str(e)
