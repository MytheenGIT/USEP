import { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  loading?: boolean;
}

export function Button({ variant = "secondary", loading = false, disabled, className = "", children, ...rest }: Props) {
  return (
    <button {...rest} type={rest.type ?? "button"} disabled={disabled || loading} aria-busy={loading || undefined} className={`btn btn-${variant} ${className}`.trim()}>
      {loading && <span className="spinner" aria-hidden="true" />}
      {children}
    </button>
  );
}
