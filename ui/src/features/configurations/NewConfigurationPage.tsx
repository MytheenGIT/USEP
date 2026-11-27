import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, navigate, paths } from "../../app/router";
import { api } from "../../shared/api/client";
import { CONNECTOR_KEYS, CONNECTOR_META } from "../../shared/api/connectors";
import { ApiError, ConnectionCheck, Configuration, ConnectorKey } from "../../shared/api/types";
import { useAsync } from "../../shared/hooks/useAsync";
import { Button, Card, ErrorMessage, Field, Spinner, useToast } from "../../shared/ui";
import { useSession } from "../auth/AuthContext";
import { CheckView, ConnectorPanel } from "./connectors/ConnectorPanel";
import { ConnectorStepper, StepInfo } from "./connectors/ConnectorStepper";
import { CONNECTOR_DEFS } from "./connectors/definitions";
import { useConfigurationList } from "./ConfigurationsContext";
import { addableConnectors, connectorPayload, connectorState, emptyForm, FormState, formFromConfiguration, selectedCount, toPayload, validateForm } from "./formModel";
import { useConfiguration } from "./hooks";

const hasErrorsFor = (errors: Record<string, string>, key: string) => Object.keys(errors).some((k) => k.startsWith(`${key}.`));
const withoutPrefix = (errors: Record<string, string>, key: string) => Object.fromEntries(Object.entries(errors).filter(([k]) => !k.startsWith(`${key}.`)));
const onlyPrefix = (errors: Record<string, string>, key: string) => Object.fromEntries(Object.entries(errors).filter(([k]) => k.startsWith(`${key}.`)));

/**
 * Choose the connectors you have and fill each in, in any order: there are no steps. One button does the rest: it checks
 * every connection by itself, creates the configuration, and opens the processing page. None is mandatory.
 * `templateId` pre-fills from an existing one (tokens start empty).
 */
export function NewConfigurationPage({ templateId }: { templateId?: string }) {
  return <ConfigurationForm templateId={templateId} />;
}

/** The same form, to add connectors to a configuration that is ready. Only the new ones are read; the graph is rebuilt with everything. */
export function AddConnectorPage({ id }: { id: string }) {
  const { config, error, refresh } = useConfiguration(id);
  if (error && !config) return <ErrorMessage onRetry={() => void refresh()}>{error.message}</ErrorMessage>;
  if (!config) return <Spinner label="Loading configuration" />;
  return <ConfigurationForm addTo={config} />;
}

