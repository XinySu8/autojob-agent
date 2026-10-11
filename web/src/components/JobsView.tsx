import { useEffect, useState } from "react";
import { api, call, type Bucket, type Job, type Run, type Status } from "../api/client";
import { JobPanel } from "./JobPanel";

const BUCKETS: Bucket[] = ["apply", "maybe", "skip"];
const STATUS_FILTERS: { value: Status | ""; label: string }[] = [
  { value: "new", label: "To review" },
  { value: "applied", label: "Applied" },
  { value: "ignored", label: "Ignored" },
  { value: "", label: "All" },
];

export function JobsView({ run, version, onError }: { run?: Run; version: number; onError: (e: string) => void }) {
  const [bucket, setBucket] = useState<Bucket>("apply");
  const [status, setStatus] = useState<Status | "">("new");
  const [q, setQ] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const query = { bucket, status: status || undefined, q: q || undefined, limit: 200 };
    const t = setTimeout(() => {
      call(api.GET("/api/jobs", { params: { query } }))
        .then((page) => {
          setJobs(page.items);
          setTotal(page.total);
        })
        .catch((e) => onError(String(e)));
    }, 150); // debounce typing
    return () => clearTimeout(t);
  }, [bucket, status, q, version, refresh, onError]);

  return (
    <main className={`jobs ${selected ? "with-panel" : ""}`}>
      <section>
        <div className="filters">
          {BUCKETS.map((b) => (
            <button key={b} className={`tab ${bucket === b ? "on" : ""}`} onClick={() => setBucket(b)}>
              {b[0].toUpperCase() + b.slice(1)} <span className="muted">{run?.counts[b] ?? 0}</span>
            </button>
          ))}
          <select value={status} onChange={(e) => setStatus(e.target.value as Status | "")}>
            {STATUS_FILTERS.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
          <input type="search" placeholder="Search title, company, location…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <p className="muted small">{total} job{total === 1 ? "" : "s"}</p>
        <ul className="list">
          {jobs.map((j) => (
            <li key={j.id} className={`row ${selected === j.id ? "sel" : ""} ${j.status !== "new" ? "dim" : ""}`} onClick={() => setSelected(j.id)}>
              <div className="row-main">
                <div className="row-title">
                  {j.title} {j.is_new && <span className="badge new">new</span>}
                </div>
                <div className="muted small">{j.company} · {j.location || "location n/a"}</div>
              </div>
              <div className="row-side">
                {j.review_verdict && <span className={`badge ${j.review_verdict}`} title="AI agent verdict">AI: {j.review_verdict}</span>}
                {j.label && <span className="badge label" title="Your label">✓ {j.label}</span>}
                <span className="score">{j.score?.score.toFixed(2)}</span>
              </div>
            </li>
          ))}
          {jobs.length === 0 && <li className="empty muted">{run ? "Nothing here." : "Run the pipeline to see jobs."}</li>}
        </ul>
      </section>
      {selected && (
        <JobPanel
          id={selected}
          onClose={() => setSelected(null)}
          onChanged={() => setRefresh((n) => n + 1)}
          onError={onError}
        />
      )}
    </main>
  );
}
