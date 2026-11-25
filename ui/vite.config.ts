import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API is not built yet. With VITE_USE_MOCK=false the UI calls /api/*, proxied to VITE_API_TARGET.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": process.env.VITE_API_TARGET ?? "http://localhost:8000" } },
});
