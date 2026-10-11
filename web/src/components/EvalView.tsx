import { useEffect, useState } from "react";
import { api, call, type Eval } from "../api/client";

const pct = (v: number | null | undefined) => (v == null ? "–" : `${Math.round(v * 100)}%`);

export function EvalView({ version }: { version: number }) {
  const [data, setData] = useState<Eval | null>(null);
  useEffect(() => void call(api.GET("/api/eval")).then(setData), [version]);
  if (!data) return <main className="muted">Loading…</main>;

  const ks = data.systems[0] ? Object.keys(data.systems[0].precision_at) : [];
  return (
    <main className="narrow">
      <h2>Ranking quality</h2>
      <p className="muted">
        Measured against your own labels on the latest run. Label jobs in the Jobs tab (“Correct bucket”).
        Precision@k = share of the top k jobs you labeled <b>apply</b>. Aim for 50+ labels, including some apply.
      </p>
      <p>
        <b>{data.labeled}</b> labeled · {Object.entries(data.label_counts).map(([k, v]) => `${v} ${k}`).join(" · ") || "none yet"}
      </p>
      <table className="grid">
        <thead>
          <tr><th>Ranker</th>{ks.map((k) => <th key={k}>P@{k}</th>)}<th>Bucket accuracy</th><th>Agent coverage</th></tr>
        </thead>
        <tbody>
          {data.systems.map((s) => (
            <tr key={s.name}>
              <td>{s.name}</td>
              {ks.map((k) => <td key={k}>{pct(s.precision_at[k])}</td>)}
              <td>{pct(s.bucket_accuracy)}</td>
              <td>{pct(s.agent_coverage)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">“–” means not applicable or not enough labels for that k.</p>
    </main>
  );
}
