import { useMemo, useState } from "react";
import { RepositoryChoice, RepositoryList } from "../../../shared/api/types";
import { Button, Icon, Spinner } from "../../../shared/ui";

interface Props {
  /** What the admin is choosing from: "repositories". */
  noun: string;
  /** Fetches what the entered token can reach. Called each time the picker opens. */
  load: () => Promise<RepositoryList>;
  /** Already in the field. They are shown as added and cannot be ticked twice. */
  added: string[];
  onAdd: (paths: string[]) => void;
  /** When set, the button is disabled and this says why (usually: enter the token first). */
  blockedReason?: string;
}

/** "Choose from my repositories": list what the token can reach, search it, tick several, add them to the field in one go. */
export function RepositoryPicker({ noun, load, added, onAdd, blockedReason }: Props) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [list, setList] = useState<RepositoryList | null>(null);
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());

  const addedSet = useMemo(() => new Set(added.map((a) => a.toLowerCase())), [added]);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (list?.repositories ?? []).filter((r) => !q || r.path.toLowerCase().includes(q) || r.name.toLowerCase().includes(q));
  }, [list, query]);
  const tickable = shown.filter((r) => !addedSet.has(r.path.toLowerCase()));

  async function show() {
    setOpen(true);
    setLoading(true);
    setError("");
    setPicked(new Set());
    try {
      setList(await load());
    } catch (e) {
      setList(null);
      setError(e instanceof Error ? e.message : `Could not list ${noun}`);
    } finally {
      setLoading(false);
    }
  }

  const toggle = (r: RepositoryChoice) =>
    setPicked((prev) => { const next = new Set(prev); if (next.has(r.path)) next.delete(r.path); else next.add(r.path); return next; });
  const selectAllShown = () => setPicked((prev) => new Set([...prev, ...tickable.map((r) => r.path)]));

  function commit() {
    onAdd([...picked]);
    setPicked(new Set());
    setOpen(false);
  }

  return (
    <div className="field field-wide repo-picker">
      <div className="repo-picker-bar">
        <Button onClick={() => (open ? setOpen(false) : void show())} disabled={!!blockedReason} aria-expanded={open}>
          <Icon name="search" size={16} /> {open ? "Close the list" : `Choose from my ${noun}`}
        </Button>
        {blockedReason && <span className="hint">{blockedReason}</span>}
      </div>

      {open && (
        <div className="repo-panel" role="group" aria-label={`Choose ${noun}`}>
          {loading && <div className="repo-state"><Spinner label={`Loading your ${noun}`} /></div>}
          {error && <div className="alert alert-danger" role="alert">{error}</div>}
          {list && !loading && (
            <>
              <div className="repo-tools">
                <input aria-label={`Search ${noun}`} placeholder={`Search ${list.repositories.length} ${noun}`} value={query} onChange={(e) => setQuery(e.target.value)} />
                <Button onClick={selectAllShown} disabled={tickable.length === 0}>Select all shown</Button>
                <Button onClick={() => setPicked(new Set())} disabled={picked.size === 0}>Clear</Button>
              </div>
              <ul className="repo-list">
                {shown.length === 0 && <li className="muted small repo-empty">Nothing matches.</li>}
                {shown.map((r) => {
                  const already = addedSet.has(r.path.toLowerCase());
                  return (
                    <li key={r.path}>
                      <label className={already ? "repo-row repo-added" : "repo-row"}>
                        <input type="checkbox" checked={already || picked.has(r.path)} disabled={already} onChange={() => toggle(r)} />
                        <span className="repo-path">{r.path}</span>
                        {r.visibility && <span className="badge repo-vis">{r.visibility}</span>}
                        {already && <span className="muted small">added</span>}
                      </label>
                    </li>
                  );
                })}
              </ul>
              {list.truncated && <p className="muted small">Only the first {list.repositories.length} are shown. Add the others by link below.</p>}
              <div className="repo-foot">
                <span className="muted small">{picked.size} selected</span>
                <span className="spacer" />
                <Button variant="primary" onClick={commit} disabled={picked.size === 0}>Add {picked.size || ""} selected</Button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
