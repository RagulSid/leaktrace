import { useState } from "react";
import { api, Who } from "../api";
import { MapData, MapView } from "../components/MapView";
import { Badge, ErrorBox, LevelBadge, PassFail, timeAgo, useLoad } from "../components/ui";
import { copy, fill } from "../copy";

type QueueRow = { id: string; status: string; severity: string; opened_at: number; decision: string | null; kind: string | null;
  decision_status: string | null; authority_level: string | null; suspect: string | null };
type Check = { code: keyof typeof copy.checks; passed: boolean; detail: any };
type Plan = { id: string; label: string; ops: string[]; passed: boolean; failed_checks: string[]; checks: Check[];
  disruption: number; shortfall: Record<string, number> };

const word = <T extends Record<string, string>>(table: T, key: string | null | undefined) =>
  (key && (table as Record<string, string>)[key]) || key || "";

export function planWords(ops: string[], names: Record<string, string>): string[] {
  if (!ops.length) return [copy.plan.nothing];
  return ops.map((op) => {
    const [verb, id] = op.split(":");
    const name = names[id] ? `${names[id]} (${id.replace("-", "‑")})` : id;
    return fill(verb === "open" ? copy.plan.open : copy.plan.close, { name });
  });
}

function whyWords(f: any): string {
  const t = (copy.why as Record<string, string>)[f.code] || f.code;
  return fill(t, { value: f.value ?? "", allowed: f.allowed ?? "" });
}

export function Problems({ who, id }: { who: Who; id?: string }) {
  const [filter, setFilter] = useState<"open" | "all">("open");
  const queue = useLoad<QueueRow[]>(() => api("/problems"), []);
  const rowsShown = (queue.data || []).filter((r) => filter === "all" || r.status === "open");
  const current = id || rowsShown[0]?.id;
  return (
    <div className="page problems">
      <section className="stack p-queue" aria-label={copy.problems.title}>
        <h1>{copy.problems.title}</h1>
        <div className="row">
          {(["open", "all"] as const).map((f) => (
            <button key={f} className={`chip ${filter === f ? "on" : ""}`} aria-pressed={filter === f} onClick={() => setFilter(f)}>
              {copy.problems.filters[f]}
            </button>
          ))}
        </div>
        <ErrorBox error={queue.error} />
        {queue.data && !rowsShown.length && <p className="muted">{copy.problems.empty}</p>}
        {rowsShown.map((r) => (
          <a key={r.id} href={`#/problems/${r.id}`} className={`queue-item ${r.id === current ? "on" : ""}`} style={{ textDecoration: "none" }}>
            <span className="spread"><b style={{ color: "var(--ink)" }}>{fill(copy.problems.problem, { id: r.id })}</b>
              <span className="small">{word(copy.severity, r.severity)}</span></span>
            <span className="row small muted">{word(copy.status, r.status)} · {timeAgo(r.opened_at)}</span>
            <span className="row" style={{ marginTop: 4 }}>
              <LevelBadge level={r.authority_level} kind={r.kind} />
              {r.decision_status && !["proposed", "recorded"].includes(r.decision_status) && <Badge>{word(copy.status, r.decision_status)}</Badge>}
            </span>
          </a>
        ))}
      </section>
      {current ? <ProblemDetail key={current} who={who} id={current} onChange={queue.reload} /> : <p className="muted">{copy.problems.pick}</p>}
    </div>
  );
}

