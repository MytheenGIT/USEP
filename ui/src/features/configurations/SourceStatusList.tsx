import { SourceStatus } from "../../shared/api/types";
import { sourceLabel } from "../../shared/lib/format";
import { ConnectorLogo } from "./connectors/ConnectorLogo";
import { SourceBadge } from "./StatusBadge";

/** What happened to each source for one configuration, with the reason when it did not run. */
export function SourceStatusList({ sources }: { sources: SourceStatus[] }) {
  if (sources.length === 0) return <p className="muted">Waiting for the first source to report.</p>;
  return (
    <ul className="source-list">
      {sources.map((s) => (
        <li key={s.source} className="source-row">
          <div className="source-name">
            <ConnectorLogo connector={s.source} size={26} />
            <strong>{sourceLabel(s.source)}</strong>
            <SourceBadge state={s.state} />
          </div>
          <div className="muted small">
            {s.state === "success" ? `${s.documents_count} document${s.documents_count === 1 ? "" : "s"} read` : (s.detail ?? "")}
          </div>
        </li>
      ))}
    </ul>
  );
}
