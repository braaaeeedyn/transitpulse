// The README screenshots and the Open Graph image (not a test: `uv run python tasks.py screenshots`).
// Playwright's Chromium with a fixed clock (Wednesday 8:00 AM Pacific, so trains are running), against the local
// warehouse when data/transitpulse.duckdb exists, else the Playwright tests' API fixtures. Writes:
//   web/img/og.png                   1200 × 630, the train map (under 400 KB)
//   docs/img/screenshot-phone.png    390 px wide, the live map band on a phone
//   docs/img/screenshot-desktop.png  1440 px wide, the top of the page through the live map
// and fails if any file is over its size limit.
import { readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { HAS_WAREHOUSE, startServer } from "./server.mjs";

const ROOT = new URL("../../", import.meta.url);
const TIME = new Date("2026-10-07T08:00:00-07:00"); // a Wednesday
const KB = 1024;
const file = (path) => fileURLToPath(new URL(path, ROOT));
const fixture = (name) => readFileSync(new URL(`fixtures/api/${name}.json`, import.meta.url), "utf-8");

async function openPage(browser, url, viewport) {
  const page = await browser.newPage({ viewport, deviceScaleFactor: 1 });
  if (!HAS_WAREHOUSE) {
    const json = (body) => (route) => route.fulfill({ contentType: "application/json", body });
    await page.route("**/api/kpis", json(fixture("kpis")));
    await page.route("**/api/trends/ridership", json(fixture("ridership")));
    await page.route("**/api/trends/bikes-vs-trains", json(fixture("bikes-vs-trains")));
    await page.route("**/api/forecast/*", json(fixture("forecast-EMBR")));
  }
  await page.clock.install({ time: TIME });
  await page.goto(url);
  await page.locator("[data-map-summary]").filter({ hasText: "trains running" }).waitFor({ state: "attached" });
  await page.locator("[data-trends] .stat-tile[data-tile]").first().waitFor();
  await page.evaluate(() => document.fonts.ready);
  return page;
}

function check(path, limit) {
  const size = statSync(file(path)).size;
  console.log(`${path}: ${Math.round(size / KB)} KB`);
  if (size > limit) throw new Error(`${path} is over ${limit / KB} KB`);
}

const server = await startServer();
const browser = await chromium.launch();
try {
  console.log(`server ${server.url} (warehouse: ${server.warehouse}${HAS_WAREHOUSE ? "" : ", API fixtures"})`);

  // Open Graph: the map stage alone, made exactly 1200 × 630, without its floating controls
  let page = await openPage(browser, server.url, { width: 1200, height: 900 });
  await page.addStyleTag({
    content: `.container { width: 100%; } .map-card { border-radius: 0; }
      .map-stage { aspect-ratio: auto; height: 630px; max-height: none; } .map-top, .map-controls, .ask-launcher { display: none; }`,
  });
  await page.locator(".map-stage").scrollIntoViewIfNeeded();
  await page.waitForTimeout(500); // the map re-lays itself out on the stage's ResizeObserver
  const box = await page.locator(".map-stage").boundingBox(); // whole pixels: an element shot can come out 631 tall
  const ogClip = { x: Math.round(box.x), y: Math.round(box.y), width: 1200, height: 630 };
  await page.screenshot({ path: file("web/img/og.png"), clip: ogClip });
  await page.close();
  check("web/img/og.png", 400 * KB);

  // phone: the live map band, as it looks scrolled to it
  page = await openPage(browser, server.url, { width: 390, height: 844 });
  await page.evaluate(() => document.getElementById("map").scrollIntoView({ behavior: "instant" }));
  await page.waitForTimeout(500);
  await page.screenshot({ path: file("docs/img/screenshot-phone.png") });
  await page.close();
  check("docs/img/screenshot-phone.png", 600 * KB);

  // desktop: from the top of the page through the end of the live map band
  page = await openPage(browser, server.url, { width: 1440, height: 900 });
  const bottom = await page.evaluate(() => {
    const r = document.querySelector(".map-meta").getBoundingClientRect();
    return Math.ceil(r.bottom + window.scrollY + 32);
  });
  const clip = { x: 0, y: 0, width: 1440, height: bottom };
  await page.screenshot({ path: file("docs/img/screenshot-desktop.png"), fullPage: true, clip });
  await page.close();
  check("docs/img/screenshot-desktop.png", 600 * KB);
} finally {
  await browser.close();
  server.stop();
}
