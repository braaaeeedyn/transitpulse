// Colour contrast with axe (F7, DESIGN.md §8): zero `color-contrast` violations on the page with every data
// section loaded (API mocked with the fixtures) at a phone and a desktop width, and on the style guide, which shows
// every text token on the surfaces it is allowed on.
import { readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const fixture = (name) => readFileSync(new URL(`./fixtures/api/${name}.json`, import.meta.url), "utf-8");
const RUSH_HOUR = new Date("2026-10-07T08:15:00-07:00");

async function mockLoaded(page) {
  const json = (body) => (route) => route.fulfill({ contentType: "application/json", body });
  await page.route("**/api/kpis", json(fixture("kpis")));
  await page.route("**/api/trends/ridership", json(fixture("ridership")));
  await page.route("**/api/trends/bikes-vs-trains", json(fixture("bikes-vs-trains")));
  await page.route("**/api/forecast/*", json(fixture("forecast-EMBR")));
  await page.route("**/api/findings", json(fixture("findings")));
}

async function contrastViolations(page) {
  const { violations } = await new AxeBuilder({ page }).withRules(["color-contrast"]).analyze();
  return violations.flatMap((v) => v.nodes.map((n) => `${n.target.join(" ")}: ${n.failureSummary}`));
}

for (const width of [390, 1440]) {
  test(`a11y: no colour-contrast violations on the loaded page at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockLoaded(page);
    await page.clock.install({ time: RUSH_HOUR });
    await page.goto("/");
    await expect(page.locator("[data-trends] .stat-tile[data-tile]")).toHaveCount(4);
    await expect(page.locator("[data-bikes-card] .chart__svg")).toHaveCount(1);
    await expect(page.locator("[data-fc-title]")).toHaveText("Embarcadero");
    await expect(page.locator("[data-findings-verdict]")).toBeVisible();
    await expect(page.locator("main .skeleton")).toHaveCount(0);
    await expect(page.locator("[data-map-summary]")).toContainText("trains running");
    expect(await contrastViolations(page)).toEqual([]);
  });
}

test("a11y: no colour-contrast violations in the style guide", async ({ page }) => {
  await page.goto("/styleguide.html");
  await page.locator("html[data-ready]").waitFor({ state: "attached" });
  expect(await contrastViolations(page)).toEqual([]);
});
