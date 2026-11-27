import { ClipboardEvent, KeyboardEvent, useRef, useState } from "react";

interface Props {
  label: string;
  values: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  hint?: string;
  error?: string;
  required?: boolean;
  id?: string;
  wide?: boolean;
  /** Common values offered as one-click "+ value" pills until they are added. */
  suggestions?: string[];
}

const split = (text: string) => text.split(/[\s,;]+/).map((t) => t.trim()).filter(Boolean);

/**
 * Entries live inside the box as round pills with a cross, like skills in a profile. Enter, comma, space or a paste of
 * several adds them all; Backspace on an empty box removes the last one; clicking the box focuses the input.
 */
export function TagInput({ label, values, onChange, placeholder, hint, error, required, id, wide, suggestions }: Props) {
  const [draft, setDraft] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const inputId = id ?? `f-${label.replace(/\W+/g, "-").toLowerCase()}`;
  const describedBy = [error ? `${inputId}-err` : "", hint ? `${inputId}-hint` : ""].filter(Boolean).join(" ") || undefined;

  const add = (text: string) => {
    const fresh = [...new Set(split(text))].filter((t) => !values.includes(t));
    if (fresh.length) onChange([...values, ...fresh]);
    setDraft("");
  };
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(draft); }
    else if (e.key === "Backspace" && !draft && values.length) onChange(values.slice(0, -1));
  };
  const onPaste = (e: ClipboardEvent<HTMLInputElement>) => {
    const text = e.clipboardData.getData("text");
    if (/[\s,;]/.test(text.trim())) { e.preventDefault(); add(text); }
  };
  const offered = (suggestions ?? []).filter((s) => !values.includes(s));

  return (
    <div className={wide ? "field field-wide" : "field"}>
      <label htmlFor={inputId}>
        {label}
        {required && <span aria-hidden="true" className="req"> *</span>}
      </label>
      <div className={error ? "tags tags-invalid" : "tags"} onClick={() => input.current?.focus()}>
        {values.map((v) => (
          <span key={v} className="tag">
            <span className="tag-text" title={v}>{v}</span>
            <button type="button" aria-label={`Remove ${v}`} onClick={(e) => { e.stopPropagation(); onChange(values.filter((x) => x !== v)); }}>
              <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 2l6 6M8 2L2 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
            </button>
          </span>
        ))}
        <input
          ref={input} id={inputId} value={draft} placeholder={values.length ? "Add another" : placeholder} autoComplete="off" spellCheck={false}
          aria-invalid={!!error} aria-describedby={describedBy}
          onChange={(e) => setDraft(e.target.value)} onKeyDown={onKeyDown} onPaste={onPaste} onBlur={() => draft && add(draft)}
        />
      </div>
      {offered.length > 0 && (
        <div className="suggestions" aria-label="Suggestions">
          {offered.map((s) => <button key={s} type="button" className="suggestion" onClick={() => onChange([...values, s])}>+ {s}</button>)}
        </div>
      )}
      {hint && !error && <span id={`${inputId}-hint`} className="hint">{hint}</span>}
      {error && <span id={`${inputId}-err`} className="field-error">{error}</span>}
    </div>
  );
}
