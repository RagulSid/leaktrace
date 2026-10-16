import { useState } from "react";
import { api, Who } from "../api";
import { Badge, ErrorBox, useLoad } from "../components/ui";
import { copy, fill } from "../copy";

type Step = { id: string; seq: number; valve: string; target: string; status: string; owner: string | null;
  idempotency_key: string; decision: string; authority_level: string; approvers: string[] };
type Job = { id: string; kind: keyof typeof copy.jobs.kinds; target: string; target_name: string | null; status: string;
  steps: string[]; confirmed: string[]; assigned_to: string | null; incident: string };

export function Jobs({ who }: { who: Who }) {
  const steps = useLoad<Step[]>(() => api("/crew/steps"), []);
  const jobs = useLoad<Job[]>(() => api("/work-orders"), []);
  const [err, setErr] = useState<unknown>(null);
  const [note, setNote] = useState<string | null>(null);
  const [findings, setFindings] = useState<Record<string, string>>({});
  const [stuck, setStuck] = useState<Record<string, string>>({});
  const reload = () => { steps.reload(); jobs.reload(); };
  async function run(fn: () => Promise<unknown>, after?: string) {
    setErr(null);
    setNote(null);
    try { await fn(); if (after) setNote(after); } catch (e) { setErr(e); } finally { reload(); }
  }
  const mine = (steps.data || []).find((s) => s.status === "claimed" && s.owner === who.user);
  const next = (steps.data || []).find((s) => s.status === "open");
  const report = (s: Step, done: boolean) => run(() => api(`/tasks/${s.id}/result`, {
    method: "POST",
    body: done ? { idempotency_key: s.idempotency_key, outcome: "done", observed_state: s.target }
      : { idempotency_key: s.idempotency_key, outcome: "failed", observed_state: s.target === "open" ? "closed" : "open", reason: "stuck" },
  }), done ? undefined : copy.jobs.lessonSaved);
  const valveText = (s: Step) => fill(copy.jobs.move, { action: copy.jobs.actions[s.target === "open" ? "open" : "closed"], name: s.valve });

  return (
    <div className="page-narrow stack">
      <h1>{copy.jobs.title}</h1>
      <ErrorBox error={steps.error || jobs.error || err} />
      {note && <p className="pass" role="status">{note}</p>}

      <h2>{copy.jobs.valveSteps}</h2>
      {steps.data && !steps.data.length && <p className="muted">{copy.jobs.noSteps}</p>}
      {mine && (
        <div className="card stack" style={{ borderColor: "var(--ink)" }}>
          <b style={{ color: "var(--ink)" }}>{valveText(mine)}</b>
          <p className="small muted">{mine.authority_level === "L2" ? copy.jobs.auto : fill(copy.jobs.approvedBy, { who: mine.approvers.join(", ") })}</p>
          <button className="btn primary block" onClick={() => report(mine, true)}>{copy.jobs.done}</button>
          <button className="btn block" onClick={() => report(mine, false)}>{copy.jobs.wontMove}</button>
        </div>
      )}
      {!mine && next && (
        <div className="card stack">
          <b style={{ color: "var(--ink)" }}>{valveText(next)}</b>
          <p className="small muted">{next.authority_level === "L2" ? copy.jobs.auto : fill(copy.jobs.approvedBy, { who: next.approvers.join(", ") })}</p>
          <button className="btn block" onClick={() => run(() => api("/tasks/claim", { method: "POST", body: {} }))}>{copy.jobs.pickUp}</button>
        </div>
      )}

      <h2>{copy.jobs.fieldJobs}</h2>
      {jobs.data && !jobs.data.length && <p className="muted">{copy.jobs.noJobs}</p>}
      {(jobs.data || []).map((j) => (
        <div key={j.id} className="card stack">
          <div className="spread"><b style={{ color: "var(--ink)" }}>{fill(copy.jobs.kinds[j.kind] || j.kind, { target: j.target_name || j.target })}</b>
            <Badge>{(copy.jobs.jobStatus as Record<string, string>)[j.status] || j.status}</Badge></div>
          <span className="small muted">{fill(copy.jobs.forProblem, { id: j.incident })}</span>
          {j.status === "open" && <button className="btn block" onClick={() => run(() => api(`/work-orders/${j.id}/take`, { method: "POST" }))}>{copy.jobs.take}</button>}
          {j.status === "in_progress" && j.assigned_to === who.user && (
            <>
              <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {j.steps.map((s) => (
                  <li key={s} className="spread">
                    <span className={j.confirmed.includes(s) ? "" : "muted"}>{j.confirmed.includes(s) ? "● " : "○ "}{s}</span>
                    {!j.confirmed.includes(s) && <button className="btn" onClick={() => run(() => api(`/work-orders/${j.id}/confirm`, { method: "POST", body: { step: s } }))}>{copy.jobs.confirm}</button>}
                  </li>
                ))}
              </ul>
              <label className="field small">{copy.jobs.findings}
                <input value={findings[j.id] || ""} onChange={(e) => setFindings({ ...findings, [j.id]: e.target.value })} /></label>
              <label className="field small">{copy.jobs.stuckLabel}
                <input value={stuck[j.id] || ""} placeholder={copy.jobs.stuckExample} onChange={(e) => setStuck({ ...stuck, [j.id]: e.target.value })} /></label>
              <button className="btn block" disabled={j.confirmed.length < j.steps.length}
                onClick={() => run(() => api(`/work-orders/${j.id}/complete`, { method: "POST", body: {
                  findings: findings[j.id] || null, stuck_valves: stuck[j.id] ? [stuck[j.id].trim().toUpperCase()] : [] } }),
                  stuck[j.id] ? copy.jobs.lessonSaved : undefined)}>{copy.jobs.finish}</button>
            </>
          )}
        </div>
      ))}
    </div>
  );
}
