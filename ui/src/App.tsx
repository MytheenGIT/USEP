import { useCallback, useEffect, useState } from "react";
import { api, usingMock } from "./api/client";
import { ApiError, Configuration, Session } from "./api/types";
import { ConfigForm } from "./components/ConfigForm";
import { GraphView } from "./pages/GraphView";
import { Login } from "./pages/Login";

// The token lives in memory only: a page reload signs the admin out. No token is written to browser storage.
export function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [configs, setConfigs] = useState<Configuration[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<"configs" | "graph">("configs");
  const [error, setError] = useState("");

  const signOut = useCallback(async () => {
    if (session) await api.logout(session.token).catch(() => undefined);
    setSession(null); setConfigs([]); setSelectedId(null); setView("configs");
  }, [session]);

  const refresh = useCallback(async () => {
    if (!session) return;
    try { setConfigs(await api.listConfigurations(session.token)); setError(""); }
    catch (e) {
      if (e instanceof ApiError && e.status === 401) { setSession(null); return; }
      setError(e instanceof Error ? e.message : "Could not load configurations");
    }
  }, [session]);

  useEffect(() => { void refresh(); }, [refresh]);
  // poll while anything is still processing
  useEffect(() => {
    if (!configs.some((c) => c.status === "submitted" || c.status === "processing")) return;
    const t = setInterval(() => void refresh(), 1000);
    return () => clearInterval(t);
  }, [configs, refresh]);

  if (!session) return <Login onSignedIn={setSession} />;
  const selected = configs.find((c) => c.id === selectedId) ?? null;

  return (
    <div className="app">
      <header className="topbar">
        <strong>USEP Console</strong>
        {usingMock && <span className="badge warn" title="No API yet: synthetic data">mock API</span>}
        <nav aria-label="Main">
          <button className={view === "configs" ? "tab active" : "tab"} onClick={() => setView("configs")}>Configurations</button>
          <button className={view === "graph" ? "tab active" : "tab"} onClick={() => setView("graph")} disabled={!selected}>Knowledge graph</button>
        </nav>
        <span className="spacer" />
        <span className="muted">{selected ? <>Selected: <strong>{selected.name}</strong></> : "No configuration selected"}</span>
        <span className="muted">{session.username}</span>
        <button onClick={() => void signOut()}>Sign out</button>
      </header>
      <main>
        {error && <p role="alert" className="error">{error}</p>}
        {view === "configs" ? (
          <div className="grid2">
            <section aria-labelledby="new-h">
              <h2 id="new-h">New configuration</h2>
              <ConfigForm token={session.token} onCreated={(c) => { setConfigs((x) => [c, ...x]); setSelectedId(c.id); }} />
            </section>
            <section aria-labelledby="list-h">
              <h2 id="list-h">Configurations</h2>
              {configs.length === 0 ? <p className="muted">None yet. Create one to build its knowledge graph.</p> : (
                <ul className="cards">
                  {configs.map((c) => (
                    <li key={c.id} className={c.id === selectedId ? "card selected" : "card"}>
                      <div className="row">
                        <strong>{c.name}</strong>
                        <span className={`badge ${c.status}`}>{c.status}</span>
                      </div>
                      <div className="muted small">{c.git_url}</div>
                      {c.status_detail && <div className="small error">{c.status_detail}</div>}
                      <div className="row">
                        <button onClick={() => setSelectedId(c.id)} disabled={c.id === selectedId}>{c.id === selectedId ? "Selected" : "Select"}</button>
                        <button onClick={() => { setSelectedId(c.id); setView("graph"); }} disabled={c.status !== "ready"}>View graph</button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        ) : selected ? (
          <GraphView token={session.token} config={selected} />
        ) : null}
      </main>
    </div>
  );
}
