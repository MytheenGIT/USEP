import { api } from "../../../shared/api/client";
import { CONNECTOR_META } from "../../../shared/api/connectors";
import { ConnectorDefault } from "../../../shared/api/types";
import { Field, SecretField, Segmented, Switch, TagInput, TextAreaField } from "../../../shared/ui";
import { useSession } from "../../auth/AuthContext";
import { connectorPayload, ConnectorForm } from "../formModel";
import { ConnectorDef, FieldDef } from "./definitions";
import { ConnectorLogo } from "./ConnectorLogo";
import { RepositoryPicker } from "./RepositoryPicker";
import { stepPanelId, stepTabId } from "./ConnectorStepper";

/** The result of the automatic connection check, shown only when something is wrong or while it runs. */
export interface CheckView {
  state: "checking" | "ok" | "bad";
  message: string;
}

interface Props {
  def: ConnectorDef;
  value: ConnectorForm;
  onChange: (next: ConnectorForm) => void;
  errors: Record<string, string>; // keys are field names within this connector
  serverDefault?: ConnectorDefault;
  check?: CheckView;
}

/** Wide inputs take the full row; a URL and an identity share a row when the connector has both. */
const isWide = (f: FieldDef, def: ConnectorDef) =>
  f.kind !== "url" && f.kind !== "text" ? true : f.key === "base_url" ? !def.fields.some((x) => x.key === "email") : f.key !== "email";

/**
 * The form for one connector. No "Test connection" button: the connection is checked by itself when the configuration is
 * submitted, and only a problem is shown here.
 */
export function ConnectorPanel({ def, value, onChange, errors, serverDefault, check }: Props) {
  const { session, guard } = useSession();
  const meta = CONNECTOR_META[def.key];
  const canUseServer = !!serverDefault?.credentials_configured;
  const blocked = serverDefault?.blocked_reason ?? null;
  const sshAvailable = !!serverDefault?.ssh_available;
  const ssh = meta.supportsSsh && value.authMethod === "ssh_key";
  const idBase = `connector-${def.key}`;

  // Editing any field is what chooses this connector: opening its tab to look is not a commitment.
  const patch = (p: Partial<ConnectorForm>) => onChange({ ...value, enabled: true, ...p });
  const setText = (k: "base_url" | "email" | "api_token", v: string) => patch({ text: { ...value.text, [k]: v } });

  const tokenReady = (value.useServerCredentials && canUseServer) || value.text.api_token.trim().length > 0;
  const pickerBlock = ssh ? "Choosing from a list needs a token." : !tokenReady ? "Enter the token first." : undefined;

  const render = (f: FieldDef) => {
    const error = errors[f.key];
    const id = `${idBase}-${f.key}`;
    const usingServer = value.useServerCredentials && !ssh;
    if (f.credential && (usingServer || ssh)) return null;
    if (f.kind === "sshkey") {
      return ssh ? <TextAreaField key={f.key} wide label={f.label} value={value.sshKey} placeholder={f.placeholder} hint={f.hint} error={error} id={id} rows={5} spellCheck={false} autoComplete="off" className="mono-area" onChange={(e) => patch({ sshKey: e.target.value })} /> : null;
    }
    if (f.kind === "lines") {
      return <TextAreaField key={f.key} wide label={f.label} value={value.jql} placeholder={f.placeholder} hint={f.hint} error={error} id={id} rows={3} spellCheck={false} onChange={(e) => patch({ jql: e.target.value })} />;
    }
    if (f.kind === "toggle") {
      if (ssh) return null; // an SSH key cannot list repositories
      return <div key={f.key} className="field field-wide"><Switch label={f.label} hint={f.hint} checked={value.allMemberProjects} id={id} onChange={(allMemberProjects) => patch({ allMemberProjects })} />{error && <span className="field-error">{error}</span>}</div>;
    }
    if (f.kind === "tags") {
      return (
        <div key={f.key} className="field-group field-wide">
          <TagInput wide label={f.label} required={!meta.alternative} values={value.tags} onChange={(tags) => patch({ tags })} placeholder={f.placeholder} hint={f.hint} error={error} id={id} suggestions={f.suggestions} />
          {(def.key === "github" || def.key === "gitlab") && (
            <RepositoryPicker
              noun="repositories" added={value.tags} blockedReason={pickerBlock}
              load={() => guard(api.listRepositories(session.token, def.key, connectorPayload(def.key, value)))}
              onAdd={(paths) => patch({ tags: [...value.tags, ...paths.filter((p) => !value.tags.includes(p))] })}
            />
          )}
        </div>
      );
    }
    if (f.kind === "secret") {
      return <SecretField key={f.key} wide label={f.label} required value={value.text.api_token} placeholder={f.placeholder} hint={f.hint} error={error} id={id} onChange={(e) => setText("api_token", e.target.value)} />;
    }
    if (f.key === "encoded_query") {
      return <Field key={f.key} wide label={f.label} value={value.encodedQuery} placeholder={f.placeholder} hint={f.hint} error={error} id={id} autoComplete="off" spellCheck={false} onChange={(e) => patch({ encodedQuery: e.target.value })} />;
    }
    const field = f.key as "base_url" | "email";
    const serverUrl = field === "base_url" ? serverDefault?.base_url : null;
    const wide = isWide(f, def);
    return (
      <Field
        key={f.key} wide={wide} label={f.label} required={field !== "base_url" || !serverUrl} value={value.text[field]}
        placeholder={serverUrl || f.placeholder} hint={serverUrl ? "Leave empty to use the server's address." : f.hint} error={error} id={id}
        type={f.kind === "url" ? "url" : field === "email" && meta.identityKind === "email" ? "email" : "text"}
        inputMode={f.kind === "url" ? "url" : undefined} autoComplete="off" spellCheck={false}
        onChange={(e) => setText(field, e.target.value)}
      />
    );
  };

  return (
    <div role="tabpanel" id={stepPanelId(def.key)} aria-labelledby={stepTabId(def.key)} className="step-panel">
      <div className="step-panel-head">
        <ConnectorLogo connector={def.key} size={48} />
        <div>
          <h2>{meta.label}</h2>
          <p className="muted">{def.blurb}</p>
        </div>
      </div>

      {blocked && <div className="alert alert-info">{blocked}</div>}

      {meta.supportsSsh && (
        <div className="field field-wide">
          <span className="field-title">Sign in with</span>
          <Segmented
            label={`How ${meta.label} signs in`} value={value.authMethod} onChange={(authMethod) => patch({ authMethod })}
            options={[
              { value: "token", label: "Token" },
              { value: "ssh_key", label: "SSH key", disabled: !sshAvailable, title: sshAvailable ? undefined : "SSH access is not set up on this server" },
            ]}
          />
          {!sshAvailable && <span className="hint">SSH key access needs the server's known hosts to be configured by its operator.</span>}
        </div>
      )}

      {canUseServer && !ssh && (
        <label className="check">
          <input type="checkbox" checked={value.useServerCredentials} onChange={(e) => patch({ useServerCredentials: e.target.checked })} />
          <span>Use the credentials already configured on the server</span>
        </label>
      )}

      <div className="connector-fields">{def.fields.map(render)}</div>

      {check && check.state === "checking" && <div className="check-line" role="status"><span className="spinner" aria-hidden="true" /> Checking the connection…</div>}
      {check && check.state === "bad" && <div className="alert alert-danger" role="alert"><strong>Could not connect.</strong> {check.message}</div>}
    </div>
  );
}
