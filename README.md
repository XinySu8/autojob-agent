# AutoJob-Agent

AutoJob-Agent is a modular, config-driven job-search automation pipeline:

- **V1 Producer**: fetches job postings from multiple ATS sources and maintains a single source of truth.
- **V2 Feeder/Scoring**: applies hard gates + semantic matching to triage jobs and outputs Apply/Maybe/Skip lists.
- **V3 Local Agent (Ollama)**: generates human-readable Markdown job cards locally (not run in GitHub Actions).

This repo is designed so that **V1 + V2 can run reliably in GitHub Actions**, while **V3 is intentionally local-only**.

---

## Repository structure

```text
scripts/                 # V1 Producer scripts (fetch + status updates)
config/targets.json       # V1 targets and filters
data/                     # V1 outputs: jobs.json, state.json, today/backlog, archive/

v2/                       # V2 scoring + triage
  config/                 # scoring.yaml, profile.md (input for V3 too)
  scripts/                # score_jobs_v2.py, triage_v2.py
  data/                   # scored_jobs.json, emb_cache.json (optional)
  output/                 # candidates.json, apply.md, maybe.md, skip.md

v3/                       # V3 local-only job cards (Ollama)
  agent/                  # run_ollama_agent.py + prompt/template
  cards-samples/          # curated sample cards committed for demo
  cards/                  # generated cards (typically local output; often gitignored)
```


---

## V1 Producer (fetch)

### Inputs
- `config/targets.json` (companies + ATS settings + filters)

### Outputs (single source of truth)
- `data/jobs.json`
- `data/state.json`
- additional reports:
  - `data/jobs.md`
  - `data/jobs_today.json / .md`
  - `data/jobs_backlog.json / .md`
  - `data/archive/`

### Run locally
```bash
python scripts/fetch_jobs.py
```

## Status behavior (important)

`data/state.json` stores `job_uid -> status`.

Jobs with `status` in `applied / ignored / closed` are hidden globally at the V1 output layer, so they will not reappear in V2 and won’t be repeatedly pushed.

---

## V2 Feeder/Scoring (triage)

### Inputs
- `data/jobs.json`

### Outputs
- `v2/data/scored_jobs.json`
- `v2/output/candidates.json` (Top-N candidates for downstream use)
- `v2/output/apply.md`
- `v2/output/maybe.md`
- `v2/output/skip.md` (skip must include reasons)

### Run locally
```bash
python v2/scripts/score_jobs_v2.py --config v2/config/scoring.yaml
python v2/scripts/triage_v2.py     --config v2/config/scoring.yaml
```

### Scoring approach (high level)
- **Hard gate** rules (must-pass constraints)
- **Semantic match** using sentence-transformers `all-MiniLM-L6-v2` cosine similarity
- Optional embedding cache for repeat runs

---

## V3 Local Agent (Ollama job cards)

**V3 requires local Ollama installed.**  
**V3 runs locally only; not in GitHub Actions.**

V3 reads the top candidates and generates a Markdown “Job Card” for each candidate, including match points, risks, skill gaps, resume-tailoring suggestions, and interview prep notes. The output is constrained to evidence from:
- `v2/output/candidates.json`
- `v2/config/profile.md`

### Install Ollama (system-level, one time)
Install Ollama on your machine, then pull a small model that fits your available RAM. Example:
```bash
ollama pull qwen2.5:3b
```
### Generate cards locally
```bash
python v3/agent/run_ollama_agent.py --model qwen2.5:3b
```
Limit generation (recommended for speed):
```bash
python v3/agent/run_ollama_agent.py --model qwen2.5:3b --limit 20
```

### Inputs
- `v2/output/candidates.json`
- `v2/config/profile.md`

### Outputs
- `v3/cards/<job_uid>.md` (generated cards)
- `v3/cards-samples/` contains a few curated sample cards committed for demonstration.

---

## GitHub Actions

GitHub Actions is configured to run **V1 + V2** on the default branch and push updated outputs back to the repo.

V3 is excluded by design because it depends on local Ollama and is intended for local use only.

## Local development setup

Recommended:
- Python 3.11 + virtual environment (`.venv`)

Typical workflow:
1) Run V1 fetch (or let Actions run it)
2) Run V2 scoring + triage
3) Optionally run V3 locally to generate cards for top candidates

## Notes on tracked vs local-only outputs

- `v3/agent/.cache/` stores local incremental indexes/logs and should not be committed.
- `v3/cards/` is usually treated as local output (can be committed once for demo, but not recommended for frequent updates).
- `v3/cards-samples/` is intended for curated examples.