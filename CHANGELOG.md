# Changelog

## 2.0.0 — 2026-10-10

v2 turns the CLI into a full-stack application: a database, a REST API, a web UI and an AI agent with evaluation.

### Added
- **Database**: PostgreSQL or SQLite through SQLAlchemy 2.0, with Alembic migrations that run on startup.
  The tables are `jobs`, `runs`, `scores` (one row per job per run, which gives score history), `decisions` and `agent_reviews`.
- **REST API** (FastAPI): `/api/jobs` (filter, search, paginate), `/api/jobs/{id}` (detail and history),
  `PATCH /api/jobs/{id}/decision`, `POST /api/jobs/{id}/review`, `/api/runs`, `/api/eval`. Interactive docs are at `/docs`.
- **Web UI** (React + TypeScript + Vite): job list, detail panel, status and label buttons, AI review, evaluation page and run history.
  The API types are generated from the OpenAPI schema, and CI fails if they drift.
- **AI agent** (LangChain + Ollama): verdicts with structured output and a check that every evidence quote appears in the JD.
  It retries with the errors as feedback, then falls back to the rule-based bucket. Reviews are incremental, keyed by job text, profile and model.
- **Evaluation**: `autojob label` and `autojob eval` compute precision@k and bucket accuracy for the keyword, semantic and agent rankers.
- **Deployment**: a multi-stage Dockerfile and `docker-compose.yml` (app, PostgreSQL, and an optional Ollama profile).
- **CI**: the test suite runs on SQLite and PostgreSQL, CI checks that migrations match the models, builds the frontend and builds the Docker image.

### Changed
- Source adapters are now classes (`Source` with one subclass per ATS), and scoring is a `Scorer` class.
  The pipeline, the repository and the agent are separate units that can be tested on their own.
- Jobs that disappear from a board are marked closed, but only when that board was fetched successfully.
- `autojob fetch` and `autojob score` are merged into `autojob run`, which is recorded as a run.
  The static HTML dashboard, the stdlib server and the Markdown job cards are replaced by the web UI and the agent.
- The daily GitHub Actions workflow keeps the database in the Actions cache, so no data is committed to the repo.
  The "mark job" workflow is removed; mark jobs in the UI or with the CLI instead.

### Upgrading from 1.x
v1 kept marks in `data/state.json`; v2 uses a database. Job ids are unchanged. v1 had no applied or ignored marks
in this repo's workspace, so no import step is provided.

## 1.0.0 — 2026-09-29

This release turns the v0 V1/V2/V3 scripts into an installable package with a single `autojob` CLI.

### Product
- `pip install`-able package with the `autojob` command: `init`, `run`, `fetch`, `score`, `list`, `mark`, `serve`, `cards`, `doctor`.
- One `autojob.yaml` replaces `config/targets.json`, `config/profile.json` (which was unused) and `v2/config/scoring.yaml`.
  All paths resolve relative to the config file, so commands work from any directory.
- New HTML dashboard. It works as a static report, or through `autojob serve` with *Applied / Ignore / Fetch & rescore* buttons.
- Markdown digest. The GitHub Actions workflow writes it to the run summary.
- The heavy ML stack is optional. The built-in TF-IDF backend handles semantic matching by default. sentence-transformers comes via `[semantic]`.
  The old pins (`torch==2.2.2`, `numpy==1.26.4`) would not install on Python ≥ 3.13.
- Job cards call Ollama's HTTP API instead of piping into `ollama run`.
- Tests (pytest), a CI matrix for Python 3.10–3.13, a Dockerfile, and a LICENSE file.
- Generated data is no longer committed. The repo previously carried about 10 MB of daily snapshots and embedding caches.

### Fixes
- **The Apply list was always empty.** Scores were min-max normalised, but the apply threshold (0.72) was higher than any real job reached.
  The keyword part now uses an absolute scale (`hard_saturation`), and the default thresholds are tuned.
- **Keyword false positives.** Matching was plain substring, so `rag` matched "sto*rag*e" and "leve*rag*e", and `git` matched "di*git*al".
  The degree gate `ms required` matched "syste*ms required*" and dropped valid jobs, and `ts/sci` matched "experimen*ts/sci*ence".
  All keyword and phrase matching is now whole-word.
- **Good internships were dropped at fetch time.** `exclude_any: [director, principal, vp]` was matched against the full JD,
  so any posting saying "you'll report to the Director" disappeared. Exclusions now check the title only.
- **The location allowlist rejected US jobs.** "Foster City, CA" and "Dallas, Texas" failed because only a few city names and "California" were listed.
  Region presets now cover all US states and state codes.
  Vague locations ("In-Office", "5 Locations") now fall back to the JD text, as `match_order: location_then_text` always claimed.
  Before, this setting was ignored.
- **Workday never worked.** A GET to the CXS endpoint returns 400, and the POST fallback lacked the required fields.
  It now POSTs correctly, and it fetches the description and real location for internship postings.
- **Greenhouse**: switched to `boards-api.greenhouse.io`. `coinbase` used to 404 on the legacy host.
- **Mixed timestamp types.** Lever returned epoch-ms integers while other sources returned ISO strings, which broke "newest first" sorting.
  All timestamps are now normalised to ISO-8601 UTC.
- **One bad target could crash the whole run.** Only a few exception types were caught before.
  Every target is now isolated, and transient 429/5xx errors are retried with backoff.
  Targets are fetched in parallel, so a run takes about 15 s instead of several minutes.
- **Shell injection in the "mark job" workflow.** `${{ inputs.url }}` was interpolated directly into `run:`. Inputs are now passed through env vars.
- **Stale embedding cache.** It was not keyed by model, so switching models reused old vectors. It also grew forever. It is now keyed by model and pruned.
- The job title and department are now part of the scored text. Before, only the description was used, and Workday jobs were scored on empty text.
- The Markdown feed contained mojibake (`鈥?` instead of `—`) and a UTF-8 BOM in `fetch_jobs.py`.
- Job-card prompts crashed with `KeyError` when a JD contained `{` or `}`, because `str.format` was used on untrusted text.
- `state.json` is written atomically. A corrupt file is backed up instead of being silently reset, which used to lose all marks.
- Removed dead or broken targets (`redis` 404, `vellum` 404). Added recruiting and sales role title exclusions.

### Compatibility
Job ids use the same hashing as v0, so an old `data/state.json` can be copied to `<workspace>/data/state.json`
and existing applied/ignored marks keep working.
