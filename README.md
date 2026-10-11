# AutoJob-Agent

[![CI](https://github.com/XinySu8/autojob-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/XinySu8/autojob-agent/actions/workflows/ci.yml)

AutoJob-Agent pulls internship and new-grad postings straight from the public job-board APIs of 40+ companies
(Greenhouse, Lever, Ashby and Workday). It ranks them against your profile and lets a local LLM agent review the
top matches. It also measures how good its own ranking is against your labels.

- **Pipeline:** about 8,000 postings fetched in about 7 seconds. Results are stored in PostgreSQL (or SQLite), with score history for every run.
- **Explainable ranking:** hard gates (location, clearance, degree), keyword hits and semantic similarity are combined into **Apply / Maybe / Skip**.
- **AI agent:** a LangChain + Ollama reviewer returns a schema-validated verdict. Every piece of evidence must quote the job description word for word. If the output fails that check, the agent is re-prompted, and it finally falls back to the rule-based bucket.
- **Evaluation:** you label jobs, and `autojob eval` reports precision@k for the keyword ranker, keywords plus semantic similarity, and the agent.
- **Web app:** React + TypeScript UI on a FastAPI REST API. The frontend types are generated from the OpenAPI schema.
- **Engineering:** Alembic migrations, 49 tests running on both SQLite and PostgreSQL, a CI pipeline, Docker Compose, and a daily GitHub Actions run.

## Architecture

```
            ┌──────────────── autojob run (CLI · cron · "Run now") ────────────────┐
 ATS APIs ─►│ Source adapters ─► PostingFilter ─► Repository ─► Scorer ─► scores   │
 (4 kinds)  │  Greenhouse/Lever/   internship?      upsert jobs,   gates +         │
            │  Ashby/Workday       title/domain     close stale    keywords +      │
            └──────────────────────────────────────────────────────semantic───────┘
                                        │
                                PostgreSQL / SQLite ◄── Alembic migrations
                     jobs · runs · scores (history) · decisions · agent_reviews
                                        │
   React + TS UI ◄──── FastAPI REST API ┼──── JobAgent (LangChain + Ollama)
   (generated types)   /api/jobs, /runs, │      structured output → schema check →
                       /eval, /decision  │      evidence-quote check → retry / fallback
                                         └──── Evaluation: precision@k vs your labels
```

| Layer | Code |
|---|---|
| Source adapters (one abstract `Source`, one subclass per ATS) | [`autojob/sources.py`](autojob/sources.py) |
| Pipeline: fetch, filter, store, score | [`autojob/pipeline.py`](autojob/pipeline.py), [`autojob/scoring.py`](autojob/scoring.py) |
| Data model and data access | [`autojob/models.py`](autojob/models.py), [`autojob/repository.py`](autojob/repository.py), [`autojob/migrations/`](autojob/migrations) |
| AI agent and guardrails | [`autojob/agent.py`](autojob/agent.py) |
| Evaluation | [`autojob/evaluation.py`](autojob/evaluation.py) |
| REST API and schemas | [`autojob/api.py`](autojob/api.py), [`autojob/schemas.py`](autojob/schemas.py) |
| Web UI | [`web/src/`](web/src) |

## Quick start (Docker)

```bash
git clone https://github.com/XinySu8/autojob-agent && cd autojob-agent
# edit workspace/profile.md (about you) and workspace/autojob.yaml (companies, keywords, locations)
docker compose up --build              # http://localhost:8000 → click "Run now"
```

AI reviews need Ollama. Start it with `docker compose --profile ai up`, then pull a model with
`docker compose exec ollama ollama pull qwen2.5:7b`. Finally, set `agent.ollama_url: http://ollama:11434`
in `workspace/autojob.yaml`.

## Quick start (local)

```bash
pip install "autojob-agent[agent] @ git+https://github.com/XinySu8/autojob-agent"
autojob init my-jobs && cd my-jobs     # creates autojob.yaml + profile.md; edit both
autojob run                            # fetch + score (SQLite at data/autojob.db)
autojob serve                          # http://127.0.0.1:8000 (API docs at /docs)
```

`pip install` from git ships the API only. To include the web UI, build it once from a clone:
`cd web && npm ci && npm run build`. For PostgreSQL, set `DATABASE_URL=postgresql+psycopg://user:pass@host/db`.

## CLI

| Command | What it does |
|---|---|
| `autojob run` | Fetch all boards and score open jobs; recorded as a run |
| `autojob list [apply\|maybe\|skip] [-u]` | Ranked jobs from the latest run |
| `autojob mark applied\|ignored\|closed\|new <id\|url…>` | Your status; marked jobs are not re-scored |
| `autojob label apply\|maybe\|skip <id\|url…>` | Ground-truth label used by `eval` |
| `autojob review [--limit N] [--job ID]` | AI agent review; skipped when job, profile and model are unchanged |
| `autojob eval` | precision@5/10/20 and bucket accuracy per ranker |
| `autojob serve` | Web UI and REST API |
| `autojob digest [-o file.md]` | Markdown summary (used in the GitHub Actions run summary) |
| `autojob doctor` | Check config, database and optional extras |

## How it works

**Ranking.** A job first has to pass the hard gates: the location allowlist (with US-state and city presets)
and the clearance, citizenship and degree phrases. It then gets a keyword score: whole-word hits on the title,
must-have, nice-to-have and negative terms, capped at `hard_saturation`. Next comes semantic similarity between
`profile.md` and the job text, computed with TF-IDF by default or sentence-transformers via the `[semantic]` extra.
The weighted sum is compared with the thresholds to pick Apply, Maybe or Skip.

**Agent guardrails.** The agent turns a ranked job into an `AgentVerdict` (verdict, confidence, summary, and
matches and gaps with evidence) in four steps:
1. The model's JSON mode is constrained to the Pydantic schema.
2. Every evidence `quote` must be found in the job description (ignoring case and whitespace). This catches invented requirements.
3. If a check fails, the model is re-prompted with the exact errors, up to `max_retries` times.
4. If it still fails, the rule-based bucket is kept and the review is flagged `fallback`. The UI and the evaluation both know about this.

**Evaluation.** Label jobs in the UI ("Correct bucket") or with `autojob label`. `autojob eval` then compares three
rankers on the same labeled set: `keywords`, `rules+semantic` and `rules+agent`. It reports precision@k
(relevant = labeled *apply*) and bucket accuracy. Values with too few labels for k are shown as "–".

**Data model.** `jobs` holds each posting once. `runs` holds one row per pipeline run. `scores` holds one row per
job per run, which gives score history and "new since last run". `decisions` holds your status, label and note,
and `agent_reviews` holds the latest verdict. Jobs that disappear from a board are closed, but only when that
board was fetched successfully, so a timeout never closes a company's jobs.

## Configuration

Everything is in `autojob.yaml`, which is commented.

```yaml
fetch:
  targets:
    - { company: stripe, source: greenhouse, board_token: stripe }
    - { company: openai, source: ashby,      job_board_name: openai }
    - { company: slack,  source: workday,    workday_url: "https://salesforce.wd12.myworkdayjobs.com/Slack" }
scoring:
  location_allowlist: { enabled: true, regions: [US, China, Singapore] }
  keywords:
    title:     { software engineer: 3, machine learning: 3 }
    must_have: { python: 3, sql: 2, llm: 2 }
triage:
  thresholds: { apply: 0.60, maybe: 0.35 }
agent:
  model: qwen2.5:7b
```

## GitHub Actions

`.github/workflows/autojob-daily.yml` runs `autojob run` using [`workspace/`](workspace/). It keeps the SQLite
database between runs with the Actions cache and writes the digest to the run summary. It starts manually by
default; uncomment `schedule:` to run it every day.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev,agent]'
pytest -q && ruff check .
TEST_DATABASE_URL=postgresql+psycopg://localhost/autojob_test pytest -q   # same suite on PostgreSQL

cd web && npm ci
autojob serve -c ../workspace & npm run dev        # Vite on :5173, proxies /api to :8000
npm run gen:api                                    # after changing autojob/schemas.py

# after changing autojob/models.py:
DATABASE_URL=sqlite:///dev.db alembic revision --autogenerate -m "describe change"
```

CI runs the backend tests on Python 3.10 and 3.13 against both SQLite and PostgreSQL. It also checks that the
migrations match the models and that the generated API types are up to date. Finally, it builds the frontend
and the Docker image.

## License

MIT
