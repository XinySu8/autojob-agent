import argparse
import subprocess
import sys
from pathlib import Path

# NOTE: Comments are intentionally in English per your preference.
REPO_ROOT = Path(__file__).resolve().parents[2]  # repo/
V3 = REPO_ROOT / "v3"

RUN_AGENT = [sys.executable, "-m", "v3.scripts.run_v3_langchain"]
VALIDATE = [sys.executable, "v3/scripts/validate_agent_results.py"]
NORMALIZE = [sys.executable, "v3/scripts/normalize_agent_results.py"]
BUILD_VIEW = [sys.executable, "v3/scripts/build_view_model_from_agent.py"]
SYNC_STATUS = [sys.executable, "v3/scripts/sync_status_into_view_model.py"]  # optional


def run(cmd, check=True):
    print(f"\n>>> {' '.join(map(str, cmd))}")
    return subprocess.run(cmd, cwd=str(REPO_ROOT), check=check)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="llama3.1:8b")
    p.add_argument("--top_n", type=int, default=3)
    p.add_argument("--timeout_s", type=int, default=600)
    p.add_argument("--sync_status", action="store_true", help="Optionally sync state.json into view_model.json")
    args = p.parse_args()

    # 1) Run agent
    run(RUN_AGENT + ["--model", args.model, "--top_n", str(args.top_n), "--timeout_s", str(args.timeout_s)])

    # 2) Validate raw output
    run(VALIDATE + ["v3/output/agent_results.json"])

    # 3) Normalize
    run(NORMALIZE)

    # 4) Validate normalized output
    run(VALIDATE + ["v3/output/agent_results.normalized.json"])

    # 5) Build view_model.json (UI reads this)
    run(BUILD_VIEW)

    # 6) Optional: sync status from state.json
    if args.sync_status:
        run(SYNC_STATUS)

    print("\n✅ Done. UI data is at: v3/data/view_model.json")


if __name__ == "__main__":
    main()