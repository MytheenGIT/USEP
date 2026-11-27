import { lazy, Suspense } from "react";
import { AuthProvider, useAuth } from "../features/auth/AuthContext";
import { LoginPage } from "../features/auth/LoginPage";
import { ProfilePage } from "../features/auth/ProfilePage";
import { AgentPage } from "../features/agent/AgentPage";
import { OntologyPage } from "../features/ontology/OntologyPage";
import { ProcessingPage } from "../features/configurations/ProcessingPage";
import { ConfigDetailPage } from "../features/configurations/ConfigDetailPage";
import { ConfigurationsProvider } from "../features/configurations/ConfigurationsContext";
import { AddConnectorPage, NewConfigurationPage } from "../features/configurations/NewConfigurationPage";
import { ConfigurationsPage } from "../features/configurations/ConfigurationsPage";
import { EmptyState, Spinner, ToastProvider } from "../shared/ui";
import { AppShell } from "./AppShell";
import { Link, paths, useRoute } from "./router";
import { useTheme } from "./theme";

// The graph page pulls in Cytoscape, the largest dependency, so it loads only when opened.
const GraphPage = lazy(() => import("../features/graph/GraphPage").then((m) => ({ default: m.GraphPage })));

function Routes() {
  const { session } = useAuth();
  const route = useRoute();
  const { theme, setTheme } = useTheme();
  if (!session) return <LoginPage />;
  return (
    <ConfigurationsProvider>
    <AppShell route={route} theme={theme} onSetTheme={setTheme}>
      {route.name === "configurations" && <ConfigurationsPage />}
      {route.name === "new" && <NewConfigurationPage key={route.from ?? "blank"} templateId={route.from} />}
      {route.name === "configuration" && <ConfigDetailPage key={route.id} id={route.id} />}
      {route.name === "add" && <AddConnectorPage key={route.id} id={route.id} />}
      {route.name === "processing" && <ProcessingPage key={route.id} id={route.id} />}
      {route.name === "agent" && <AgentPage key={route.id ?? "latest"} id={route.id} />}
      {route.name === "ontology" && <OntologyPage key={`${route.id ?? "first"}`} id={route.id} concept={route.concept} themeKey={theme} />}
      {route.name === "profile" && <ProfilePage theme={theme} onTheme={setTheme} />}
      {route.name === "graph" && (
        <Suspense fallback={<Spinner label="Loading graph view" />}>
          <GraphPage key={route.id} id={route.id} themeKey={theme} />
        </Suspense>
      )}
      {route.name === "notfound" && (
        <EmptyState title="Page not found" action={<Link to={paths.configurations()}>Go to configurations</Link>} />
      )}
    </AppShell>
    </ConfigurationsProvider>
  );
}

export function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <Routes />
      </AuthProvider>
    </ToastProvider>
  );
}
