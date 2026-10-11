import type { Run } from "../api/client";

export function RunsView({ runs }: { runs: Run[] }) {
  return (
    <main className="narrow">
      <h2>Pipeline runs</h2>
      <table className="grid">
        <thead>
          <tr><th>#</th><th>Started</th><th>Status</th><th>Fetched</th><th>Relevant</th><th>New</th><th>Apply / Maybe / Skip</th><th>Warnings</th></tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id} title={r.error ?? r.warnings.join("\n")}>
              <td>{r.id}</td>
              <td>{new Date(r.started_at).toLocaleString()}</td>
              <td><span className={`badge ${r.status}`}>{r.status}</span></td>
              <td>{r.fetched.toLocaleString()}</td>
              <td>{r.matched}</td>
              <td>{r.new_jobs}</td>
              <td>{r.counts.apply ?? 0} / {r.counts.maybe ?? 0} / {r.counts.skip ?? 0}</td>
              <td>{r.warnings.length}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
