import { api } from "../api";
import { Badge, ErrorBox, timeAgo, useLoad } from "../components/ui";
import { copy, fill } from "../copy";
import { AskPanel } from "../components/AskPanel";

type Step = { ts: number; actor: string; kind: string; tool: string | null; summary: string; ok: boolean;
  chooser: string | null; fallback: string | null; task: string | null; args: Record<string, any> };
type Link = { id: string; kind: string; status: string; agents: string[]; handed_to: string[] };
type Block = { key: string; actor: string; ts: number; steps: Step[]; notice?: string };

const helperName = (k: string) => (copy.who.helpers as Record<string, string>)[k] || k;
const refusal = (code: string) => (copy.who.refusals as Record<string, string>)[code] || code;
const parse = (s: string) => { try { return JSON.parse(s); } catch { return null; } };

/** Exactly what the graph recorded: "rules" or the model's name, and why the rules stood in for a model. */
function pickedBy(steps: Step[]): string[] {
  const seen = new Map<string, string>();
  for (const s of steps) {
    if (!s.chooser) continue;
    const who = s.chooser === "rules" ? copy.who.byRules : s.chooser;
    let text = fill(copy.who.pickedBy, { who });
    if (s.fallback) text += ` · ${fill(copy.who.stoodIn, { why: (copy.who.fallbackWhy as Record<string, string>)[s.fallback] || s.fallback })}`;
    seen.set(`${s.chooser}|${s.fallback}`, text);
  }
  return [...seen.values()];
}

function group(steps: Step[]): Block[] {
  const out: Block[] = [];
  for (const s of steps) {
    if (s.kind === "notify") {
      const code = s.args?.code as string | undefined;
      out.push({ key: `n${s.ts}`, actor: s.actor, ts: s.ts, steps: [], notice: (code && (copy.who.notices as Record<string, string>)[code]) || code || "" });
      continue;
    }
    if (s.kind !== "agent_step") continue;
    const last = out[out.length - 1];
    if (last && !last.notice && last.steps[0]?.task === s.task) last.steps.push(s);
    else out.push({ key: `${s.task}-${s.ts}`, actor: s.actor, ts: s.ts, steps: [s] });
  }
  return out;
}

export function WhoDidWhat({ id }: { id?: string }) {
  const problems = useLoad<any[]>(() => api("/problems"), []);
  const current = id || problems.data?.[0]?.id;
  const t = useLoad<{ chain: Link[]; steps: Step[] } | null>(() => (current ? api(`/problems/${current}/timeline`) : Promise.resolve(null)), [current]);
  const blocks = group(t.data?.steps || []);
  return (
    <div className="page two">
      <section className="stack" style={{ minWidth: 0 }}>
        <h1>{copy.who.title}</h1>
        <label className="field small">{copy.who.pick}
          <select value={current || ""} onChange={(e) => { window.location.hash = `#/who/${e.target.value}`; }}>
            {(problems.data || []).map((p) => <option key={p.id} value={p.id}>{fill(copy.problems.problem, { id: p.id })}</option>)}
          </select>
        </label>
        <ErrorBox error={problems.error || t.error} />
        {t.data && (
          <>
            <div className="chain" aria-label={copy.who.title}>
              {t.data.chain.map((c, i) => (
                <span key={c.id} className="row">
                  {i > 0 && <span className="muted" aria-hidden="true">›</span>}
                  <Badge kind={c.status === "waiting" ? "ok-needed" : c.status === "failed" ? "bad" : ""}>
                    {(copy.who.stepKinds as Record<string, string>)[c.kind] || c.kind}: {(copy.who.stepStatus as Record<string, string>)[c.status] || c.status}
                  </Badge>
                </span>
              ))}
            </div>
            {!blocks.length && <p className="muted">{copy.who.noHelpers}</p>}
            <div>
              {blocks.map((b) => {
                if (b.notice) {
                  return (
                    <div key={b.key} className="timeline-step stack" style={{ gap: 2 }}>
                      <span className="row"><span className="small muted mono">{timeAgo(b.ts / 1e9)}</span><b style={{ color: "var(--ink)" }}>{helperName(b.actor)}</b></span>
                      <span>{b.notice}</span>
                    </div>
                  );
                }
                const results = b.steps.map((s) => parse(s.summary) || {});
                const passed = results.map((r) => r.passed_to).find(Boolean);
                const refused = b.steps.map((s, i) => ({ s, r: results[i] })).filter((x) => x.r.refused);
                const actions = [...new Set(b.steps.map((s) => (copy.who.tools as Record<string, string>)[s.tool || ""] || s.tool || ""))];
                return (
                  <div key={b.key} className="timeline-step stack" style={{ gap: 4 }}>
                    <span className="row"><span className="small muted mono">{timeAgo(b.ts / 1e9)}</span><b style={{ color: "var(--ink)" }}>{helperName(b.actor)}</b></span>
                    <ul style={{ margin: 0, paddingLeft: 18 }}>{actions.map((a) => <li key={a}>{a}</li>)}</ul>
                    {refused.map((x, i) => <span key={i} className="small fail">{fill(copy.who.refused, { why: refusal(x.r.refused) })}</span>)}
                    {passed && <span className="small muted">{fill(copy.who.passedOn, { who: helperName(passed) })}</span>}
                    {pickedBy(b.steps).map((p) => <span key={p} className="small muted">{p}</span>)}
                    <details className="small">
                      <summary>{copy.details.title}</summary>
                      <ul className="mono" style={{ margin: 0, paddingLeft: 18 }}>
                        {b.steps.map((s, i) => (
                          <li key={i}>{fill(copy.details.tool, { name: s.tool || "" })} · {fill(copy.details.chooserRecorded, { value: String(s.chooser) })}
                            {s.fallback ? ` · ${fill(copy.details.fallbackRecorded, { value: s.fallback })}` : ""}</li>
                        ))}
                      </ul>
                    </details>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </section>
      <AskPanel incident={current} />
    </div>
  );
}
