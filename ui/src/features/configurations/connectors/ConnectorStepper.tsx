import { KeyboardEvent } from "react";
import { ConnectorLogo } from "./ConnectorLogo";

export interface StepInfo {
  key: string;
  label: string;
  state: "off" | "incomplete" | "complete" | "checking" | "connected" | "failed";
  hasError: boolean;
}

interface Props {
  steps: StepInfo[];
  activeKey: string;
  onSelect: (key: string) => void;
}

export const stepTabId = (key: string) => `step-tab-${key}`;
export const stepPanelId = (key: string) => `step-panel-${key}`;

/** The connectors laid out side by side as tabs, free to open in any order. Each tab says whether the connector is used and whether it is ready. */
export function ConnectorStepper({ steps, activeKey, onSelect }: Props) {
  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const delta = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!delta) return;
    e.preventDefault();
    const next = steps[(index + delta + steps.length) % steps.length];
    onSelect(next.key);
    document.getElementById(stepTabId(next.key))?.focus();
  };

  return (
    <div role="tablist" aria-label="Connectors" className="stepper">
      {steps.map((s, i) => {
        const active = s.key === activeKey;
        const bad = s.hasError || s.state === "failed";
        const good = s.state === "complete" || s.state === "connected";
        const cls = ["step", bad ? "step-error" : good ? "step-complete" : s.state === "off" ? "step-off" : ""].join(" ").trim();
        const stateText = bad ? "Needs attention" : s.state === "connected" ? "Connected" : s.state === "complete" ? "Ready" : s.state === "checking" ? "Checking…" : s.state === "off" ? "Not used" : "Needs input";
        return (
          <button
            key={s.key} id={stepTabId(s.key)} role="tab" type="button" className={cls}
            aria-selected={active} aria-controls={stepPanelId(s.key)} tabIndex={active ? 0 : -1}
            onClick={() => onSelect(s.key)} onKeyDown={(e) => onKeyDown(e, i)}
          >
            <span className="step-logo">
              <ConnectorLogo connector={s.key} size={38} />
              {(bad || good) && <span className="step-badge" aria-hidden="true">{bad ? "!" : "✓"}</span>}
              {s.state === "checking" && <span className="step-badge step-badge-busy" aria-hidden="true"><span className="spinner" /></span>}
            </span>
            <span className="step-text">
              <span className="step-label">{s.label}</span>
              <span className="step-state">{stateText}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
