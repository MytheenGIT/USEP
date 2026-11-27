import { FormEvent, useState } from "react";
import { usingMock } from "../../shared/api/client";
import { Button, ErrorMessage, Field } from "../../shared/ui";
import { useAuth } from "./AuthContext";

export function LoginPage() {
  const { signIn } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await signIn(username, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <form onSubmit={submit} className="login-card" aria-labelledby="login-h">
        <h1 id="login-h" className="login-title">Universal Semantic Engineering Platform</h1>
        <p className="muted">Sign in as administrator to manage configurations and the knowledge graph.</p>
        <Field label="Username" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required autoFocus />
        <Field label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        {error && <ErrorMessage>{error}</ErrorMessage>}
        <Button variant="primary" type="submit" loading={busy} className="btn-block">{busy ? "Signing in" : "Sign in"}</Button>
        {usingMock && <p className="muted small">Mock API (development only): admin / admin</p>}
      </form>
    </div>
  );
}
