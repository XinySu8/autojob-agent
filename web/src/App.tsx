import { useEffect, useState } from "react";
import { api, call, type Run } from "./api/client";
import { EvalView } from "./components/EvalView";
import { JobsView } from "./components/JobsView";
import { RunsView } from "./components/RunsView";

type View = "jobs" | "eval" | "runs";

export function App() {
  const [view, setView] = useState<View>("jobs");
  const [runs, setRuns] = useState<Run[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0); // bump to make children refetch

  const loadRuns = () => call(api.GET("/api/runs")).then(setRuns).catch((e) => setError(String(e)));
  useEffect(() => void loadRuns(), []);

  // While a run is in progress, poll until it finishes, then refresh everything.
  useEffect(() => {
    if (!running) return;
    const t = setInterval(async () => {
      const latest = (await call(api.GET("/api/runs")))[0];
      if (latest && latest.status !== "running") {
        setRunning(false);
        setRuns(await call(api.GET("/api/runs")));
        setVersion((v) => v + 1);
        if (latest.status === "failed") setError(`Run failed: ${latest.error}`);
      }
    }, 2000);
    return () => clearInterval(t);
  }, [running]);

  async function startRun() {
    setError(null);
    try {
      await call(api.POST("/api/runs"));
      setRunning(true);
    } catch (e) {
      setError(String(e));
    }
  }

  const last = runs.find((r) => r.status === "succeeded");
  return (
    <div className="app">
      <header className="top">
        <div>
          <h1>AutoJob</h1>
          <p className="muted">
            {last
              ? `Run #${last.id} · ${new Date(last.started_at).toLocaleString()} · ${last.fetched.toLocaleString()} postings → ${last.matched} relevant · ${last.new_jobs} new`
              : "No runs yet — click “Run now” to fetch jobs."}
          </p>
        </div>
        <nav>
          {(["jobs", "eval", "runs"] as View[]).map((v) => (
            <button key={v} className={`tab ${view === v ? "on" : ""}`} onClick={() => setView(v)}>
              {{ jobs: "Jobs", eval: "Evaluation", runs: "Runs" }[v]}
            </button>
          ))}
          <button className="primary" onClick={startRun} disabled={running}>
            {running ? "Running…" : "Run now"}
          </button>
        </nav>
      </header>
      {error && <div className="error" onClick={() => setError(null)}>{error}</div>}
      {view === "jobs" && <JobsView run={last} version={version} onError={setError} />}
      {view === "eval" && <EvalView version={version} />}
      {view === "runs" && <RunsView runs={runs} />}
    </div>
  );
}
