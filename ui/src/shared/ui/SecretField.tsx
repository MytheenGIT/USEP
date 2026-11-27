import { InputHTMLAttributes, useState } from "react";

interface Props extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label: string;
  error?: string;
  hint?: string;
  wide?: boolean;
}

/** An eye that opens and closes. Pure CSS: the slash draws across it and the lid lifts when the secret is shown. */
function Eye({ shown }: { shown: boolean }) {
  return (
    <svg className="eye" data-shown={shown} width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <g className="eye-ball">
        <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" />
        <circle className="eye-pupil" cx="12" cy="12" r="3" />
      </g>
      <path className="eye-slash" d="M4 4l16 16" />
    </svg>
  );
}

/**
 * Write-only secret input. Hidden by default. Once something is typed, an eye appears inside the box (it fades in) and
 * toggles between showing and hiding it. The browser is told not to remember it.
 */
export function SecretField({ label, error, hint, id, required, wide, value, ...rest }: Props) {
  const [shown, setShown] = useState(false);
  const inputId = id ?? `f-${label.replace(/\W+/g, "-").toLowerCase()}`;
  const describedBy = [error ? `${inputId}-err` : "", hint ? `${inputId}-hint` : ""].filter(Boolean).join(" ") || undefined;
  const hasValue = typeof value === "string" ? value.length > 0 : !!value;
  return (
    <div className={wide ? "field field-wide" : "field"}>
      <label htmlFor={inputId}>
        {label}
        {required && <span aria-hidden="true" className="req"> *</span>}
      </label>
      <div className="secret-box">
        <input {...rest} value={value} id={inputId} type={shown ? "text" : "password"} autoComplete="new-password" spellCheck={false} aria-invalid={!!error} aria-describedby={describedBy} />
        <button
          type="button" className="eye-btn" data-visible={hasValue} tabIndex={hasValue ? 0 : -1} onClick={() => setShown((s) => !s)}
          aria-pressed={shown} aria-label={shown ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`}
        >
          <Eye shown={shown} />
        </button>
      </div>
      {hint && !error && <span id={`${inputId}-hint`} className="hint">{hint}</span>}
      {error && <span id={`${inputId}-err`} className="field-error">{error}</span>}
    </div>
  );
}