function ConfigurationForm({ templateId, addTo }: { templateId?: string; addTo?: Configuration }) {
  const { session, guard } = useSession();
  const { items, add, refresh: refreshList } = useConfigurationList();
  const toast = useToast();
  const defaults = useAsync(() => guard(api.connectorDefaults(session.token)), [session.token]);
  const template = useMemo<Configuration | undefined>(() => items?.find((c) => c.id === templateId), [items, templateId]);
  // Starts filled in immediately except when copying a template: that has to wait for the list to load.
  const [form, setForm] = useState<FormState | null>(() => (addTo ? { ...emptyForm(), name: addTo.name } : templateId ? null : emptyForm()));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [checks, setChecks] = useState<Partial<Record<ConnectorKey, CheckView>>>({});
  const [formError, setFormError] = useState("");
  const [phase, setPhase] = useState<"idle" | "checking" | "creating">("idle");
  // When adding, only the connectors the configuration does not use yet are offered.
  const offered = addTo ? addableConnectors(addTo) : CONNECTOR_KEYS;
  const tabs = CONNECTOR_DEFS.filter((d) => offered.includes(d.key));
  const [activeKey, setActiveKey] = useState<ConnectorKey>(tabs[0]?.key ?? CONNECTOR_DEFS[0].key);

  // Once the template's own configuration has loaded, start the form from it (tokens stay empty).
  useEffect(() => {
    if (!templateId || form || !items) return;
    setForm(template ? formFromConfiguration(template) : emptyForm());
  }, [templateId, items, template, form]);

  if (defaults.loading && !defaults.data) return <Spinner label="Loading" />;
  if (!form) return <Spinner label="Loading configuration" />;
  const current = form;
  const defs = defaults.data ?? {};
  const active = tabs.find((d) => d.key === activeKey) ?? tabs[0] ?? CONNECTOR_DEFS[0];
  const busy = phase !== "idle";

  const steps: StepInfo[] = tabs.map((d) => {
    const check = checks[d.key];
    const base = connectorState(d.key, current.connectors[d.key], defs);
    const state = base === "off" ? "off" : check?.state === "checking" ? "checking" : check?.state === "bad" ? "failed" : check?.state === "ok" ? "connected" : base;
    return { key: d.key, label: CONNECTOR_META[d.key].label, state, hasError: hasErrorsFor(errors, d.key) };
  });

  const changeConnector = (key: ConnectorKey, next: FormState["connectors"][ConnectorKey]) => {
    setForm({ ...current, connectors: { ...current.connectors, [key]: next } });
    setErrors((prev) => withoutPrefix(prev, key)); // the old messages no longer describe what is typed
    setChecks((prev) => ({ ...prev, [key]: undefined })); // and a result for different values is out of date
    setFormError("");
  };

  /** Show errors for the first connector that has them and open its tab. Returns true when there were any. */
  function showErrors(all: Record<string, string>): boolean {
    const keys = Object.keys(all);
    if (!keys.length) return false;
    setErrors(all);
    const firstBad = tabs.find((d) => hasErrorsFor(all, d.key));
    if (firstBad) setActiveKey(firstBad.key);
    const names = tabs.filter((d) => hasErrorsFor(all, d.key)).map((d) => CONNECTOR_META[d.key].label);
    setFormError(all.connectors ?? (names.length ? `Needs attention: ${names.join(", ")}.` : "Check the highlighted field."));
    return true;
  }

  /** Check every switched-on connection at once, without the admin pressing anything. */
  async function checkConnections(f: FormState): Promise<boolean> {
    const keys = CONNECTOR_KEYS.filter((k) => f.connectors[k].enabled);
    setChecks(Object.fromEntries(keys.map((k) => [k, { state: "checking", message: "" } as CheckView])));
    const results = await Promise.all(keys.map(async (k): Promise<[ConnectorKey, ConnectionCheck]> => {
      try {
        return [k, await guard(api.testConnector(session.token, k, connectorPayload(k, f.connectors[k])))];
      } catch (e) {
        if (e instanceof ApiError && e.fields) setErrors((prev) => ({ ...prev, ...e.fields }));
        return [k, { ok: false, message: e instanceof Error ? e.message : "The check could not run" }];
      }
    }));
    setChecks(Object.fromEntries(results.map(([k, r]) => [k, { state: r.ok ? "ok" : "bad", message: r.message } as CheckView])));
    const failed = results.filter(([, r]) => !r.ok).map(([k]) => k);
    if (failed.length) {
      setActiveKey(failed[0]);
      setFormError(`Could not connect to ${failed.map((k) => CONNECTOR_META[k].label).join(", ")}. Fix it and try again.`);
    }
    return failed.length === 0;
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setFormError("");
    if (showErrors(validateForm(current!, defs))) return;
    setPhase("checking");
    try {
      if (!(await checkConnections(current!))) return;
      setPhase("creating");
      if (addTo) {
        const added = Object.fromEntries(Object.entries(toPayload(current!).connectors).filter(([, c]) => c?.enabled));
        await guard(api.addConnectors(session.token, addTo.id, added));
        setForm(emptyForm()); // drops every typed token from memory
        await refreshList();
        toast.show(`Adding to “${addTo.name}”`, "success");
        navigate(paths.processing(addTo.id));
      } else {
        const created = await guard(api.createConfiguration(session.token, toPayload(current!)));
        add(created);
        setForm(emptyForm()); // drops every typed token from memory
        toast.show(`“${created.name}” submitted for processing`, "success");
        navigate(paths.processing(created.id));
      }
    } catch (err) {
      if (err instanceof ApiError && err.fields) showErrors(err.fields);
      else setFormError(err instanceof Error ? err.message : "Could not submit");
    } finally {
      setPhase("idle");
    }
  }

  const selected = selectedCount(current);
  if (addTo && tabs.length === 0) {
    return (
      <>
        <nav aria-label="Breadcrumb" className="crumbs"><Link to={paths.configurations()}>Connectors</Link> / <Link to={paths.configuration(addTo.id)}>{addTo.name}</Link> / <span>Add a connector</span></nav>
        <ErrorMessage>Every connector is already part of this configuration.</ErrorMessage>
      </>
    );
  }
  return (
    <>
      {addTo ? (
        <nav aria-label="Breadcrumb" className="crumbs"><Link to={paths.configurations()}>Connectors</Link> / <Link to={paths.configuration(addTo.id)}>{addTo.name}</Link> / <span>Add a connector</span></nav>
      ) : (
        <nav aria-label="Breadcrumb" className="crumbs"><Link to={paths.configurations()}>Connectors</Link> / <span>New</span></nav>
      )}
      <div className="page-head">
        <div>
          <h1>{addTo ? `Add a connector to “${addTo.name}”` : templateId ? "Edit and resubmit" : "New Connection"}</h1>
          <p className="muted">
            {addTo
              ? "The connectors already in this configuration are kept and are not read again, so you do not need their tokens. Only what you add now is read, and the knowledge graph is rebuilt with everything. Tokens go to the server for this run only and are never stored."
              : "Switch on the connectors you have, in any order. None is mandatory, but one you switch on must be filled in. Connections are checked for you when you create the configuration. Tokens go to the server for this run only and are never stored."}
          </p>
        </div>
      </div>
      {templateId && items && !template && <ErrorMessage>That configuration was not found, so the form starts empty.</ErrorMessage>}
      {defaults.error && <ErrorMessage onRetry={defaults.reload}>{defaults.error.message}</ErrorMessage>}

      <form onSubmit={submit} noValidate className="new-config">
        {!addTo && <Card>
          <Field label="Configuration name" required value={current.name} maxLength={80} placeholder="Payments platform" autoComplete="off" error={errors.name} disabled={busy}
            onChange={(e) => { setForm({ ...current, name: e.target.value }); setErrors(({ name: _n, ...rest }) => rest); }} />
        </Card>}

        <div className="card wizard">
          <ConnectorStepper steps={steps} activeKey={active.key} onSelect={(key) => setActiveKey(key as ConnectorKey)} />
          <fieldset className="panel-fieldset" disabled={busy}>
            <ConnectorPanel
              key={active.key} def={active} value={current.connectors[active.key]} serverDefault={defs[active.key]} check={checks[active.key]}
              errors={Object.fromEntries(Object.entries(onlyPrefix(errors, active.key)).map(([k, v]) => [k.slice(active.key.length + 1), v]))}
              onChange={(v) => changeConnector(active.key, v)}
            />
          </fieldset>
          <div className="wizard-foot">
            <span className="muted progress">{selected === 0 ? "No connector switched on yet" : `${selected} connector${selected === 1 ? "" : "s"} switched on`}</span>
            {formError && <span role="alert" className="field-error">{formError}</span>}
            <span className="spacer" />
            <Button onClick={() => navigate(addTo ? paths.configuration(addTo.id) : paths.configurations())} disabled={busy}>Cancel</Button>
            <Button variant="primary" type="submit" loading={busy}>
              {phase === "checking" ? "Checking connections" : phase === "creating" ? (addTo ? "Adding" : "Creating") : addTo ? "Add" : "Create"}
            </Button>
          </div>
        </div>
      </form>
    </>
  );
}
