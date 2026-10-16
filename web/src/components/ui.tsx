import { ReactNode, useEffect, useState } from "react";
import { ApiError } from "../api";
import { copy, fill } from "../copy";

export function Badge({ kind, children }: { kind?: string; children: ReactNode }) {
  return <span className={`badge ${kind || ""}`}>{children}</span>;
}

/** The word badge for how much the helpers may do: always words, never colour alone. */
export function LevelBadge({ level, kind, why }: { level?: string | null; kind?: string | null; why?: boolean }) {
  if (kind === "request_evidence") return <Badge kind="people">{copy.badges.request_evidence}</Badge>;
  if (kind === "escalate" || level === "L4") return <Badge kind="people">{copy.badges.L4}</Badge>;
  if (level === "L2") return <Badge kind="good">{copy.badges.L2}</Badge>;
  if (level === "L3") return <Badge kind="ok-needed">{why ? copy.badges.L3why : copy.badges.L3}</Badge>;
  return null;
}

export function PassFail({ passed }: { passed: boolean }) {
  return <span className={passed ? "pass" : "fail"}>{passed ? copy.badges.pass : copy.badges.fail}</span>;
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const e = error as ApiError;
  let text: string;
  if (e instanceof ApiError && e.mapDown) text = copy.errors.mapDown;
  else if (e instanceof ApiError && e.status === 403) text = copy.errors.notAllowed;
  else if (e instanceof ApiError && e.status === 404) text = copy.errors.notFound;
  else if (e instanceof ApiError && e.status === 429) text = copy.errors.tooMany;
  else text = fill(copy.errors.generic, { why: e instanceof ApiError ? e.code : String(error) });
  return <div className="error" role="alert">{text}<DownDetails error={error} /></div>;
}

/** What the server said about FalkorDB (reason, host, port, graph), only in the Details drawer. */
export function DownDetails({ error }: { error: unknown }) {
  const b = error instanceof ApiError && error.mapDown ? (error.body as Record<string, any> | null) : null;
  if (!b || !b.reason) return null;
  const reasons = copy.details.graphReason as Record<string, string>;
  const hints = copy.details.graphHint as Record<string, string>;
  return (
    <details className="small">
      <summary>{copy.details.title}</summary>
      <div className="mono">{fill(copy.details.graphDown, { reason: reasons[b.reason] || b.reason, host: String(b.host), port: String(b.port), graph: String(b.graph ?? "-") })}</div>
      {hints[b.reason] && <div className="mono">{hints[b.reason]}</div>}
    </details>
  );
}

/** Load data from the API; `reload` runs it again. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    setError(null);
    fn().then((d) => { if (live) setData(d); }).catch((e) => { if (live) { setError(e); setData(null); } });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n]);
  return { data, error, reload: () => setN((x) => x + 1) };
}

export function timeAgo(ts?: number | null): string {
  if (!ts) return copy.app.never;
  return new Date(ts * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function Tabs<K extends string>({ tabs, value, onChange }: { tabs: Record<K, string>; value: K; onChange: (k: K) => void }) {
  return (
    <div className="tabs" role="tablist">
      {(Object.keys(tabs) as K[]).map((k) => (
        <button key={k} role="tab" aria-selected={k === value} className={k === value ? "on" : ""} onClick={() => onChange(k)}>
          {tabs[k]}
        </button>
      ))}
    </div>
  );
}
