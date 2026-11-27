import { ReactNode, useState } from "react";
import { usingMock } from "../shared/api/client";
import { Badge } from "../shared/ui";
import { useAuth } from "../features/auth/AuthContext";
import { Route } from "./router";
import { Sidebar } from "./Sidebar";
import { ThemeChoice } from "./theme";
import { UserMenu } from "./UserMenu";

const KEY = "usep-sidebar-collapsed";

function readCollapsed(): boolean {
  try { return localStorage.getItem(KEY) === "1"; } catch { return false; }
}

export function AppShell({ route, theme, onSetTheme, children }: { route: Route; theme: ThemeChoice; onSetTheme: (t: ThemeChoice) => void; children: ReactNode }) {
  const { session, signOut } = useAuth();
  const [collapsed, setCollapsed] = useState(readCollapsed);

  const toggleCollapsed = () => {
    setCollapsed((c) => {
      try { localStorage.setItem(KEY, c ? "0" : "1"); } catch { /* preference not saved */ }
      return !c;
    });
  };

  return (
    <div className="shell" data-collapsed={collapsed}>
      <Sidebar route={route} collapsed={collapsed} onToggleCollapsed={toggleCollapsed} />
      <div className="content">
        <header className="topbar">
          {usingMock && <Badge tone="warning" title="Synthetic data, no backend">mock API</Badge>}
          <span className="spacer" />
          <UserMenu username={session?.username ?? ""} theme={theme} onTheme={onSetTheme} onSignOut={() => void signOut()} />
        </header>
        <main id="main">{children}</main>
      </div>
    </div>
  );
}
