import { useEffect } from "react";
import { Link, navigate, paths } from "../../app/router";
import { ConnectorKey, Configuration } from "../../shared/api/types";
import { sourceLabel } from "../../shared/lib/format";
import { Button, ErrorMessage, Icon, Spinner } from "../../shared/ui";
import { ConnectorLogo } from "./connectors/ConnectorLogo";
import { isPending, useConfiguration } from "./hooks";

/** What the service is doing for each connector while it reads it, in plain words. */
const DOING: Record<ConnectorKey, string> = {
  ado: "Reading work items, pull requests and repositories from Azure DevOps",
  jira: "Reading issues, comments and history from Jira",
  confluence: "Reading pages and version history from Confluence",
  gitlab: "Reading merge requests, commits and diffs from GitLab",
  github: "Reading pull requests, reviews and changed files from GitHub",
  servicenow: "Reading incidents, changes and problems from ServiceNow",
  figma: "Reading pages, frames and text from Figma",
};

const READY_DELAY_MS = 1400;

function rows(config: Configuration) {
  return Object.entries(config.connectors).filter(([, c]) => c.enabled).map(([key]) => {
    const result = config.sources?.find((s) => s.source === key);
    return { key, state: result?.state ?? "pending", count: result?.documents_count ?? 0, detail: result?.detail };
  });
}

/**
 * Shown right after a configuration is created. The sources are read in the background; this page says what is happening
 * with a spinner, then opens the knowledge graph by itself as soon as it is ready.
 */
export function ProcessingPage({ id }: { id: string }) {
  const { config, error, refresh } = useConfiguration(id);
  const ready = config?.status === "ready";
  const note = ready ? config?.status_detail : null; // ready, but a connector could not be added: say so before moving on

  useEffect(() => {
    if (!ready || note) return;
    const timer = window.setTimeout(() => navigate(paths.graph(id)), READY_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [ready, note, id]);

  if (error && !config) return <ErrorMessage onRetry={() => void refresh()}>{error.message}</ErrorMessage>;
  if (!config) return <Spinner label="Loading" />;

  const items = rows(config);
  const failed = config.status === "failed";
  const title = ready ? (note ? "Done, with one thing to know" : "Your knowledge graph is ready") : failed ? "Some sources could not be read" : "Building your knowledge graph";
  const subtitle = ready
    ? note ?? "Opening it now."
    : failed
      ? config.status_detail ?? "Processing failed."
      : "This usually takes a minute. You can leave this page; the configuration keeps processing.";

  return (
    <div className="processing" role="status" aria-live="polite">
      <div className="processing-card">
        <div className={ready && !note ? "processing-mark processing-done" : failed ? "processing-mark processing-failed" : "processing-mark"}>
          {ready ? <Icon name="check" size={34} /> : failed ? <span aria-hidden="true">!</span> : <span className="spinner spinner-lg" aria-hidden="true" />}
        </div>
        <h1>{title}</h1>
        <p className="muted">{subtitle}</p>
        <p className="processing-name">{config.name}</p>

        <ul className="processing-list">
          {items.map((r) => (
            <li key={r.key} className={`processing-row processing-${r.state}`}>
              <ConnectorLogo connector={r.key} size={30} />
              <div className="processing-text">
                <strong>{sourceLabel(r.key)}</strong>
                <span className="muted small">
                  {r.state === "success" ? `${r.count} item${r.count === 1 ? "" : "s"} read` : r.state === "pending" ? DOING[r.key as ConnectorKey] : r.detail ?? "Could not be read"}
                </span>
              </div>
              <span className="processing-icon" aria-label={r.state}>
                {r.state === "pending" && <span className="spinner" aria-hidden="true" />}
                {r.state === "success" && <Icon name="check" size={18} />}
                {(r.state === "failed" || r.state === "skipped") && <span aria-hidden="true">!</span>}
              </span>
            </li>
          ))}
          {isPending(config) && (
            <li className="processing-row processing-pending">
              <span className="processing-step"><Icon name="graph" size={18} /></span>
              <div className="processing-text"><strong>Knowledge graph</strong><span className="muted small">Linking what was found: requirements, changes, incidents, decisions</span></div>
              <span className="processing-icon"><span className="spinner" aria-hidden="true" /></span>
            </li>
          )}
        </ul>

        <div className="processing-actions">
          {ready && <Button variant="primary" onClick={() => navigate(paths.graph(id))}>Open the knowledge graph</Button>}
          {failed && <Button variant="primary" onClick={() => navigate(paths.newConfiguration(id))}>Edit and resubmit</Button>}
          <Link to={paths.configuration(id)} className="btn btn-ghost">View details</Link>
        </div>
      </div>
    </div>
  );
}
