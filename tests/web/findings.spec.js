// The Findings ink band (IMPLEMENTATION_PLAN M4, web/js/findings.js), with GET /api/findings mocked by page.route
// and a synthetic fixture (tests/web/fixtures/api/findings.json), never the real results.
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

const FIXTURE = JSON.parse(readFileSync(new URL("./fixtures/api/findings.json", import.meta.url)));
const MINUS = "−";

const json = (route, body, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const band = (page) => page.locator("[data-findings]");

test("findings: the band shows the fixture's verdict, numbers, caution and method", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route("**/api/findings", (route) => json(route, FIXTURE));
  await page.goto("/");
  await expect(band(page).locator("[data-findings-verdict]")).toContainText("consistent with eBART mostly moving riders");
  const corridor = band(page).locator("[data-findings-figure=corridor]");
  await expect(corridor).toContainText("Whole line, Concord → Antioch (incl. new stations)");
  await expect(corridor.locator(".findings__figure-value")).toHaveText("0.0%");
  await expect(corridor).toContainText(`95% interval ${MINUS}3.0% to +4.0%`);
  await expect(corridor).toContainText(`about 0 more entries a day (${MINUS}1,230 to 1,650)`);
  const legacy = band(page).locator("[data-findings-figure=legacy]");
  await expect(legacy).toContainText("Pittsburg/Bay Point, North Concord, Concord");
  await expect(legacy.locator(".findings__figure-value")).toHaveText(`${MINUS}10.0%`);
  await expect(legacy).toContainText(`95% interval ${MINUS}15.0% to ${MINUS}5.0%`);
  await expect(band(page).locator("[data-findings-caution]")).toContainText("with care");
  await expect(band(page).locator("[data-findings-method]")).toContainText(
    "Difference-in-differences against 34 BART stations far from the line, pre-registered on Oct 9, 2026. 95% intervals from placebo tests.",
  );
  await expect(band(page).locator("[data-findings-method] a")).toHaveAttribute(
    "href",
    "https://github.com/braaaeeedyn/transitpulse/blob/main/docs/FINDINGS.md",
  );
  await expect(band(page).locator(".skeleton")).toHaveCount(0);
  await expect(band(page)).toHaveAttribute("aria-busy", "false");
});

test("findings: no caution sentence when the flag is off", async ({ page }) => {
  await page.route("**/api/findings", (route) => json(route, { ...FIXTURE, caution: false, verdict: "new" }));
  await page.goto("/");
  await expect(band(page).locator("[data-findings-verdict]")).toContainText(
    "consistent with eBART bringing a modest number of new riders",
  );
  await expect(band(page).locator("[data-findings-caution]")).toHaveCount(0);
});

test("findings: the hedge note shows for the new verdict only", async ({ page }) => {
  let verdict = "new";
  await page.route("**/api/findings", (route) => json(route, { ...FIXTURE, caution: false, verdict }));
  await page.goto("/");
  const note = band(page).locator("[data-findings-note]");
  await expect(note).toBeVisible();
  await expect(note).toContainText("before the opening");
  verdict = "moved";
  await page.reload();
  await expect(band(page).locator("[data-findings-verdict]")).toContainText("mostly moving riders");
  await expect(band(page).locator("[data-findings-note]")).toHaveCount(0);
});

test("findings: two event-study charts with a point per bin and hidden tables", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route("**/api/findings", (route) => json(route, FIXTURE));
  await page.goto("/");
  for (const key of ["legacy", "corridor"]) {
    const card = band(page).locator(`[data-findings-chart=${key}]`);
    const n = FIXTURE.event_study.series[key].length;
    await expect(card.locator("svg.findings-chart__svg")).toHaveCount(1);
    await expect(card.locator(".findings-chart__point")).toHaveCount(n);
    await expect(card.locator("svg .chart__line")).toHaveCount(1);
    await expect(card.locator("svg .chart__band")).toHaveCount(1);
    await expect(card.locator("svg .findings-chart__event")).toHaveCount(1);
    await expect(card.locator("svg")).toHaveAttribute("aria-label", /95% placebo bands/);
    const table = card.locator(".visually-hidden table");
    await expect(table.locator("tbody tr")).toHaveCount(n);
    await expect(table.locator("tbody tr").nth(1)).toContainText(`${MINUS}5 to ${MINUS}2`);
  }
  // side by side from 768 px
  const [a, b] = await band(page)
    .locator("[data-findings-chart]")
    .evaluateAll((els) => els.map((e) => e.getBoundingClientRect().top));
  expect(Math.abs(a - b)).toBeLessThan(1);
});

test("findings: 404 says the analysis is in progress", async ({ page }) => {
  await page.route("**/api/findings", (route) =>
    json(route, { detail: { code: "findings_not_available", message: "The analysis is in progress." } }, 404),
  );
  await page.goto("/");
  await expect(band(page).locator(".message")).toHaveText("The analysis is in progress.");
  await expect(band(page).locator("[data-action]")).toHaveCount(0);
});

test("findings: a server error offers Retry, which recovers", async ({ page }) => {
  let fail = true;
  await page.route("**/api/findings", (route) => (fail ? json(route, { detail: "boom" }, 500) : json(route, FIXTURE)));
  await page.goto("/");
  const retry = band(page).locator("[data-action]");
  await expect(retry).toHaveText("Retry");
  await expect(band(page).locator(".message--error")).toContainText("didn't load");
  fail = false;
  await retry.click();
  await expect(band(page).locator("[data-findings-verdict]")).toContainText("consistent with eBART mostly moving riders");
  await expect(band(page).locator(".findings-chart__point")).toHaveCount(2 * FIXTURE.event_study.series.legacy.length);
});

for (const width of [320, 375]) {
  test(`findings: no horizontal overflow at ${width}px, charts stacked`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.route("**/api/findings", (route) => json(route, FIXTURE));
    await page.goto("/");
    await expect(band(page).locator(".findings-chart__point")).toHaveCount(2 * FIXTURE.event_study.series.legacy.length);
    await band(page).scrollIntoViewIfNeeded();
    const [scrollW, innerW] = await page.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
    expect(scrollW).toBeLessThanOrEqual(innerW);
    const [a, b] = await band(page)
      .locator("[data-findings-chart]")
      .evaluateAll((els) => els.map((e) => e.getBoundingClientRect().top));
    expect(b).toBeGreaterThan(a);
  });
}
