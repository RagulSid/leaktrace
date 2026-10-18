import { useState } from "react";
import { api } from "../api";
import { Badge, DownDetails, ErrorBox, useLoad } from "../components/ui";
import { copy, fill } from "../copy";

const H = copy.howItWorks;
type StepKey = keyof typeof H.steps;

export function HowItWorks() {
  const summary = useLoad<any>(() => api("/how-it-works/summary"), []);
  const steps = useLoad<any>(() => api("/how-it-works/steps"), []);
  const features = useLoad<any>(() => api("/how-it-works/features"), []);
  const proof = useLoad<any>(() => api("/how-it-works/proof"), []);
  const [sel, setSel] = useState<StepKey>("report");
  const [tech, setTech] = useState(false);
  const [result, setResult] = useState<Record<string, any>>({});
  const [runErr, setRunErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  if (summary.error) {
    // Live or absent: with FalkorDB unreachable nothing below is shown, no numbers at all.
    return (
      <div className="hiw">
        <section className="hiw-hero stack"><h1>{H.heroTitle}</h1></section>
        <div className="error" role="alert"><b>{H.down}</b> {H.downText}<DownDetails error={summary.error} /></div>
      </div>
    );
  }
  const s = summary.data;
  const stepList: any[] = steps.data?.steps || [];
  const step = stepList.find((x) => x.key === sel);
  async function run() {
    setBusy(true);
    setRunErr(null);
    try {
      const out = await api(`/how-it-works/run/${sel}`, { method: "POST" });
      setResult({ ...result, [sel]: out });
      features.reload();
    } catch (e) { setRunErr(e); } finally { setBusy(false); }
  }
  const r = result[sel];

  return (
    <div className="hiw">
      <section className="hiw-hero spread" style={{ alignItems: "flex-end" }}>
        <div className="stack" style={{ maxWidth: 720 }}>
          <h1>{H.heroTitle}</h1>
          <p style={{ fontSize: 16 }}>{H.heroText}</p>
        </div>
        <a href="#/how-it-works" onClick={(e) => { e.preventDefault(); document.getElementById("checks")?.scrollIntoView(); }}>{H.seeChecks} →</a>
      </section>

      <section className="stack">
        <div className="spread"><h2>{H.mapNow}</h2><span className="row"><Badge>{H.practice}</Badge><span className="muted small">{H.live}</span></span></div>
        {!s ? <p className="muted">{copy.app.loading}</p> : (
          <>
            <div className="tiles">
              <div className="card tile"><span className="label">{H.connected}</span><div className="num">{copy.app.yes}</div><span className="muted small">{fill(H.connectedYes, { ms: s.ping_ms })}</span></div>
              <div className="card tile"><span className="label">{H.things}</span><div className="num">{s.nodes}</div></div>
              <div className="card tile"><span className="label">{H.links}</span><div className="num">{s.links}</div></div>
              <div className="card tile"><span className="label">{H.kinds}</span><div className="num">{s.kinds}</div></div>
            </div>
            <p className="muted small">{H.shape}</p>
            <div className="scroll-x">
              <table>
                <tbody>
                  {s.shape.slice(0, 12).map((x: any, i: number) => (
                    <tr key={i}><td className="mono">{x.from_kind}</td><td className="mono muted">-[{x.link}]→</td><td className="mono">{x.to_kind}</td><td>{x.links}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      <section className="stack">
        <h2>{H.follow}</h2>
        <ErrorBox error={steps.error} />
        {steps.data && !steps.data.problem && <p className="muted">{H.noProblem}</p>}
        {steps.data?.problem && <p className="muted">{fill(H.followFor, { id: steps.data.problem.incident })}</p>}
        <div className="steps">
          <ol className="stack" style={{ listStyle: "none", padding: 0, margin: 0, gap: 4 }}>
            {(Object.keys(H.steps) as StepKey[]).map((k, i) => (
              <li key={k}><button className={`step-btn ${k === sel ? "on" : ""}`} onClick={() => setSel(k)}>
                <span className="mono">{i + 1}</span><span>{H.steps[k].title}</span></button></li>
            ))}
          </ol>
          <div className="card stack" style={{ minWidth: 0 }}>
            <span className="label">{H.whatHappens}</span><p>{H.steps[sel].what}</p>
            <span className="label">{H.whyMap}</span><p>{H.steps[sel].why}</p>
            <div><button className="btn" aria-pressed={tech} onClick={() => setTech(!tech)}>{tech ? H.hideTech : H.showTech}</button></div>
            {tech && step && (
              <div className="stack">
                <span className="label">{H.search}</span><pre>{step.query}</pre>
                <span className="label">{H.params}</span><pre>{JSON.stringify(step.params, null, 1)}</pre>
                <span className="label">{H.plan}</span><pre>{(step.plan || []).join("\n")}</pre>
                {r?.profile && <><span className="label">{H.cost}</span><pre>{r.profile.join("\n")}</pre></>}
              </div>
            )}
            <div><button className="btn primary" disabled={busy || !steps.data?.problem} onClick={run}>{H.run}</button></div>
            <ErrorBox error={runErr} />
            {r && (
              <div className="stack">
                <span className="small">{fill(H.result, { n: r.row_count, ms: r.ms })}{r.capped ? ` ${fill(H.capped, { cap: r.rows.length })}` : ""}</span>
                <div className="scroll-x">
                  <table>
                    <thead><tr>{Object.keys(r.rows[0] || {}).map((c) => <th key={c} className="mono">{c}</th>)}</tr></thead>
                    <tbody>{r.rows.map((row: any, i: number) => (
                      <tr key={i}>{Object.values(row).map((v: any, j) => <td key={j} className="mono">{typeof v === "object" ? JSON.stringify(v) : String(v)}</td>)}</tr>
                    ))}</tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="stack">
        <h2>{H.versus}</h2>
        {proof.data?.evaluation ? <Versus ev={proof.data.evaluation} /> : <div className="dashed">{H.notMeasured}</div>}
      </section>

      <section className="stack">
        <h2>{H.features}</h2>
        <ErrorBox error={features.error} />
        {features.data && (
          <>
            <div className="scroll-x">
              <table>
                <thead><tr><th>{H.featureCols.feature}</th><th>{H.featureCols.what}</th><th>{H.featureCols.calls}</th><th>{H.featureCols.last}</th></tr></thead>
                <tbody>{features.data.features.map((f: any) => {
                  const row = (H.featureRows as Record<string, { name: string; what: string }>)[f.feature];
                  return <tr key={f.feature}><td>{row?.name || f.feature}</td><td>{row?.what}</td><td>{f.calls}</td><td>{f.last_ms === null ? copy.app.never : `${f.last_ms} ms`}</td></tr>;
                })}</tbody>
              </table>
            </div>
            <p className="muted small">{H.oneMapPerCustomer} {H.since}</p>
            <span className="label">{H.slowest}</span>
            {features.data.slowest.length ? (
              <div className="scroll-x"><table><tbody>{features.data.slowest.map((x: any, i: number) => (
                <tr key={i}><td className="mono">{x.ms} ms</td><td className="mono">{x.query}</td></tr>))}</tbody></table></div>
            ) : <p className="muted">{H.noneSlow}</p>}
          </>
        )}
      </section>

      <section className="stack" id="checks">
        <h2>{H.checksRan}</h2>
        <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {(Object.keys(H.checkNames) as (keyof typeof H.checkNames)[]).map((k) => {
            const c = proof.data?.checks?.checks?.[k];
            return (
              <li key={k} className="spread" style={{ borderBottom: "1px solid var(--line)", paddingBottom: 8 }}>
                <span>{H.checkNames[k]}</span>
                <span className="row small">
                  {c ? <span className={c.result === "pass" ? "pass" : "fail"}>{c.result === "pass" ? H.pass : H.fail}</span> : <span className="muted">{H.notRun}</span>}
                  {c && <span className="muted">{c.when} · {c.environment}</span>}
                </span>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="stack">
        <h2>{H.helpersTitle}</h2>
        <ul>{H.helpersList.map((x) => <li key={x}>{x}</li>)}</ul>
      </section>

      <section className="stack">
        <h2>{H.codeTitle}</h2>
        <ul>{H.codePaths.map((x) => <li key={x} className="mono">{x}</li>)}</ul>
        <p className="muted">{H.readme}</p>
      </section>
    </div>
  );
}

/** The saved ablation and baselines result (app/data/evaluation.json), exactly as measured. */
function Versus({ ev }: { ev: any }) {
  const C = H.versusCols;
  const n = (x: number, runs: number) => fill(H.versusRuns, { n: x, runs });
  return (
    <div className="stack">
      <p className="small muted" style={{ margin: 0 }}>{fill(H.versusLead, { when: ev.ran_at, seeds: ev.seeds, secs: ev.seconds })}</p>
      <div className="scroll-x">
        <table>
          <thead><tr>{[C.case, C.approach, C.stopped, C.keyShort, C.short, C.moves, C.asked, C.lookups, C.maxflow].map((c) => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>{(ev.summary || []).map((r: any) => (
            <tr key={`${r.case}-${r.approach}`}>
              <td title={ev.cases?.[r.case]}>{r.case}</td>
              <td title={ev.approaches?.[r.approach]}>{r.approach}</td>
              <td>{n(r.leak_stopped, r.runs)}</td>
              <td>{n(r.key_rack_short_runs, r.runs)}</td>
              <td>{r.racks_short_avg}</td>
              <td>{r.moves_avg}</td>
              <td>{n(r.asked_person, r.runs)}</td>
              <td>{r.lookups_avg}</td>
              <td>{r.max_flow_calls_avg}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <h3>{H.versusShows}</h3>
      <ul className="small">
        {Object.entries(ev.notes || {}).map(([k, v]) => <li key={k}><b>{k}</b>: {String(v)}</li>)}
      </ul>
      <h3>{H.versusArms}</h3>
      <ul className="small">
        {Object.entries(ev.cases || {}).map(([k, v]) => <li key={k}><b>{k}</b>: {String(v)}</li>)}
        {Object.entries(ev.approaches || {}).map(([k, v]) => <li key={k}><b>{k}</b>: {String(v)}</li>)}
        {(ev.not_run || []).map((x: string) => <li key={x}>{fill(H.versusNotRun, { what: x })}</li>)}
      </ul>
      <span className="small muted">{H.versusSource}</span>
    </div>
  );
}
