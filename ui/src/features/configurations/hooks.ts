import { useCallback, useEffect, useState } from "react";
import { api } from "../../shared/api/client";
import { Configuration } from "../../shared/api/types";
import { usePolling } from "../../shared/hooks/usePolling";
import { useSession } from "../auth/AuthContext";

export const isPending = (c: Pick<Configuration, "status">) => c.status === "submitted" || c.status === "processing";
const POLL_MS = 1500;

/** The signed-in admin's configurations, refreshed while any of them is still processing. */
export function useConfigurations() {
  const { session, guard } = useSession();
  const [items, setItems] = useState<Configuration[] | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const refresh = useCallback(async () => {
    try {
      setItems(await guard(api.listConfigurations(session.token)));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Could not load configurations"));
    }
  }, [session.token, guard]);

  useEffect(() => { void refresh(); }, [refresh]);
  usePolling(() => void refresh(), POLL_MS, !!items?.some(isPending));

  const add = useCallback((c: Configuration) => setItems((x) => [c, ...(x ?? [])]), []);
  return { items, error, refresh, add };
}

/** One configuration, refreshed while it is still processing. */
export function useConfiguration(id: string) {
  const { session, guard } = useSession();
  const [config, setConfig] = useState<Configuration | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const refresh = useCallback(async () => {
    try {
      setConfig(await guard(api.getConfiguration(session.token, id)));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Could not load the configuration"));
    }
  }, [session.token, id, guard]);

  useEffect(() => {
    setConfig(null);
    void refresh();
  }, [refresh]);
  usePolling(() => void refresh(), POLL_MS, !!config && isPending(config));
  return { config, error, refresh };
}
