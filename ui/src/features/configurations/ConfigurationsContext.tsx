import { createContext, ReactNode, useContext } from "react";
import { Configuration } from "../../shared/api/types";
import { useConfigurations } from "./hooks";

interface Ctx {
  items: Configuration[] | null;
  error: Error | null;
  refresh: () => Promise<void>;
  add: (c: Configuration) => void;
}

const ConfigurationsContext = createContext<Ctx | null>(null);

/** One shared, auto-refreshing list for the sidebar and the pages, so they never disagree and poll once. */
export function ConfigurationsProvider({ children }: { children: ReactNode }) {
  const value = useConfigurations();
  return <ConfigurationsContext.Provider value={value}>{children}</ConfigurationsContext.Provider>;
}

export function useConfigurationList(): Ctx {
  const ctx = useContext(ConfigurationsContext);
  if (!ctx) throw new Error("useConfigurationList must be used inside ConfigurationsProvider");
  return ctx;
}
