import { AnchorHTMLAttributes, useEffect, useState } from "react";

/**
 * Tiny hash router (no dependency): #/configurations, #/configurations/new[?from=:id], #/configurations/:id,
 * #/configurations/:id/add, #/configurations/:id/processing, #/configurations/:id/graph, #/agent[/:id], #/profile
 */
export type Route =
  | { name: "configurations" }
  | { name: "new"; from?: string }
  | { name: "configuration"; id: string }
  | { name: "add"; id: string }
  | { name: "processing"; id: string }
  | { name: "graph"; id: string }
  | { name: "agent"; id?: string }
  | { name: "profile" }
  | { name: "notfound" };

export function parseRoute(hash: string): Route {
  const [pathPart, query = ""] = hash.replace(/^#\/?/, "").split("?");
  const parts = pathPart.split("/").filter(Boolean).map(decodeURIComponent);
  if (parts.length === 2 && parts[0] === "configurations" && parts[1] === "new") {
    const from = new URLSearchParams(query).get("from");
    return from ? { name: "new", from } : { name: "new" };
  }
  if (parts.length === 0 || (parts.length === 1 && parts[0] === "configurations")) return { name: "configurations" };
  if (parts[0] === "configurations" && parts.length === 2) return { name: "configuration", id: parts[1] };
  if (parts[0] === "configurations" && parts.length === 3 && parts[2] === "graph") return { name: "graph", id: parts[1] };
  if (parts[0] === "configurations" && parts.length === 3 && parts[2] === "add") return { name: "add", id: parts[1] };
  if (parts[0] === "configurations" && parts.length === 3 && parts[2] === "processing") return { name: "processing", id: parts[1] };
  if (parts[0] === "agent" && parts.length <= 2) return parts[1] ? { name: "agent", id: parts[1] } : { name: "agent" };
  if (parts.length === 1 && parts[0] === "profile") return { name: "profile" };
  return { name: "notfound" };
}

export const paths = {
  configurations: () => "#/configurations",
  newConfiguration: (from?: string) => (from ? `#/configurations/new?from=${encodeURIComponent(from)}` : "#/configurations/new"),
  configuration: (id: string) => `#/configurations/${encodeURIComponent(id)}`,
  addConnectors: (id: string) => `#/configurations/${encodeURIComponent(id)}/add`,
  processing: (id: string) => `#/configurations/${encodeURIComponent(id)}/processing`,
  graph: (id: string) => `#/configurations/${encodeURIComponent(id)}/graph`,
  agent: (id?: string) => (id ? `#/agent/${encodeURIComponent(id)}` : "#/agent"),
  profile: () => "#/profile",
};

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export const navigate = (to: string) => {
  window.location.hash = to;
};

export function Link({ to, ...rest }: { to: string } & AnchorHTMLAttributes<HTMLAnchorElement>) {
  return <a href={to} {...rest} />;
}
