import { useState } from "react";
import { api } from "../api";
import { ErrorBox, timeAgo, useLoad } from "../components/ui";
import { copy, fill } from "../copy";

type Status = { code: string; sent_at: number; stages: { key: keyof typeof copy.track.stages; done: boolean; current: boolean }[];
  others: number; can_confirm: boolean };

export function TrackReport({ code }: { code?: string }) {
  const [entry, setEntry] = useState(code || "");
  const [thanks, setThanks] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const { data, error, reload } = useLoad<Status | null>(() => (code ? api(`/public/reports/${encodeURIComponent(code)}`) : Promise.resolve(null)), [code]);
  async function confirm() {
    setErr(null);
    try {
      const out = await api<{ code: string }>(`/public/reports/${encodeURIComponent(code!)}/confirm`, { method: "POST" });
      setThanks(fill(copy.track.thanks, { code: out.code }));
      reload();
    } catch (e) {
      setErr(e);
    }
  }
  if (!code) {
    return (
      <div className="page-narrow">
        <form className="stack" onSubmit={(e) => { e.preventDefault(); if (entry.trim()) window.location.hash = `#/track/${entry.trim().toUpperCase()}`; }}>
          <h1>{copy.track.title}</h1>
          <label className="field">{copy.track.enter}<input value={entry} onChange={(e) => setEntry(e.target.value)} placeholder={copy.track.codeExample} /></label>
          <button className="btn block" type="submit">{copy.track.find}</button>
        </form>
      </div>
    );
  }
  return (
    <div className="page-narrow stack">
      <h1>{copy.track.title}</h1>
      <ErrorBox error={error} />
      {data && (
        <>
          <div className="row"><span className="badge mono">{data.code}</span><span className="muted small">{fill(copy.track.sent, { when: timeAgo(data.sent_at) })}</span></div>
          <h2>{copy.track.standing}</h2>
          <ol className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {data.stages.map((s) => (
              <li key={s.key} className="spread">
                <span className="row">
                  <span aria-hidden="true">{s.done ? "●" : s.current ? "◐" : "○"}</span>
                  <span className={s.done ? "" : "muted"}>{copy.track.stages[s.key]}</span>
                </span>
                {s.current && <span className="muted small">{copy.track.next}</span>}
              </li>
            ))}
          </ol>
          <div className="card stack">
            <p>{data.others ? fill(copy.track.others, { n: data.others }) : copy.track.noOthers}</p>
            {data.can_confirm ? (
              <>
                <p className="muted small">{copy.track.seeingIt}</p>
                <button className="btn primary block" onClick={confirm}>{copy.track.seeToo}</button>
              </>
            ) : <p className="muted small">{copy.track.closed}</p>}
            {thanks && <p className="pass" role="status">{thanks}</p>}
            <ErrorBox error={err} />
          </div>
          <div className="dashed">{copy.track.notice}</div>
        </>
      )}
    </div>
  );
}
