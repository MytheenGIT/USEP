import { ReactNode } from "react";

export type Tone = "neutral" | "success" | "warning" | "danger" | "info";

/** Status is always carried by the text as well as the colour. */
export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  );
}
