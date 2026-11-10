/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

// Build into the Python package, so one `delve serve` process serves the SPA.
const here = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    // portraitgen is vendored, not an npm dependency (web/vendor/portraitgen/README.md).
    alias: [{ find: /^portraitgen$/, replacement: resolve(here, "vendor/portraitgen/src/index.js") }],
  },
  build: {
    outDir: resolve(here, "../src/delve/web/static"),
    emptyOutDir: true,
    rollupOptions: {
      // portraitgen's own editor, a page of its own that the sheet's Edit portrait frames (DEL-238).
      input: { main: resolve(here, "index.html"), portraitEditor: resolve(here, "vendor/portraitgen/web/index.html") },
    },
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:7810",
    },
  },
  test: {
    environment: "jsdom",
    // globals lets Testing Library register its own cleanup after each test.
    globals: true,
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    setupFiles: ["./src/vitest.setup.ts"],
    // monaco-editor only declares "module"; tests mock it, but its name still has to resolve.
    alias: [{ find: /^monaco-editor$/, replacement: "monaco-editor/esm/vs/editor/editor.main.js" }],
  },
});
