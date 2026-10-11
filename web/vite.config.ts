import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev: `npm run dev` proxies /api to `autojob serve` on :8000.
// Build: output goes into the Python package so `autojob serve` ships the UI.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { outDir: "../autojob/static", emptyOutDir: true },
});
