import { DependencyList, useCallback, useEffect, useRef, useState } from "react";

export interface AsyncState<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  reload: () => void;
}

/** Runs `load` on mount and whenever `deps` change; ignores results that arrive after a newer call or unmount. */
export function useAsync<T>(load: () => Promise<T>, deps: DependencyList): AsyncState<T> {
  const [state, setState] = useState<{ data: T | null; error: Error | null; loading: boolean }>({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  const latest = useRef(0);

  useEffect(() => {
    const id = ++latest.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    load().then(
      (data) => id === latest.current && setState({ data, error: null, loading: false }),
      (error: unknown) => id === latest.current && setState({ data: null, error: error instanceof Error ? error : new Error(String(error)), loading: false }),
    );
    return () => {
      latest.current++;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}
