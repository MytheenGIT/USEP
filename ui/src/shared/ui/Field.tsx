import { InputHTMLAttributes, TextareaHTMLAttributes } from "react";

interface Props extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
  hint?: string;
  /** Take the full row in a multi-column form. */
  wide?: boolean;
}

export function Field({ label, error, hint, id, required, wide, ...rest }: Props) {
  const inputId = id ?? `f-${label.replace(/\W+/g, "-").toLowerCase()}`;
  const describedBy = [error ? `${inputId}-err` : "", hint ? `${inputId}-hint` : ""].filter(Boolean).join(" ") || undefined;
  return (
    <div className={wide ? "field field-wide" : "field"}>
      <label htmlFor={inputId}>
        {label}
        {required && <span aria-hidden="true" className="req"> *</span>}
      </label>
      <input {...rest} id={inputId} required={required} aria-invalid={!!error} aria-describedby={describedBy} />
      {hint && !error && <span id={`${inputId}-hint`} className="hint">{hint}</span>}
      {error && <span id={`${inputId}-err`} className="field-error">{error}</span>}
    </div>
  );
}

interface AreaProps extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "id"> {
  label: string;
  error?: string;
  hint?: string;
  id?: string;
  wide?: boolean;
}

/** A multi-line field, for values such as JQL where one entry takes a line. */
export function TextAreaField({ label, error, hint, id, wide, ...rest }: AreaProps) {
  const areaId = id ?? `f-${label.replace(/\W+/g, "-").toLowerCase()}`;
  const describedBy = [error ? `${areaId}-err` : "", hint ? `${areaId}-hint` : ""].filter(Boolean).join(" ") || undefined;
  return (
    <div className={wide ? "field field-wide" : "field"}>
      <label htmlFor={areaId}>{label}</label>
      <textarea {...rest} id={areaId} aria-invalid={!!error} aria-describedby={describedBy} />
      {hint && !error && <span id={`${areaId}-hint`} className="hint">{hint}</span>}
      {error && <span id={`${areaId}-err`} className="field-error">{error}</span>}
    </div>
  );
}
