import { FormEvent, useState } from "react";
import { api, usingMock } from "../api/client";
import { Session } from "../api/types";

export function Login({ onSignedIn }: { onSignedIn: (s: Session) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError("");
    try { onSignedIn(await api.login(username.trim(), password)); }
    catch (err) { setError(err instanceof Error ? err.message : "Sign-in failed"); setPassword(""); }
    finally { setBusy(false); }
  }

  return (
    <div className="login">
      <form onSubmit={submit} aria-labelledby="login-h">
        <h1 id="login-h">USEP Console</h1>
        <p className="muted">Administrator sign-in</p>
        <label>Username<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required autoFocus /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>
        {error && <p role="alert" className="error">{error}</p>}
        <button className="primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        {usingMock && <p className="muted small">Mock API (development only): admin / admin</p>}
      </form>
    </div>
  );
}
