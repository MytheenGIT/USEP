import { Link, navigate, paths } from "../../app/router";
import { Configuration } from "../../shared/api/types";
import { sourceLabel, timeAgo } from "../../shared/lib/format";
import { Button, Card, EmptyState, ErrorMessage, Spinner } from "../../shared/ui";
import { ConnectorLogo } from "./connectors/ConnectorLogo";
import { useConfigurationList } from "./ConfigurationsContext";
import { SourceBadge, StatusBadge } from "./StatusBadge";

const enabledLabels = (c: Configuration) =>
  Object.entries(c.connectors).filter(([, s]) => s.enabled).map(([k]) => sourceLabel(k)).join(" · ");

function ConfigRow({ c }: { c: Configuration }) {
  return (
    <li className="list-item">
      <div className="list-main">
        <Link to={paths.configuration(c.id)} className="list-title">{c.name}</Link>
        <div className="muted small">{enabledLabels(c)} · created {timeAgo(c.created_at)} by {c.created_by}</div>
        {c.status_detail && <div className="small detail-text">{c.status_detail}</div>}
      </div>
      <div className="chips" aria-label="Sources">
        {(c.sources ?? []).map((s) => (
          <span key={s.source} className="chip-static" title={s.detail ?? ""}><ConnectorLogo connector={s.source} size={18} />{sourceLabel(s.source)} <SourceBadge state={s.state} /></span>
        ))}
      </div>
      <StatusBadge status={c.status} />
      <Button onClick={() => navigate(paths.graph(c.id))} disabled={c.status !== "ready"}>View graph</Button>
    </li>
  );
}

export function ConfigurationsPage() {
  const { items, error, refresh } = useConfigurationList();
  const create = () => navigate(paths.newConfiguration());

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Connectors</h1>
          <p className="muted">Each connector configuration reads its sources and builds a knowledge graph.</p>
        </div>
        <Button variant="primary" onClick={create}>New connector</Button>
      </div>

      {error && !items && <ErrorMessage onRetry={() => void refresh()}>{error.message}</ErrorMessage>}
      {!items && !error && <Spinner label="Loading connectors" />}
      {items && (
        <Card>
          {items.length === 0 ? (
            <EmptyState title="No connectors yet" action={<Button variant="primary" onClick={create}>Create the first one</Button>}>
              Connect Jira, Confluence, GitLab or Figma to build a knowledge graph.
            </EmptyState>
          ) : (
            <ul className="list">{items.map((c) => <ConfigRow key={c.id} c={c} />)}</ul>
          )}
        </Card>
      )}
    </>
  );
}
