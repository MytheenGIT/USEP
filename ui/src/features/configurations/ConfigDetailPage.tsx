import { Link, navigate, paths } from "../../app/router";
import { ConnectorSummary } from "../../shared/api/types";
import { formatDateTime, sourceLabel } from "../../shared/lib/format";
import { Badge, Button, Card, ErrorMessage, Spinner } from "../../shared/ui";
import { ConnectorLogo } from "./connectors/ConnectorLogo";
import { useConfiguration, isPending } from "./hooks";
import { SourceStatusList } from "./SourceStatusList";
import { StatusBadge } from "./StatusBadge";

const CREDENTIALS: Record<ConnectorSummary["credentials"], string> = {
  provided: "Token entered for this run (not stored)",
  server: "Server credentials",
  none: "No credentials",
};

export function ConfigDetailPage({ id }: { id: string }) {
  const { config, error, refresh } = useConfiguration(id);

  if (error && !config) {
    return (
      <>
        <ErrorMessage onRetry={() => void refresh()}>{error.message}</ErrorMessage>
        <p><Link to={paths.configurations()}>Back to configurations</Link></p>
      </>
    );
  }
  if (!config) return <Spinner label="Loading configuration" />;

  const enabled = Object.entries(config.connectors).filter(([, s]) => s.enabled);

  return (
    <>
      <nav aria-label="Breadcrumb" className="crumbs"><Link to={paths.configurations()}>Configurations</Link> / <span>{config.name}</span></nav>
      <div className="page-head">
        <div>
          <h1>{config.name} <StatusBadge status={config.status} /></h1>
          <p className="muted">Created {formatDateTime(config.created_at)} by {config.created_by}</p>
        </div>
        <div className="row-gap">
          <Button onClick={() => navigate(paths.addConnectors(config.id))} disabled={config.status !== "ready"} title={config.status === "ready" ? undefined : "A connector can be added once the configuration is ready"}>Add a connector</Button>
          <Button onClick={() => navigate(paths.newConfiguration(config.id))}>Edit and resubmit</Button>
          <Button variant="primary" onClick={() => navigate(paths.graph(config.id))} disabled={config.status !== "ready"}>View knowledge graph</Button>
        </div>
      </div>

      {isPending(config) && <div className="alert alert-info" role="status"><span className="spinner" aria-hidden="true" /> Reading sources. This page updates by itself.</div>}
      {config.status === "failed" && <ErrorMessage>{config.status_detail ?? "Processing failed."}</ErrorMessage>}
      {config.status === "ready" && config.status_detail && <div className="alert alert-warning" role="status">{config.status_detail}</div>}

      <div className="grid-2">
        <Card title="Sources"><SourceStatusList sources={config.sources ?? []} /><p className="muted small">Only the connectors you switched on are read.</p></Card>
        <Card title="Connectors">
          <ul className="source-list">
            {enabled.map(([key, s]) => (
              <li key={key} className="source-row">
                <div className="source-name"><ConnectorLogo connector={key} size={26} /><strong>{sourceLabel(key)}</strong><Badge>{CREDENTIALS[s.credentials]}</Badge></div>
                {s.base_url && <div className="mono">{s.base_url}</div>}
                {s.email && <div className="muted small">{s.email}</div>}
                <div className="chips">
                  {s.targets.map((t) => <span key={t} className="tag tag-static">{t}</span>)}
                  {s.all_member_projects && <span className="tag tag-static">every repository you are a member of</span>}
                </div>
                {(s.jql_queries ?? []).length > 0 && <ul className="jql-list">{s.jql_queries.map((q) => <li key={q} className="mono small">{q}</li>)}</ul>}
              </li>
            ))}
          </ul>
          <p className="muted small">Tokens are not kept after a run. Use Edit and resubmit to run again with fresh ones.</p>
        </Card>
      </div>
    </>
  );
}
