// Data on the site (IMPLEMENTATION_PLAN F4): Trends band and the station tooltip, with the API mocked by
// page.route and JSON fixtures in tests/web/fixtures/api/, so these tests don't need a warehouse.
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/api/${name}.json`, import.meta.url)));
const KPIS = fixture("kpis");
const RIDERSHIP = fixture("ridership");
const STATION_EMBR = fixture("station-EMBR");
const BIKES = fixture("bikes-vs-trains");
const NETWORK = JSON.parse(readFileSync(new URL("../../web/data/network.json", import.meta.url)));

const NIGHT = new Date("2026-10-07T03:00:00-07:00"); // no trains, so hovering a station can't hit a train
const NOT_CONNECTED = { detail: { code: "warehouse_not_connected", message: "Ridership data isn't connected yet." } };

const json = (route, body, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

async function mockTrends(page, { kpis = KPIS, ridership = RIDERSHIP, bikes = BIKES, gate = null } = {}) {
  await page.route("**/api/kpis", async (route) => {
    if (gate) await gate;
    await json(route, kpis);
  });
  await page.route("**/api/trends/ridership", async (route) => {
    if (gate) await gate;
    await json(route, ridership);
  });
  await page.route("**/api/trends/bikes-vs-trains", async (route) => {
    if (gate) await gate;
    await (bikes.status ? json(route, bikes.body, bikes.status) : json(route, bikes));
  });
}

const tiles = (page) => page.locator("[data-trends] .stat-tile[data-tile]");

test("trends: KPI tiles and charts render from the API", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockTrends(page);
  await page.goto("/");
  await expect(tiles(page)).toHaveCount(4);

  await expect(page.locator("[data-trends-through]")).toContainText("Data through Dec 31, 2025");
  await expect(page.locator("[data-tile=recovery] .stat-tile__value")).toHaveText("38%");
  await expect(page.locator("[data-tile=entries] .stat-tile__value")).toHaveText("115,501");
  await expect(page.locator("[data-tile=entries] .stat-tile__delta")).toHaveText("▲ 3.1% vs a year earlier");
  await expect(page.locator("[data-tile=peak_share] .stat-tile__value")).toHaveText("10.9%");
  await expect(page.locator("[data-tile=peak_share] .stat-tile__delta")).toHaveText("▼ 0.9 pts vs 2019");
  await expect(page.locator("[data-tile=busiest_station] .stat-tile__value")).toHaveText("Powell Street");

  // ⓘ reveals the definition
  const info = page.locator("[data-tile=recovery] .stat-tile__info");
  await expect(page.locator("#kpi-def-recovery")).toBeHidden();
  await info.click();
  await expect(info).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator("#kpi-def-recovery")).toContainText("same week of the year");

  // chart: one line, broken at the 2020-2024 months that aren't loaded; takeaway names the latest month
  await expect(page.locator("[data-chart-title]")).toHaveText("Ridership since 2019");
  await expect(page.locator("[data-takeaway]")).toContainText("In Dec 2025, BART averaged");
  const d = await page.locator("[data-chart] .chart__line").getAttribute("d");
  expect(d.match(/M/g)).toHaveLength(2);
  await expect(page.locator("[data-chart] .chart__tick", { hasText: "2025" })).toHaveCount(1);
  await expect(page.locator("[data-chart] .chart__svg")).toHaveAttribute("aria-label", /Gaps are months with no data/);

  // bikes vs trains: BART solid + Bay Wheels dashed, both named in the legend
  const bikes = page.locator("[data-bikes-card]");
  await expect(bikes.locator(".chart__svg .chart__line--primary")).toHaveCount(1);
  await expect(bikes.locator(".chart__svg .chart__line--secondary")).toHaveCount(1);
  await expect(bikes.locator(".chart-legend")).toContainText("BART entries");
  await expect(bikes.locator(".chart-legend")).toContainText("Bay Wheels trips");
  await expect(bikes.locator("[data-bikes-takeaway]")).toHaveText(
    "In Dec 2025, Bay Wheels trips were at 191% of Dec 2019 and BART entries at 43%.",
  );
  const dash = await bikes.locator(".chart__svg .chart__line--secondary").evaluate((el) => getComputedStyle(el).strokeDasharray);
  expect(dash.replace(/px/g, "")).toMatch(/^4,? 3$/);
  await expect(page.locator("[data-trends] .skeleton")).toHaveCount(0);
});

test("trends: missing bike data keeps the BART numbers and says why", async ({ page }) => {
  await mockTrends(page, { bikes: { status: 404, body: { detail: { code: "data_not_available" } } } });
  await page.goto("/");
  await expect(tiles(page)).toHaveCount(4);
  await expect(page.locator("[data-chart] .chart__line")).toHaveCount(1);
  await expect(page.locator("[data-bikes-card] .message")).toContainText("Bay Wheels numbers will appear here");
  await expect(page.locator("[data-trends] .skeleton")).toHaveCount(0);
});

test("trends: not connected keeps the honest empty state", async ({ page }) => {
  await page.route("**/api/kpis", (route) => json(route, NOT_CONNECTED, 503));
  await page.route("**/api/trends/ridership", (route) => json(route, NOT_CONNECTED, 503));
  await page.goto("/");
  const msg = page.locator("[data-trends] .message");
  await expect(msg).toContainText("Ridership numbers will appear here once the data pipeline is connected.");
  await expect(msg).not.toHaveClass(/message--error/);
  await expect(tiles(page)).toHaveCount(0);
  await expect(page.locator("[data-trends] .skeleton")).toHaveCount(0);
});

test("trends: a failed request shows Retry and Retry reloads", async ({ page }) => {
  let kpiCalls = 0;
  await page.route("**/api/kpis", async (route) => {
    kpiCalls += 1;
    if (kpiCalls === 1) await route.fulfill({ status: 500, body: "boom" });
    else await json(route, KPIS);
  });
  await page.route("**/api/trends/ridership", (route) => json(route, RIDERSHIP));
  await page.goto("/");
  const err = page.locator("[data-trends] .message--error");
  await expect(err).toContainText("didn't load");
  await err.getByRole("button", { name: "Retry" }).click();
  await expect(tiles(page)).toHaveCount(4);
  await expect(page.locator("[data-chart] .chart__line")).toHaveCount(1);
  expect(kpiCalls).toBe(2);
});

test("trends: skeletons hold the space while loading", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  let release;
  const gate = new Promise((r) => {
    release = r;
  });
  await mockTrends(page, { gate });
  await page.goto("/");
  await page.evaluate(() => document.fonts.ready);
  const region = page.locator("[data-trends]");
  await expect(region.locator(".skeleton").first()).toBeVisible();
  await expect(region).toHaveAttribute("aria-busy", "true");
  const before = (await region.boundingBox()).height;
  release();
  await expect(tiles(page)).toHaveCount(4);
  await expect(page.locator(".chart__svg")).toHaveCount(2);
  const after = (await region.boundingBox()).height;
  expect(Math.abs(after - before)).toBeLessThanOrEqual(2);
});

test("trends: no horizontal scroll at 320px with data loaded", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await mockTrends(page);
  await page.goto("/");
  await expect(tiles(page)).toHaveCount(4);
  await expect(page.locator(".chart__svg")).toHaveCount(2);
  const [scrollW, innerW] = await page.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
  expect(scrollW).toBeLessThanOrEqual(innerW);
  // narrow card: fewer y ticks and every other year
  expect(await page.locator("[data-chart] .chart__grid").count()).toBeLessThanOrEqual(4);
});

test("map: station tooltip shows entries when the API has data", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const requested = [];
  await page.route("**/api/stations/*/summary", (route) => {
    const code = route.request().url().split("/").at(-2);
    requested.push(code);
    return code === "EMBR"
      ? json(route, STATION_EMBR)
      : json(route, { detail: { code: "unknown_station" } }, 404);
  });
  await page.clock.install({ time: NIGHT });
  await page.goto("/");
  await expect(page.locator(".map-loading")).toHaveCount(0);

  const index = NETWORK.stations.findIndex((s) => s.code === "EMBR");
  await page.locator(".map-stage").scrollIntoViewIfNeeded();
  const box = await page.locator(`.map-station[data-station="${index}"]`).boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  const tip = page.locator(".tooltip");
  await expect(tip).toContainText("Embarcadero");
  await expect(tip).toContainText("Entries on Dec 31, 2025: 6,399 (52% of 2019)");
  expect(requested).toEqual(["EMBR"]);
});

// --- forecast explorer (F5) -------------------------------------------------------------------------
const FORECASTS = { EMBR: fixture("forecast-EMBR"), MCAR: fixture("forecast-MCAR") };

async function mockForecast(page) {
  await page.route("**/api/forecast/*", (route) => {
    const code = route.request().url().split("/").at(-1);
    return FORECASTS[code]
      ? json(route, FORECASTS[code])
      : json(route, { detail: { code: "forecast_not_available", message: "No forecast." } }, 404);
  });
}

test("forecast: keyboard-only station search shows a 14-day forecast", async ({ page }) => {
  await mockForecast(page);
  await page.goto("/");
  const input = page.locator("[data-fc-input]");
  await expect(page.locator("[data-fc-title]")).toHaveText("Embarcadero"); // the default station
  await expect(page.locator("[data-fc-chip=EMBR]")).toHaveAttribute("aria-pressed", "true");

  await input.focus();
  await page.keyboard.type("mac");
  await expect(input).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator("#fc-listbox [role=option]").first()).toContainText("MacArthur");
  await page.keyboard.press("ArrowDown");
  await expect(input).toHaveAttribute("aria-activedescendant", "fc-opt-0");
  await expect(page.locator("#fc-opt-0")).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Enter");
  await expect(page.locator("#fc-listbox")).toBeHidden();
  await expect(input).toHaveAttribute("aria-expanded", "false");
  await expect(input).toHaveValue("MacArthur");
  await expect(input).toBeFocused();

  await expect(page.locator("[data-fc-title]")).toHaveText("MacArthur");
  await expect(page.locator("[data-fc-caption]")).toHaveText(
    "For Tue, Jan 6, 2026 the model expected about 3,000 entries; model range (10th–90th percentile) 2,900–3,700.",
  );
  await expect(page.locator("[data-fc-source]")).toContainText("Forecast from data through Dec 31, 2025.");
  await expect(page.locator("[data-fc-source]")).toContainText("in back-testing it held 48% of actual days");
  await expect(page.locator("[data-fc-table] tbody tr")).toHaveCount(14);
  await expect(page.locator("[data-fc-chart] .chart__line--actual")).toHaveCount(1);
  await expect(page.locator("[data-fc-chart] .chart__line--forecast")).toHaveCount(1);
  await expect(page.locator("[data-fc-chart] .chart__band")).toHaveCount(1);
  await expect(page.locator("[data-fc-chip=MCAR]")).toHaveAttribute("aria-pressed", "true");

  // Escape closes an open list without choosing
  await page.keyboard.press("Control+A");
  await page.keyboard.type("pow");
  await expect(page.locator("#fc-listbox")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("#fc-listbox")).toBeHidden();
  await expect(page.locator("[data-fc-title]")).toHaveText("MacArthur");
});

test("forecast: legend and caption describe the calibrated range", async ({ page }) => {
  await mockForecast(page);
  await page.goto("/");
  await expect(page.locator("[data-fc-title]")).toHaveText("Embarcadero"); // calibrated fixture, 79% coverage
  await expect(page.locator("[data-fc-caption]")).toHaveText(
    "For Tue, Jan 6, 2026 the model expected about 11,400 entries; 80% range 9,500–14,700.",
  );
  await expect(page.locator("[data-fc-band]")).toHaveText("80% range");
  const source = page.locator("[data-fc-source]");
  await expect(source).toContainText("Forecast from data through Dec 31, 2025. It covers Jan 1–14, 2026,");
  await expect(source).toContainText("in back-testing it held 79% of actual days against an 80% target.");
  await expect(source).not.toContainText("narrower");
  await expect(page.locator("[data-fc-table] th")).toContainText(["80% range: low", "80% range: high"]);
  await expect(page.locator("[data-fc-table] tbody tr").first()).toContainText("Thu, Jan 1, 2026");
  // the band drawn is the published one (lo/hi), not the raw quantiles: its top reaches the highest `hi`
  await expect(page.locator("[data-fc-chart] .chart__band")).toHaveCount(1);
  const label = await page.locator("[data-fc-chart] .chart__svg").getAttribute("aria-label");
  expect(label).toContain("with its 80% range (shaded)");
  expect(label).not.toContain("likely");
});

test("forecast: an uncalibrated band is called the model range", async ({ page }) => {
  await mockForecast(page);
  await page.goto("/");
  await page.locator("[data-fc-chip=MCAR]").click(); // the older API shape: raw p10-p90, 47.5% coverage
  await expect(page.locator("[data-fc-title]")).toHaveText("MacArthur");
  await expect(page.locator("[data-fc-caption]")).toHaveText(
    "For Tue, Jan 6, 2026 the model expected about 3,000 entries; model range (10th–90th percentile) 2,900–3,700.",
  );
  await expect(page.locator("[data-fc-band]")).toHaveText("Model range (10th–90th percentile)");
  await expect(page.locator("[data-fc-source]")).toContainText(
    "in back-testing it held 48% of actual days against an 80% target, so it is narrower than it should be.",
  );
  await expect(page.locator("[data-fc-table] th")).toContainText([
    "Model range low (10th percentile)",
    "Model range high (90th percentile)",
  ]);
  await expect(page.locator("#forecast")).not.toContainText(/likely|80% range/i);
  // the longer legend label wraps instead of widening the page on the smallest phone
  await page.setViewportSize({ width: 320, height: 640 });
  await page.locator("[data-fc-band]").scrollIntoViewIfNeeded();
  const [scrollW, innerW] = await page.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
  expect(scrollW).toBeLessThanOrEqual(innerW);
});

test("forecast: missing forecast offers another station", async ({ page }) => {
  await mockForecast(page);
  await page.goto("/");
  await expect(page.locator("[data-fc-title]")).toHaveText("Embarcadero");
  const input = page.locator("[data-fc-input]");
  await input.focus();
  await page.keyboard.type("berr");
  await page.keyboard.press("Enter");
  const msg = page.locator("[data-fc-result] .message");
  await expect(msg).toContainText("There's no forecast for Berryessa");
  const again = msg.getByRole("button", { name: "Try another station" });
  await again.click();
  await expect(input).toBeFocused();
  await expect(input).toHaveValue("");
  await expect(page.locator("#fc-listbox")).toBeVisible();
  await page.keyboard.type("embr");
  await page.keyboard.press("Enter");
  await expect(page.locator("[data-fc-title]")).toHaveText("Embarcadero");
});

test("forecast: fits a phone in portrait", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockForecast(page);
  await page.goto("/");
  await page.locator("#forecast").scrollIntoViewIfNeeded();
  const chart = page.locator("[data-fc-chart] .chart__svg");
  await expect(chart).toBeVisible();
  const [scrollW, innerW] = await page.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
  expect(scrollW).toBeLessThanOrEqual(innerW);
  const box = await chart.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(390);
  expect(box.height).toBeGreaterThan(150);
  // the chips wrap rather than widening the page, and stay tappable
  const chip = await page.locator("[data-fc-chip=MCAR]").boundingBox();
  expect(chip.x + chip.width).toBeLessThanOrEqual(390);
});
