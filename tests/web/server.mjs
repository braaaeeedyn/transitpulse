// Starts the FastAPI app (the API and web/) on a free port for the scripts in tests/web/ (screenshots.mjs,
// lighthouse.mjs). It reads the local warehouse when data/transitpulse.duckdb exists, the same rule as
// `tasks.py api`, so the page's data requests answer 200 instead of 503.
import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { createServer } from "node:net";

const ROOT = new URL("../../", import.meta.url);
export const HAS_WAREHOUSE = existsSync(new URL("data/transitpulse.duckdb", ROOT));

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

/** Resolves to {url, warehouse, stop} once /healthz answers. Always call stop(), even after a failure. */
export async function startServer() {
  const port = await freePort();
  const env = { ...process.env };
  if (HAS_WAREHOUSE && !env.TP_GCP_PROJECT) env.TP_WAREHOUSE ??= "duckdb";
  const args = ["run", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", String(port), "--log-level", "warning"];
  const child = spawn("uv", args, { cwd: ROOT, env, stdio: ["ignore", "ignore", "inherit"] });
  // `uv run` starts python as a child process, so Windows needs the whole tree killed
  const stop = () =>
    process.platform === "win32"
      ? spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" })
      : child.kill();
  const url = `http://127.0.0.1:${port}/`;
  const deadline = Date.now() + 60_000;
  for (;;) {
    if (child.exitCode !== null) throw new Error(`the API server exited with code ${child.exitCode}`);
    try {
      if ((await fetch(`${url}healthz`)).ok) return { url, warehouse: env.TP_WAREHOUSE ?? "none", stop };
    } catch {
      // not listening yet
    }
    if (Date.now() > deadline) {
      stop();
      throw new Error("the API server didn't answer /healthz within 60 s");
    }
    await new Promise((r) => setTimeout(r, 250));
  }
}
