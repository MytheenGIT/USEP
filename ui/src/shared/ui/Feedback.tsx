import { ReactNode } from "react";

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="center-pad" role="status">
      <span className="spinner spinner-lg" aria-hidden="true" />
      <span className="muted">{label}…</span>
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children && <p className="muted">{children}</p>}
      {action}
    </div>
  );
}

export function ErrorMessage({ children, onRetry }: { children: ReactNode; onRetry?: () => void }) {
  return (
    <div role="alert" className="alert alert-danger">
      <span>{children}</span>
      {onRetry && <button className="btn btn-secondary" onClick={onRetry}>Retry</button>}
    </div>
  );
}
