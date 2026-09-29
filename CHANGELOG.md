# Changelog

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
