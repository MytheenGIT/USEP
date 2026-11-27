import { InputHTMLAttributes } from "react";

interface Props extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "onChange"> {
  label: string;
  hint?: string;
  onChange: (checked: boolean) => void;
}

/** An on/off choice. It is a real checkbox underneath, so keyboard and screen readers work as for any checkbox. */
export function Switch({ label, hint, onChange, checked, disabled, id, ...rest }: Props) {
  const switchId = id ?? `sw-${label.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <label className={disabled ? "switch switch-disabled" : "switch"} htmlFor={switchId}>
      <input {...rest} id={switchId} type="checkbox" role="switch" checked={checked} disabled={disabled} aria-describedby={hint ? `${switchId}-hint` : undefined} onChange={(e) => onChange(e.target.checked)} />
      <span className="switch-track" aria-hidden="true"><span className="switch-thumb" /></span>
      <span className="switch-text">
        <span className="switch-label">{label}</span>
        {hint && <span id={`${switchId}-hint`} className="hint">{hint}</span>}
      </span>
    </label>
  );
}
