import { useEffect, useState } from "react";
import { api, Who } from "../api";
import { Badge, ErrorBox, Tabs, timeAgo, useLoad } from "../components/ui";
import { copy, fill } from "../copy";

type Tab = keyof typeof copy.auto.tabs;
type Field = keyof typeof copy.auto.fields;

export function AutoMode({ who, onPaused }: { who: Who; onPaused: () => void }) {
  const [tab, setTab] = useState<Tab>("settings");
  const pol = useLoad<any[]>(() => api("/policies"), []);
  const rev = useLoad<any>(() => api("/review"), []);
  const learned = useLoad<any>(() => api("/learned"), []);
  const [form, setForm] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const policy = pol.data?.[0]?.policy;
  const manager = who.role === "manager";
  useEffect(() => {
    if (policy) setForm(Object.fromEntries((Object.keys(copy.auto.fields) as Field[]).map((k) => [k, String(policy[k] ?? "")])));
  }, [policy]);
  async function run(fn: () => Promise<unknown>, done?: string) {
    setErr(null);
    setMsg(null);
    try { await fn(); if (done) setMsg(done); } catch (e) { setErr(e); } finally { pol.reload(); rev.reload(); learned.reload(); onPaused(); }
  }
  const changes = policy ? Object.fromEntries(Object.entries(form).filter(([k, v]) => String(policy[k] ?? "") !== v)) : {};
  const reviewCount = (rev.data?.reviews || []).filter((r: any) => r.status === "open").length + (rev.data?.knowledge || []).length;

  return (
    <div className="page stack">
      <h1>{copy.auto.title}</h1>
      <Tabs tabs={{ ...copy.auto.tabs, review: `${copy.auto.tabs.review} (${reviewCount})` }} value={tab} onChange={setTab} />
      <ErrorBox error={pol.error || rev.error || learned.error || err} />
      {msg && <p className="pass" role="status">{msg}</p>}

      {tab === "settings" && policy && (
        <div className="two">
          <div className="stack">
            <div className="card spread">
              <div className="stack" style={{ gap: 4 }}>
                <b style={{ color: "var(--ink)" }}>{policy.frozen ? copy.auto.isPaused : copy.auto.isOn}</b>
                <span className="muted small">{copy.auto.pauseNote}</span>
              </div>
              {manager && (
                <button className="btn" onClick={() => run(() => api(`/policies/${policy.id}/pause`, { method: "POST", body: { paused: !policy.frozen } }))}>
                  {policy.frozen ? copy.auto.resume : copy.auto.pause}
                </button>
              )}
            </div>
            <form className="card stack" onSubmit={(e) => { e.preventDefault(); run(() => api(`/policies/${policy.id}`, { method: "PUT", body: { changes } }), copy.auto.saved); }}>
              <h2>{copy.auto.mayDo}</h2>
              {(Object.keys(copy.auto.fields) as Field[]).map((k) => (
                <label key={k} className="field small">{copy.auto.fields[k]}
                  <input inputMode="decimal" disabled={!manager} value={form[k] ?? ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
                </label>
              ))}
              {manager ? <button className="btn primary block" type="submit" disabled={!Object.keys(changes).length}>{copy.auto.save}</button>
                : <p className="muted small">{copy.auto.readOnly}</p>}
            </form>
          </div>
          <Proven learned={learned.data} />
        </div>
      )}

      {tab === "review" && rev.data && (
        <div className="two">
          <div className="card stack">
            <h2>{copy.auto.onTheirOwn}</h2>
            {!rev.data.on_their_own.length && <p className="muted">{copy.auto.nothingOwn}</p>}
            {rev.data.on_their_own.map((a: any) => (
              <div key={a.decision} className="stack" style={{ gap: 4, borderBottom: "1px solid var(--line)", paddingBottom: 8 }}>
                <span className="spread"><b style={{ color: "var(--ink)" }}>{fill(copy.problems.problem, { id: a.incident })}</b>
                  <Badge kind={a.status === "verified" ? "good" : ["rolled_back", "failed"].includes(a.status) ? "bad" : ""}>{(copy.status as Record<string, string>)[a.status] || a.status}</Badge></span>
                <span className="small muted">{a.actions.map((x: any) => fill(x.to_state === "open" ? copy.plan.open : copy.plan.close, { name: x.valve })).join(", ")} · {timeAgo(a.last)}</span>
              </div>
            ))}
          </div>
          <div className="card stack">
            <h2>{copy.auto.reviewItems}</h2>
            {!rev.data.reviews.length && <p className="muted">{copy.auto.nothingToReview}</p>}
            {rev.data.reviews.map((r: any) => (
              <div key={r.id} className="spread">
                <span className="stack" style={{ gap: 2 }}>
                  <Badge kind={r.kind === "break_glass" ? "bad" : "people"}>{(copy.auto.reviewKinds as Record<string, string>)[r.kind] || r.kind}</Badge>
                  <span className="small muted">{timeAgo(r.created_at)}</span>
                </span>
                {manager && r.status === "open" && <button className="btn" onClick={() => run(() => api(`/reviews/${r.id}/resolve`, { method: "POST" }))}>{copy.auto.markReviewed}</button>}
              </div>
            ))}
            {(rev.data.knowledge || []).length > 0 && <h2>{copy.auto.nameChecks}</h2>}
            {(rev.data.knowledge || []).map((r: any) => {
              let word = "";
              try { word = JSON.parse(r.detail || "{}").word || ""; } catch { /* keep empty */ }
              return (
                <div key={r.id} className="spread">
                  <span className="small">{fill(copy.auto.nameCheck, { source: r.source_id, word })}</span>
                  {manager && <button className="btn" onClick={() => run(() => api(`/reviews/${r.id}/resolve`, { method: "POST" }))}>{copy.auto.markReviewed}</button>}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {tab === "learned" && learned.data && (
        <div className="two">
          <div className="card stack">
            <h2>{copy.auto.things}</h2>
            {!learned.data.facts.length && <p className="muted">{copy.auto.noThings}</p>}
            {learned.data.facts.map((f: any) => (
              <div key={f.id} className="stack" style={{ gap: 4, borderBottom: "1px solid var(--line)", paddingBottom: 8 }}>
                <span>{f.statement}</span>
                <span className="row small muted">
                  {fill(copy.auto.sure, { pct: Math.round((f.confidence || 0) * 100) })} ·
                  {f.source === "field" ? ` ${copy.auto.fromField}` : f.source === "verification" ? ` ${copy.auto.fromCheck}` : f.source === "synthetic" ? ` ${copy.auto.fromRecords}` : ` ${f.source}`}
                  {f.status === "retired" && <Badge>{copy.auto.retired}</Badge>}
                  {f.status === "superseded" && <Badge>{copy.auto.replaced}</Badge>}
                </span>
                {manager && f.status !== "retired" && f.status !== "superseded" && (
                  <span className="row">
                    <button className="btn" onClick={() => run(() => api(`/facts/${f.id}/confirm`, { method: "POST" }))}>{copy.auto.confirmIt}</button>
                    <button className="btn" onClick={() => run(() => api(`/facts/${f.id}/retire`, { method: "POST" }))}>{copy.auto.retire}</button>
                  </span>
                )}
              </div>
            ))}
          </div>
          <Proven learned={learned.data} />
        </div>
      )}

      {tab === "notices" && <div className="dashed">{copy.auto.notices}</div>}

      {tab === "history" && pol.data && (
        <div className="card stack">
          <h2>{copy.auto.history}</h2>
          {!pol.data[0]?.history?.length && <p className="muted">{copy.auto.noHistory}</p>}
          {(pol.data[0]?.history || []).map((h: any, i: number) => (
            <span key={i} className="small">{timeAgo(h.ts)} · {fill(copy.auto.changedBy, { who: h.actor,
              what: Object.keys(h.detail || {}).map((k) => fill(copy.auto.changeLine, { field: (copy.auto.fields as Record<string, string>)[k] || k,
                from: String(h.detail[k].from), to: String(h.detail[k].to) })).join("; ") })}</span>
          ))}
        </div>
      )}
    </div>
  );
}

function Proven({ learned }: { learned: any }) {
  return (
    <div className="card stack">
      <h2>{copy.auto.proven}</h2>
      {learned && !learned.playbooks.length && <p className="muted">{copy.auto.noProven}</p>}
      {(learned?.playbooks || []).map((p: any) => (
        <div key={p.id} className="stack" style={{ gap: 2 }}>
          <b style={{ color: "var(--ink)" }}>{fill(copy.auto.provenName, {
            steps: (p.steps || []).map((s: string) => { const [v, id] = s.split(":"); return fill(v === "open" ? copy.plan.open : copy.plan.close, { name: learned.names?.[id] || id }); }).join(", "),
            where: learned.names?.[p.segment] || p.segment })}</b>
          <span className="small muted">{fill(copy.auto.provenLine, { s: p.successes, f: p.failures })}</span>
        </div>
      ))}
    </div>
  );
}
