import { FormEvent, useState } from "react";
import { api, ApiError, login, Who } from "../api";
import { ErrorBox, useLoad } from "../components/ui";
import { copy, fill } from "../copy";

type Info = { demo_tenant: string; practice_sign_in: { accounts: string[]; password: string } | null };

export function Login({ onDone }: { onDone: (w: Who) => void }) {
  const [user, setUser] = useState("");
  const [pw, setPw] = useState("");
  const [error, setError] = useState<unknown>(null);
  const info = useLoad<Info>(() => api("/public/info"), []);
  const judges = info.data?.practice_sign_in;
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const info = await api<{ demo_tenant: string }>("/public/info");
      onDone(await login(info.demo_tenant, user.trim(), pw));
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? new Error(copy.errors.signInFailed) : err);
    }
  }
  return (
    <div className="page-narrow">
      <form className="stack" onSubmit={submit}>
        <h1>{copy.login.title}</h1>
        <p className="muted">{copy.login.lead}</p>
        <label className="field">{copy.login.user}<input autoComplete="username" value={user} onChange={(e) => setUser(e.target.value)} /></label>
        <label className="field">{copy.login.password}<input type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} /></label>
        {error instanceof Error && !(error instanceof ApiError) ? <div className="error" role="alert">{error.message}</div> : <ErrorBox error={error} />}
        <button className="btn primary block" type="submit" disabled={!user || !pw}>{copy.login.submit}</button>
        {judges ? <p className="card small">{fill(copy.login.judges, { accounts: judges.accounts.join(", "), password: judges.password })}</p>
          : <p className="muted small">{copy.login.accounts}</p>}
      </form>
    </div>
  );
}
