import { useEffect, useRef } from "react";

/** Calls `tick` every `intervalMs` while `enabled`. Stops on unmount or when disabled. */
export function usePolling(tick: () => void, intervalMs: number, enabled: boolean): void {
  const saved = useRef(tick);
  saved.current = tick;
  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(() => saved.current(), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs, enabled]);
}
