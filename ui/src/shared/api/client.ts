import { httpApi } from "./http";
import { mockApi } from "./mock";
import { Api } from "./types";

// The real API is the default. The in-browser mock (synthetic data) is opt-in with VITE_USE_MOCK=true.
export const usingMock = import.meta.env.VITE_USE_MOCK === "true";
export const api: Api = usingMock ? mockApi : httpApi;
