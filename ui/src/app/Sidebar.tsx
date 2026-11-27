import { useMemo, useState } from "react";
import { useAuth } from "../features/auth/AuthContext";
import { useConfigurationList } from "../features/configurations/ConfigurationsContext";
import { BrandLogo, Icon, IconName } from "../shared/ui";
import { Link, paths, Route } from "./router";

const MAX_LISTED = 8;
const DOT: Record<string, string> = { ready: "dot-success", processing: "dot-warning", submitted: "dot-info", failed: "dot-danger" };

interface Props {
  route: Route;
  collapsed: boolean;
  onToggleCollapsed: () => void;
}

/**
 * Collapsible left panel. Collapsed it is a 64px rail of icons; tapping a group's icon opens the panel on it.
 * Groups: Configurations (each saved one), Knowledge graphs (each one that is ready), Ask the agent. At the bottom is
 * the signed-in admin with a link to the profile and a way to sign out.
 */
export function Sidebar({ route, collapsed, onToggleCollapsed }: Props) {
  const { items } = useConfigurationList();
  const { session, signOut } = useAuth();
  const [open, setOpen] = useState<{ configs: boolean; graphs: boolean }>({ configs: true, graphs: true });
  const ready = useMemo(() => (items ?? []).filter((c) => c.status === "ready"), [items]);
  const activeId = route.name === "configuration" || route.name === "graph" || route.name === "processing" || (route.name === "agent" && route.id) ? route.id : undefined;
  const inConfigs = route.name === "configurations" || route.name === "new" || route.name === "configuration" || route.name === "processing";
  const username = session?.username ?? "";

  const toggle = (group: "configs" | "graphs") => {
    if (collapsed) { onToggleCollapsed(); setOpen((o) => ({ ...o, [group]: true })); }
    else setOpen((o) => ({ ...o, [group]: !o[group] }));
  };

  const groupButton = (group: "configs" | "graphs", icon: IconName, label: string, active: boolean, controls: string) => (
    <button className={active ? "nav-item active" : "nav-item"} onClick={() => toggle(group)} aria-expanded={!collapsed && open[group]} aria-controls={controls} title={label}>
      <Icon name={icon} />
      <span className="side-label nav-text">{label}</span>
      <span className="side-label"><Icon name={open[group] ? "chevronDown" : "chevronRight"} size={16} /></span>
    </button>
  );

  return (
    <aside className="sidebar" aria-label="Sidebar">
      <div className="sidebar-top">
        <div className="sidebar-brand">
          <span className="rail-logo"><BrandLogo brand="ust" size={34} /></span>
          <span className="side-label brand-row"><BrandLogo brand="ust" size={30} /><span className="product-wrap"><span className="product">Universal Semantic Engineering Platform</span></span></span>
        </div>
        <button className="icon-btn side-collapse" onClick={onToggleCollapsed} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} aria-expanded={!collapsed}>
          <Icon name={collapsed ? "chevronRight" : "chevronLeft"} />
        </button>
      </div>

      <nav aria-label="Main" className="side-nav">
        {groupButton("configs", "layers", "Connectors", inConfigs, "side-configs")}
        {!collapsed && open.configs && (
          <ul id="side-configs" className="sub-list">
            <li>
              <Link to={paths.newConfiguration()} className={route.name === "new" ? "sub-item active" : "sub-item"}>
                <Icon name="plus" size={15} /> New connector
              </Link>
            </li>
            {items === null && <li className="sub-note muted small">Loading…</li>}
            {items?.length === 0 && <li className="sub-note muted small">None yet</li>}
            {items?.slice(0, MAX_LISTED).map((c) => (
              <li key={c.id}>
                <Link to={c.status === "ready" || c.status === "failed" ? paths.configuration(c.id) : paths.processing(c.id)} className={c.id === activeId && route.name !== "graph" && route.name !== "agent" ? "sub-item active" : "sub-item"} title={`${c.name} (${c.status})`}>
                  <span className={`dot ${DOT[c.status] ?? ""}`} aria-hidden="true" />
                  <span className="sub-name">{c.name}</span>
                  <span className="sr-only"> ({c.status})</span>
                </Link>
              </li>
            ))}
            {items && items.length > MAX_LISTED && <li><Link to={paths.configurations()} className="sub-item muted">View all {items.length}</Link></li>}
          </ul>
        )}

        {groupButton("graphs", "graph", "Knowledge graphs", route.name === "graph", "side-graphs")}
        {!collapsed && open.graphs && (
          <ul id="side-graphs" className="sub-list">
            {items === null && <li className="sub-note muted small">Loading…</li>}
            {items && ready.length === 0 && <li className="sub-note muted small">One appears here when a configuration is ready</li>}
            {ready.slice(0, MAX_LISTED).map((c) => (
              <li key={c.id}>
                <Link to={paths.graph(c.id)} className={route.name === "graph" && c.id === activeId ? "sub-item active" : "sub-item"} title={`Knowledge graph of ${c.name}`}>
                  <Icon name="graph" size={15} />
                  <span className="sub-name">{c.name}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}

        <Link to={paths.ontology(items?.[0]?.id)} className={route.name === "ontology" ? "nav-item active" : "nav-item"} title="Ontology">
          <Icon name="book" />
          <span className="side-label nav-text">Ontology</span>
        </Link>

        <Link to={paths.agent(ready[0]?.id)} className={route.name === "agent" ? "nav-item active" : "nav-item"} title="Ask the agent">
          <Icon name="chat" />
          <span className="side-label nav-text">Ask the agent</span>
        </Link>
      </nav>

      <div className="sidebar-profile">
        <Link to={paths.profile()} className={route.name === "profile" ? "profile-link active" : "profile-link"} title="Profile">
          <BrandLogo brand="kf" size={34} />
          <span className="side-label profile-text">
            <span className="profile-name">{username}</span>
            <span className="muted small">Administrator</span>
          </span>
        </Link>
        <button className="icon-btn" onClick={() => void signOut()} aria-label="Sign out" title="Sign out"><Icon name="logout" /></button>
      </div>
    </aside>
  );
}
