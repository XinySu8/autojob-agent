import { useEffect, useState } from "react";
import { api, call, type Bucket, type JobDetail, type Status } from "../api/client";

const HIT_GROUPS: [string, string][] = [["title", "title"], ["must", "must-have"], ["nice", "nice-to-have"], ["negative", "negative"]];

export function JobPanel({ id, onClose, onChanged, onError }: {
  id: string;
  onClose: () => void;
  onChanged: () => void;
  onError: (e: string) => void;
}) {
  const [job, setJob] = useState<JobDetail | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [note, setNote] = useState("");

  const load = () =>
    call(api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } }))
      .then((j) => {
        setJob(j);
        setNote(j.note);
      })
      .catch((e) => onError(String(e)));
  useEffect(() => void load(), [id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function decide(body: { status?: Status; label?: Bucket | null; note?: string }) {
    try {
      await call(api.PATCH("/api/jobs/{job_id}/decision", { params: { path: { job_id: id } }, body }));
      await load();
      onChanged();
    } catch (e) {
      onError(String(e));
    }
  }

  async function review() {
    setReviewing(true);
    try {
      await call(api.POST("/api/jobs/{job_id}/review", { params: { path: { job_id: id } } }));
      await load();
      onChanged();
    } catch (e) {
      onError(String(e));
    } finally {
      setReviewing(false);
    }
  }

  if (!job) return <aside className="panel muted">Loading…</aside>;
  const s = job.score;
  const r = job.review;
  return (
    <aside className="panel">
      <button className="close" onClick={onClose} aria-label="Close">×</button>
      <h2><a href={job.url} target="_blank" rel="noreferrer">{job.title} ↗</a></h2>
      <p className="muted">{job.company} · {job.location || "n/a"} · {job.source} · first seen {new Date(job.first_seen_at).toLocaleDateString()}</p>

      <div className="block">
        <div className="label-row">Your status</div>
        <div className="btns">
          {(["new", "applied", "ignored"] as Status[]).map((st) => (
            <button key={st} className={job.status === st ? "on" : ""} onClick={() => decide({ status: st })}>{st}</button>
          ))}
        </div>
        <div className="label-row">Correct bucket <span className="muted small">(your label — used by Evaluation)</span></div>
        <div className="btns">
          {(["apply", "maybe", "skip"] as Bucket[]).map((b) => (
            <button key={b} className={job.label === b ? "on" : ""} onClick={() => decide({ label: job.label === b ? null : b })}>{b}</button>
          ))}
        </div>
        <textarea placeholder="Notes (referral, deadline…)" value={note} onChange={(e) => setNote(e.target.value)}
                  onBlur={() => note !== job.note && decide({ note })} />
      </div>

      {s && (
        <div className="block">
          <div className="label-row">Rules <span className={`badge ${s.bucket}`}>{s.bucket}</span> <span className="score">{s.score.toFixed(2)}</span></div>
          <Meter label="keywords" value={s.keyword_score} />
          <Meter label="semantic" value={s.semantic_score} />
          <p className="small muted">{s.reason}</p>
          {HIT_GROUPS.map(([key, name]) =>
            (s.hits[key] ?? []).length > 0 && (
              <div key={key} className="chips">
                <span className="muted small">{name}:</span>
                {s.hits[key].map((h) => <span key={h} className={`chip ${key === "negative" ? "neg" : ""}`}>{h}</span>)}
              </div>
            ))}
        </div>
      )}

      <div className="block">
        <div className="label-row">
          AI agent {r && <span className={`badge ${r.verdict}`}>{r.fallback ? "fallback" : r.verdict}</span>}
          {r && !r.fallback && <span className="muted small">confidence {Math.round(r.confidence * 100)}% · {r.model}</span>}
        </div>
        {r ? (
          <>
            <p>{r.summary}</p>
            <Evidence title="Matches" items={r.matches} />
            <Evidence title="Gaps / risks" items={r.gaps} />
          </>
        ) : (
          <p className="muted small">Not reviewed yet.</p>
        )}
        <button onClick={review} disabled={reviewing}>{reviewing ? "Reviewing… (can take a minute)" : r ? "Re-run review" : "Run AI review"}</button>
      </div>

      {job.history.length > 1 && (
        <div className="block">
          <div className="label-row">History</div>
          <table className="small">
            <tbody>
              {job.history.map((h) => (
                <tr key={h.run_id}><td>Run #{h.run_id}</td><td>{h.score.toFixed(2)}</td><td><span className={`badge ${h.bucket}`}>{h.bucket}</span></td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <details className="block">
        <summary>Job description</summary>
        <p className="jd">{job.content || "No description provided by the board."}</p>
      </details>
    </aside>
  );
}

function Meter({ label, value }: { label: string; value: number }) {
  return (
    <div className="meter-row small">
      <span className="muted">{label}</span>
      <span className="meter"><i style={{ width: `${Math.round(value * 100)}%` }} /></span>
      <span>{value.toFixed(2)}</span>
    </div>
  );
}

function Evidence({ title, items }: { title: string; items: { point: string; quote: string }[] }) {
  if (!items.length) return null;
  return (
    <div>
      <div className="small muted">{title}</div>
      <ul className="evidence">
        {items.map((e, i) => (
          <li key={i}>{e.point}<blockquote>“{e.quote}”</blockquote></li>
        ))}
      </ul>
    </div>
  );
}
