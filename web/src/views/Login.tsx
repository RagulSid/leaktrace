import { FormEvent, useState } from "react";
import { api, ApiError, login, Who } from "../api";
import { ErrorBox } from "../components/ui";
import { copy } from "../copy";

export function Login({ onDone }: { onDone: (w: Who) => void }) {
  const [user, setUser] = useState("");
  const [pw, setPw] = useState("");
  const [error, setError] = useState<unknown>(null);
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
        <p className="muted small">{copy.login.accounts}</p>
      </form>
    </div>
  );
}
