// Lighthouse on the home page (IMPLEMENTATION_PLAN F7). Not a test file and not in CI: performance scores on shared
// runners vary too much to gate on. Run it locally: `uv run python tasks.py lighthouse [--runs N] [--assert]`.
// It starts its own API server (the local warehouse when there is one, so data requests don't log 503s), runs
// Lighthouse's default mobile config (Moto G Power, simulated slow 4G and 4x CPU) N times in Playwright's Chromium,
// stops the server, and prints the median-performance run as JSON:
//   {performance, accessibility, best_practices, lcp_ms, cls, runs: [every run]}
// --assert exits 1 unless performance >= 90, accessibility >= 95 and best practices >= 95.
import { parseArgs } from "node:util";
import { chromium } from "@playwright/test";
import * as chromeLauncher from "chrome-launcher";
import lighthouse from "lighthouse";
import { startServer } from "./server.mjs";

const GATE = { performance: 90, accessibility: 95, best_practices: 95 };
const CATEGORY = { performance: "performance", accessibility: "accessibility", best_practices: "best-practices" };

const { values } = parseArgs({
  options: { runs: { type: "string", default: "1" }, assert: { type: "boolean", default: false } },
});
const runs = Math.max(1, Number.parseInt(values.runs, 10) || 1);

const results = [];
const failing = new Map(); // category → audit ids that lost points, for whoever has to fix them
const server = await startServer();
let chrome;
try {
  chrome = await chromeLauncher.launch({ chromePath: chromium.executablePath(), chromeFlags: ["--headless=new"] });
  for (let i = 0; i < runs; i++) {
    const { lhr } = await lighthouse(server.url, {
      port: chrome.port,
      logLevel: "error",
      onlyCategories: Object.values(CATEGORY),
    });
    const run = {};
    for (const [key, id] of Object.entries(CATEGORY)) {
      const category = lhr.categories[id];
      run[key] = Math.round(category.score * 100);
      const lost = category.auditRefs.filter((a) => a.weight > 0 && (lhr.audits[a.id].score ?? 1) < 1).map((a) => a.id);
      failing.set(key, lost);
    }
    run.lcp_ms = Math.round(lhr.audits["largest-contentful-paint"].numericValue);
    run.cls = Number(lhr.audits["cumulative-layout-shift"].numericValue.toFixed(3));
    results.push(run);
  }
} finally {
  await chrome?.kill();
  server.stop();
}

const median = results.toSorted((a, b) => a.performance - b.performance)[Math.floor(results.length / 2)];
console.log(JSON.stringify({ ...median, runs: results }));

if (values.assert) {
  const below = Object.entries(GATE).filter(([key, min]) => median[key] < min);
  for (const [key, min] of below) {
    console.error(`${key} ${median[key]} < ${min}; audits losing points: ${failing.get(key).join(", ")}`);
  }
  if (below.length) process.exit(1);
}
