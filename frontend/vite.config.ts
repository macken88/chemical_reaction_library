import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Ketcher 3.14 transitively reads process.env from the browser bundle.
  define: { "process.env": {}, global: "globalThis" },
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
  test: { environment: "jsdom", setupFiles: "./src/test/setup.ts", css: true },
});
