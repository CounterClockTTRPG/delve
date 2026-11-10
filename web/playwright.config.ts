// The browser checks of the play screen and the module editor (`make e2e-browser`, not in `make ci`): Chromium against
// `delve serve` with a fake `claude` (tests/e2e/fake_play_server.py). The real `claude` never runs.
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";

// A free high port, never one of the owner's (5000, 7777, 7790, 7810, 8000).
const port = Number(process.env.DELVE_E2E_PORT ?? 47811);
const python = process.env.DELVE_E2E_PYTHON ?? "uv run python";
// The folders the Storage section's spec sets as the stores (zzz-storage.spec.ts), made afresh by the server: the
// workers read the same path from the environment.
process.env.DELVE_E2E_STORES ??= join(tmpdir(), `delve-e2e-stores-${port}`);
const stores = process.env.DELVE_E2E_STORES;

export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    ...devices["Desktop Chrome"],
    viewport: { width: 1280, height: 800 },
    // A fake microphone that beeps, granted without asking (voice.spec.ts).
    launchOptions: { args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] },
  },
  webServer: {
    command: `${python} -m tests.e2e.fake_play_server --port ${port} --stores "${stores}"`,
    cwd: "..",
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
