# AutoJob-Agent

[![CI](https://github.com/XinySu8/autojob-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/XinySu8/autojob-agent/actions/workflows/ci.yml)

**Stop refreshing 40 career pages.** AutoJob-Agent pulls internship and early-career postings straight from the
public job-board APIs that companies use (Greenhouse, Lever, Ashby, Workday). It ranks them against *your*
profile and gives you a short **Apply / Maybe / Skip** list, with the reason for every decision.

- **One command a day:** `autojob run` fetches about 8,000 postings from 40+ companies in about 15 seconds.
- **Explainable ranking:** keyword hits, semantic similarity, and hard gates (location, clearance, degree) are all shown on each job.
- **Dashboard:** a local web page where you mark jobs *Applied* or *Ignore*. Marked jobs never come back.
- **Light install:** the only dependency is PyYAML. Semantic matching uses built-in TF-IDF. You can optionally switch to sentence-transformers.
- **Optional job cards:** a local LLM ([Ollama](https://ollama.com)) writes evidence-only prep notes for top matches.
- **Runs anywhere:** laptop, Docker, or GitHub Actions on a schedule.

---

## Quick start

```bash
pip install git+https://github.com/XinySu8/autojob-agent
autojob init my-jobs        # creates my-jobs/autojob.yaml + my-jobs/profile.md
cd my-jobs
# 1) edit profile.md – a few paragraphs about you (skills, projects, what you want)
# 2) edit autojob.yaml – companies, keywords, locations (defaults are sensible)
autojob run --open          # fetch + score + open the dashboard
```

Daily use:

```bash
autojob run                 # refresh
autojob list                # top "apply" jobs in the terminal (list maybe / list skip)
autojob mark applied <url-or-id> --note "referral from Alex"
autojob serve --open        # dashboard with Applied / Ignore buttons + "Fetch & rescore"
```

Check your setup at any time with `autojob doctor`.

## Commands

| Command | What it does |
|---|---|
| `autojob init [dir]` | Create a workspace with a starter `autojob.yaml` and `profile.md` |
| `autojob run [--open]` | `fetch` + `score` (the daily command) |
| `autojob fetch` | Download postings, filter to internships, update `state.json` |
| `autojob score` | Gates, keyword and semantic scoring, triage, and reports (`data/reports/`) |
| `autojob list [apply\|maybe\|skip] [-n N] [-u]` | Print ranked jobs |
| `autojob mark <applied\|ignored\|closed\|new> <url\|id…>` | Record your decision; hidden jobs don't come back |
| `autojob serve [--port 8765] [--open]` | Local dashboard (binds to 127.0.0.1) |
| `autojob cards [--model qwen2.5:3b] [--limit 20]` | Generate job cards with local Ollama |
| `autojob doctor` | Validate config and show optional components |

Every command accepts `-c/--config <path>`. Without it, AutoJob looks for `autojob.yaml` in the current folder
and its parents, or uses `$AUTOJOB_CONFIG`.

## How ranking works

```
fetch ─► filter (title looks like internship/new-grad, domain match, title exclusions)
      ─► hard gates  (location allowlist, clearance/citizenship/degree phrases)   ─► skip + reason
      ─► keyword score (title + must-have + nice-to-have − negatives, whole-word)  ─┐
      ─► semantic score (profile.md vs JD: TF-IDF or sentence-transformers)        ─┴► weighted ─► apply / maybe / skip
```

- **Keyword score:** the sum of weights for whole-word hits. It is capped at `hard_saturation` and scaled to 0–1.
- **Semantic score:** the cosine similarity between your profile and each posting, min-max scaled across today's batch.
- **Final score:** `weights.hard × keyword + weights.semantic × semantic`. The thresholds in `triage.thresholds` decide the bucket.

For better semantic matching (downloads PyTorch, about 1–2 GB):

```bash
pip install "autojob-agent[semantic] @ git+https://github.com/XinySu8/autojob-agent"
```

With `backend: auto` in the config, it gets picked up automatically.

## Configuration

Everything lives in `autojob.yaml`. The generated file is commented; these are the parts you will most likely change:

```yaml
fetch:
  targets:
    - { company: stripe,  source: greenhouse, board_token: stripe }
    - { company: openai,  source: ashby,      job_board_name: openai }
    - { company: zoox,    source: lever,      lever_slug: zoox }
    - { company: slack,   source: workday,    workday_url: "https://salesforce.wd12.myworkdayjobs.com/Slack" }

scoring:
  location_allowlist:
    enabled: true
    regions: [US, China, Singapore]      # presets: US, Canada, China, Singapore, UK, Remote
  keywords:
    title:     { software engineer: 3, machine learning: 3, data engineer: 3 }
    must_have: { python: 3, sql: 2, llm: 2 }
    negative:  { "5+ years": -2 }

triage:
  thresholds: { apply: 0.60, maybe: 0.35 }
```

**Finding a company's board:** open its careers page and look at the job links.

- `boards.greenhouse.io/<token>` → Greenhouse
- `jobs.lever.co/<slug>` → Lever
- `jobs.ashbyhq.com/<name>` → Ashby
- `*.myworkdayjobs.com/<site>` → Workday

## Where the data goes

```
my-jobs/
  autojob.yaml, profile.md
  data/
    state.json          # your applied/ignored marks  ← the only file worth backing up
    jobs.json           # today's open internships
    scored.json         # every job with bucket, score and reason
    candidates.json     # top apply+maybe with JD excerpts (input for job cards)
    reports/digest.md   # Markdown summary
    reports/dashboard.html
    cards/              # Ollama job cards
    archive/            # daily fetch stats
```

## Run on GitHub Actions

The repo ships a ready-made workspace in [`workspace/`](workspace/) and two workflows:

- **AutoJob daily** (`.github/workflows/autojob-daily.yml`): runs `autojob run`, writes the digest to the run
  summary, attaches the dashboard as an artifact, and commits `workspace/data/state.json`. It starts manually by
  default; uncomment the `schedule:` block to run it every day.
- **AutoJob mark**: Actions → *AutoJob mark* → *Run workflow*. Enter a URL or id to mark it applied or ignored.

Fork the repo, edit `workspace/profile.md` and `workspace/autojob.yaml`, and run it.

## Docker

```bash
docker build -t autojob .
docker run --rm -v "$PWD/my-jobs:/workspace" autojob run
docker run --rm -p 8765:8765 -v "$PWD/my-jobs:/workspace" autojob serve --host 0.0.0.0
```

## Job cards with a local LLM (optional)

```bash
ollama pull qwen2.5:3b
autojob cards --limit 10          # writes data/cards/<id>.md
```

Cards only use facts from `profile.md` and the job posting. Anything missing is written as
*"Not specified in evidence."* Cards are regenerated only when the posting, your profile, or the model changes.

## Claude Code skills

[`skills/`](skills/) contains three Claude Code skills for the manual steps after triage:

- `jd-triage-5min`: fast apply or skip decision
- `jd-deep-safe-rewrite`: tailored resume bullets without exaggeration
- `github-project-miner`: turn a skill gap into a one-week project

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest -q && ruff check .
```

See [CHANGELOG.md](CHANGELOG.md) for what changed from the v0 scripts.

## License

MIT
