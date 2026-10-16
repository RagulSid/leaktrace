import { FormEvent, useState } from "react";
import { api, ApiError } from "../api";
import { ErrorBox } from "../components/ui";
import { copy } from "../copy";

type Kind = keyof typeof copy.report.kinds;
type Sev = keyof typeof copy.report.severities;

export function ReportProblem() {
  const [kinds, setKinds] = useState<Kind[]>([]);
  const [where, setWhere] = useState("");
  const [code, setCode] = useState("");
  const [sev, setSev] = useState<Sev>("small");
  const [error, setError] = useState<unknown>(null);
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const toggle = (k: Kind) => setKinds((ks) => (ks.includes(k) ? ks.filter((x) => x !== k) : [...ks, k]));
  async function send(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!kinds.length || where.trim().length < 2) { setMissing(true); return; }
    setBusy(true);
    try {
      const out = await api<{ code: string }>("/public/reports", {
        method: "POST", body: { kinds, where: where.trim(), severity: sev, asset_code: code.trim() || null },
      });
      window.location.hash = `#/track/${out.code}`;
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  const badCode = error instanceof ApiError && error.code === "unknown_asset_code";
  return (
    <div className="page-narrow">
      <form className="stack" onSubmit={send}>
        <h1>{copy.report.title}</h1>
        <p className="muted">{copy.report.lead}</p>
        <div className="banner">{copy.report.danger}</div>
        <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="label">{copy.report.what}</legend>
          <div className="row">
            {(Object.keys(copy.report.kinds) as Kind[]).map((k) => (
              <button type="button" key={k} className={`chip ${kinds.includes(k) ? "on" : ""}`} aria-pressed={kinds.includes(k)} onClick={() => toggle(k)}>
                {copy.report.kinds[k]}
              </button>
            ))}
          </div>
        </fieldset>
        <label className="field">{copy.report.where}
          <input value={where} placeholder={copy.report.wherePlaceholder} onChange={(e) => setWhere(e.target.value)} />
        </label>
        <label className="field">{copy.report.code}
          <input value={code} placeholder={copy.report.codePlaceholder} onChange={(e) => setCode(e.target.value)} />
        </label>
        <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="label">{copy.report.how}</legend>
          <div className="row">
            {(Object.keys(copy.report.severities) as Sev[]).map((s) => (
              <button type="button" key={s} className={`chip ${sev === s ? "on" : ""}`} aria-pressed={sev === s} onClick={() => setSev(s)}>
                {copy.report.severities[s]}
              </button>
            ))}
          </div>
        </fieldset>
        {missing && <div className="error" role="alert">{copy.report.pickOne}</div>}
        {badCode ? <div className="error" role="alert">{copy.report.badCode}</div> : <ErrorBox error={error} />}
        <button className="btn primary block" type="submit" disabled={busy}>{copy.report.send}</button>
        <p className="muted small">{copy.report.after}</p>
      </form>
    </div>
  );
}
