// Browser tests for the site (IMPLEMENTATION_PLAN F7). Starts the FastAPI server, which serves web/.
import { defineConfig } from "@playwright/test";

const PORT = Number(process.env.TP_TEST_PORT ?? 8811);

export default defineConfig({
  testDir: "tests/web",
  testMatch: "**/*.spec.js", // *.test.mjs files are node:test unit tests
  timeout: 30_000,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${PORT}`, browserName: "chromium" },
  webServer: {
    command: `uv run uvicorn api.main:app --host 127.0.0.1 --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/healthz`,
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
