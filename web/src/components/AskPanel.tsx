import { FormEvent, useState } from "react";
import { api, session } from "../api";
import { ErrorBox, useLoad } from "./ui";
import { copy, fill } from "../copy";

type Cite = { id: string; kind: string; title: string | null };
type Msg = { id?: string; role: "user" | "assistant"; text: string; cites: Cite[]; known?: boolean | null;
  phrased_by?: string | null; fallback?: string | null; offer?: string | null };

const W = copy.who;
const kindWord = (k: string) => (W.sourceKinds as Record<string, string>)[k] || k;
const why = (k?: string | null) => (k ? (W.askWhy as Record<string, string>)[k] || k : null);

/** Answer text with each [id] shown as a small source tag. */
function Answer({ text }: { text: string }) {
  const parts = text.split(/(\[[A-Za-z0-9][A-Za-z0-9#:._-]*\])/g);
  return <p style={{ margin: 0 }}>{parts.map((p, i) => (/^\[.*\]$/.test(p) ? <span key={i} className="badge mono">{p.slice(1, -1)}</span> : p))}</p>;
}

/** Ask LeakTrace: questions about one problem, saved per person and problem (so it resumes after a restart). */
export function AskPanel({ incident }: { incident?: string }) {
  const hist = useLoad<{ messages: Msg[] }>(() => api(`/brain/conversation${incident ? `?incident=${encodeURIComponent(incident)}` : ""}`), [incident]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [sent, setSent] = useState<Record<string, string>>({});
  const role = session.who()?.role || "";
  const canDispatch = role === "operator" || role === "manager";

  async function ask(question: string, e?: FormEvent) {
    e?.preventDefault();
    if (question.trim().length < 3) return;
    setBusy(true); setErr(null);
    try {
      await api("/brain/ask", { method: "POST", body: { question, incident: incident || null } });
      setQ("");
      hist.reload();
    } catch (x) { setErr(x); } finally { setBusy(false); }
  }

  async function findOut(question: string, key: string) {
    setErr(null);
    try {
      await api("/brain/find-out", { method: "POST", body: { question, incident: incident || null } });
      setSent((s) => ({ ...s, [key]: W.offerSent }));
    } catch (x) { setErr(x); }
  }

  const msgs = hist.data?.messages || [];
  return (
    <aside className="card stack" aria-label={W.ask}>
      <h2>{W.ask}</h2>
      <p className="small muted" style={{ margin: 0 }}>{W.askLead}</p>
      <ErrorBox error={hist.error || err} />
      {msgs.length === 0 && !hist.error && (
        <div className="stack small">
          <span className="muted">{W.askEmpty}</span>
          {W.askExamples.map((x) => <button key={x} className="btn" onClick={() => ask(x)} disabled={busy}>{x}</button>)}
        </div>
      )}
      <div className="stack">
        {msgs.map((m, i) => {
          if (m.role === "user") return <div key={m.id || i} className="small"><b>{W.you}:</b> {m.text}</div>;
          const question = msgs[i - 1]?.text || "";
          const key = m.id || String(i);
          return (
            <div key={key} className="stack" style={{ gap: 6 }}>
              <b className="small">{W.leaktrace}</b>
              {m.known ? <Answer text={m.text} /> : <p style={{ margin: 0 }}>{W.dontKnow}</p>}
              {m.known && m.cites.length > 0 && (
                <div className="small">
                  <span className="muted">{W.sources}: </span>
                  {m.cites.map((c) => (
                    <span key={c.id} className="badge" title={c.title || undefined}>{kindWord(c.kind)} <span className="mono">{c.id}</span></span>
                  ))}
                </div>
              )}
              {!m.known && m.offer === "ask_crew" && (
                canDispatch
                  ? (sent[key] ? <span className="small good">{sent[key]}</span>
                    : <button className="btn" onClick={() => findOut(question, key)}>{W.offer}</button>)
                  : <span className="small muted">{W.offerAskOperator}</span>
              )}
              <details className="small">
                <summary>{copy.details.title}</summary>
                <div className="mono">{fill(W.wordedBy, { who: m.phrased_by === "template" || !m.phrased_by ? W.wordedByTemplates : m.phrased_by })}</div>
                {why(m.fallback) && <div>{why(m.fallback)}</div>}
              </details>
            </div>
          );
        })}
      </div>
      <form className="stack" onSubmit={(e) => ask(q, e)}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={W.askPlaceholder} aria-label={W.askPlaceholder} maxLength={500} />
        <button className="btn block" type="submit" disabled={busy || q.trim().length < 3}>{busy ? W.askBusy : W.askButton}</button>
      </form>
    </aside>
  );
}