function ProblemDetail({ who, id, onChange }: { who: Who; id: string; onChange: () => void }) {
  const p = useLoad<any>(() => api(`/problems/${id}`), [id]);
  const m = useLoad<MapData>(() => api(`/problems/${id}/map`), [id]);
  const [busy, setBusy] = useState(false);
  const [actErr, setActErr] = useState<unknown>(null);
  const [allPlans, setAllPlans] = useState(false);
  if (p.error) return <div className="p-head"><ErrorBox error={p.error} /></div>;
  if (!p.data) return <p className="muted p-head">{copy.app.loading}</p>;
  const d = p.data.decision;
  const st = p.data.status;
  const names: Record<string, string> = Object.fromEntries((m.data?.nodes || []).map((n) => [n.id, n.name || n.id]));
  const plans: Plan[] = d?.plans || [];
  const chosen = plans.find((x) => x.id === d?.chosen);
  const fallback = plans.find((x) => x.id === d?.fallback);
  const conf = d?.suspect?.confidence;

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setActErr(null);
    try { await fn(); } catch (e) { setActErr(e); } finally { setBusy(false); p.reload(); m.reload(); onChange(); }
  }
  const approveAndRun = () => act(async () => {
    await api(`/decisions/${d.decision_id}/approve`, { method: "POST", body: {} });
    try { await api(`/decisions/${d.decision_id}/execute`, { method: "POST" }); } catch { /* a helper may have started it */ }
  });
  const decider = ["operator", "manager"].includes(who.role);
  const ownRequest = d?.requested_by === who.user;
  const canApprove = decider && st?.status === "proposed" && st?.authority_level === "L3" && d?.kind === "act";

  const ranked = [chosen, fallback, ...plans.filter((x) => x !== chosen && x !== fallback)].filter(Boolean) as Plan[];
  const shown = allPlans ? ranked : ranked.slice(0, 3);
  const path: string[] = (d?.evidence_paths?.[0] || "").split("->").map((x: string) => x.trim()).filter(Boolean);

  return (
    <>
      <section className="stack p-head">
        <div className="stack" style={{ gap: 4 }}>
          <h1>{d?.suspect ? fill(copy.problems.leakOn, { where: names[d.suspect.segment] || d.suspect.segment }) : copy.problems.noSuspect}</h1>
          <p className="muted">{fill(copy.problems.problem, { id })} · {fill(copy.problems.opened, { when: timeAgo(p.data.incident.opened_at) })}</p>
          {conf && (
            <p><b>{fill(copy.problems.howSure, { level: word(copy.sure, conf.level) })}</b>
              <span className="muted"> · {fill(copy.problems.signs, { n: conf.signs_agree, total: conf.kinds_total })}</span></p>
          )}
        </div>
      </section>
      <section className="stack p-body">
        <div className="card stack">
          <div className="spread"><h2>{copy.problems.mapTitle}</h2>
            <span className="row"><Badge kind="path">{copy.problems.mapWhy}</Badge><Badge kind="ok-needed">{copy.problems.mapAffected}</Badge><Badge>{copy.problems.mapPlan}</Badge></span></div>
          <div className="map-wrap">
            {m.error ? <ErrorBox error={m.error} /> : m.data ? <MapView data={m.data} label={copy.problems.mapTitle} /> : <div className="map" />}
          </div>
          {path.length > 0 && <p className="small path-text">{fill(copy.problems.pathText, { path: path.map((x) => names[x] || x).join(" → ") })}</p>}
          <p className="muted small">{copy.problems.mapLegend}</p>
        </div>
        <div className="stack">
          <h2>{copy.problems.plansTitle}</h2>
          {!plans.length && <p className="muted">{copy.problems.noPlans}</p>}
          <div className="plans">
            {shown.map((pl) => {
              const short = Object.values(pl.shortfall || {}).filter((v) => v > 0).length;
              return (
                <div key={pl.id} className={`card stack plan ${pl.id === d.chosen ? "chosen" : ""}`} style={{ gap: 8 }}>
                  <div className="row">
                    {pl.id === d.chosen && <Badge kind="accent">{copy.badges.recommended}</Badge>}
                    {pl.id === d.fallback && <Badge>{copy.badges.backup}</Badge>}
                  </div>
                  {planWords(pl.ops, names).map((t) => <b key={t} style={{ color: "var(--ink)" }}>{t}</b>)}
                  <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0, gap: 4 }}>
                    {pl.checks.map((c) => (
                      <li key={c.code} className="small"><PassFail passed={c.passed} /> {word(copy.checks, c.code)}</li>
                    ))}
                  </ul>
                  <p className="muted small">{short === 1 ? copy.problems.planShortOne : short ? fill(copy.problems.planShort, { n: short }) : copy.problems.planAllGood}</p>
                </div>
              );
            })}
          </div>
          {ranked.length > 3 && (
            <div><button className="btn" onClick={() => setAllPlans(!allPlans)}>
              {allPlans ? copy.problems.showFewer : fill(copy.problems.showAll, { n: ranked.length })}</button></div>
          )}
        </div>
        <details className="card">
          <summary>{copy.details.title}</summary>
          <div className="stack small mono" style={{ marginTop: 8 }}>
            {d && <span>{fill(copy.details.decision, { id: d.decision_id })}</span>}
            <span>{fill(copy.details.incident, { id })}</span>
            {d?.suspect && <span>{fill(copy.details.segment, { id: d.suspect.segment })}</span>}
            {conf && <span>{fill(copy.details.confidence, { score: conf.score })}</span>}
            {st && <span>{fill(copy.details.authority, { level: st.authority_level, codes: (st.failed_conditions || []).join(", ") || copy.app.none })}</span>}
          </div>
        </details>
      </section>

      <aside className="stack p-aside">
        <div className="card stack">
          <span className="label">{copy.problems.recommendedTitle}</span>
          {d?.kind === "request_evidence" && <div className="banner">{copy.problems.needInfo}</div>}
          {d?.kind === "escalate" && <div className="banner">{copy.problems.peopleDecide}</div>}
          {chosen && (
            <>
              {planWords(chosen.ops, names).map((t) => <b key={t} style={{ color: "var(--ink)" }}>{t}</b>)}
              <p className="muted small">{fallback ? fill(copy.problems.backupLabel, { plan: planWords(fallback.ops, names).join(", ") }) : copy.problems.noBackup}</p>
            </>
          )}
          {st && d?.kind === "act" && (
            <div className="stack" style={{ gap: 6 }}>
              <LevelBadge level={st.authority_level} kind={d.kind} why />
              {st.authority_level !== "L2" && (st.failed_conditions?.length ? (d.authority?.failed || st.failed_conditions.map((c: string) => ({ code: c }))) : [])
                .map((f: any, i: number) => <span key={i} className="small"><span className="fail">{copy.badges.fail}</span> {whyWords(f)}</span>)}
              {st.authority_level === "L2" && <p className="small">{copy.problems.autoBy}</p>}
            </div>
          )}
          {st && st.status !== "proposed" && st.status !== "recorded" && (
            <Badge kind={st.status === "verified" ? "good" : ["failed", "rolled_back", "rollback_failed"].includes(st.status) ? "bad" : ""}>{word(copy.status, st.status)}</Badge>
          )}
          {st?.approval && st.approval.by !== "auto" && <p className="small muted">{fill(copy.problems.approvedBy, { who: word(copy.problems.actors, st.approval.by) })}</p>}
          {canApprove && ownRequest && <p className="small muted">{copy.problems.cannotApproveOwn}</p>}
          {canApprove && !ownRequest && (
            <>
              <button className="btn primary block" disabled={busy} onClick={approveAndRun}>{copy.problems.approve}</button>
              <button className="btn block" disabled={busy} onClick={() => act(() => api(`/decisions/${d.decision_id}/reject`, { method: "POST", body: {} }))}>{copy.problems.dontApprove}</button>
            </>
          )}
          {decider && st && ["verified", "failed"].includes(st.status) && (
            <button className="btn block" disabled={busy} onClick={() => act(() => api(`/decisions/${d.decision_id}/rollback`, { method: "POST", body: {} }))}>{copy.problems.undo}</button>
          )}
          <ErrorBox error={actErr} />
        </div>
        {st?.tasks?.length ? (
          <div className="card stack">
            <span className="label">{copy.problems.steps}</span>
            {st.tasks.map((t: any) => (
              <span key={t.id} className="spread small">
                <span>{planWords([`${t.target === "closed" ? "close" : "open"}:${t.valve}`], names)[0]}</span>
                <span className="muted">{word(copy.problems.stepStatus, t.status)}</span>
              </span>
            ))}
          </div>
        ) : st?.status === "proposed" && d?.kind === "act" ? (
          <div className="card stack small">
            <span className="label">{copy.problems.afterTitle}</span>
            <span>1 {copy.problems.after1}</span><span>2 {copy.problems.after2}</span><span>3 {copy.problems.after3}</span>
          </div>
        ) : null}
        {st?.verification && (
          <div className={`banner ${st.verification.passed ? "good" : "bad"}`}>
            {st.verification.passed ? copy.problems.checkPass
              : fill(copy.problems.checkFail, { why: st.verification.failed_checks.map((c: string) => word(copy.checks, c)).join(", ") })}
          </div>
        )}
        {st?.status === "rolled_back" && <div className="banner bad">{copy.problems.undone}</div>}
      </aside>
    </>
  );
}
