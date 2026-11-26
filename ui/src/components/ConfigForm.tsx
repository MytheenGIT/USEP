import { FormEvent, useState } from "react";
import { api } from "../api/client";
import { ApiError, ConfigInput, Configuration } from "../api/types";
import { emptyConfig, FIELDS, FieldErrors, validateConfig } from "../validation";

export function ConfigForm({ token, onCreated }: { token: string; onCreated: (c: Configuration) => void }) {
  const [values, setValues] = useState<ConfigInput>(emptyConfig());
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setFormError("");
    const local = validateConfig(values);
    setErrors(local);
    if (Object.keys(local).length) return;
    setBusy(true);
    try {
      const trimmed = Object.fromEntries(Object.entries(values).map(([k, v]) => [k, v.trim()])) as unknown as ConfigInput;
      onCreated(await api.createConfiguration(token, trimmed));
      setValues(emptyConfig());
    } catch (err) {
      if (err instanceof ApiError && err.fields) setErrors(err.fields);
      setFormError(err instanceof Error ? err.message : "Could not submit");
    } finally { setBusy(false); }
  }

  return (
    <form onSubmit={submit} noValidate>
      {FIELDS.map((f) => (
        <label key={f.key}>
          {f.label}{f.required ? <span aria-hidden="true"> *</span> : <span className="muted"> (optional)</span>}
          <input
            value={values[f.key]} placeholder={f.placeholder} maxLength={f.key === "name" ? 80 : 2048}
            type="text" inputMode={f.key === "name" ? "text" : "url"}
            aria-invalid={!!errors[f.key]} aria-describedby={errors[f.key] ? `${f.key}-err` : undefined}
            onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
          />
          {errors[f.key] && <span id={`${f.key}-err`} className="error small">{errors[f.key]}</span>}
        </label>
      ))}
      {formError && <p role="alert" className="error">{formError}</p>}
      <button className="primary" disabled={busy}>{busy ? "Submitting…" : "Submit for processing"}</button>
      <p className="muted small">Do not put tokens or passwords in URLs. Credentials are configured on the server.</p>
    </form>
  );
}
