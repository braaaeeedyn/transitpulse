// The Station closures band (web/js/closures.js, index.html #closures), with GET /api/closures mocked by page.route
// and a fixture generated once from the local API (tests/web/fixtures/api/closures.json: 15 stations, all three
// verdicts).
import { readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const FIXTURE = JSON.parse(readFileSync(new URL("./fixtures/api/closures.json", import.meta.url)));
const SOURCES = [
  "https://www.cbsnews.com/sanfrancisco/news/bart-could-close-15-stations-lay-off-1200-without-sales-tax-measure/",
  "https://www.cbsnews.com/sanfrancisco/news/bart-board-approves-station-closures-if-2026-sales-tax-measure-rejected/",
  "https://www.bart.gov/node/44936",
  "https://www.bart.gov/sites/default/files/2026-02/Proposed%20Alternative%20Service%20Framework%20from%20Feb%2012%202026.pdf",
  "https://sfstandard.com/2026/02/26/bart-doomsday-scenario-less-doomy/",
  "https://www.kron4.com/news/bay-area/these-are-the-bart-stations-that-could-close-under-transit-systems-worst-case-scenario/",
  "https://news.medill.northwestern.edu/chicago/several-stations-on-chopping-block-as-bart-heads-for-financial-cliff/",
  "https://localnewsmatters.org/2026/07/02/connect-bay-area-transit-tax-ballot-november-2026/",
  "https://stanforddaily.com/2026/10/07/bay-area-to-vote-on-transit-measure/",
  "https://antiochherald.com/2026/02/bart-board-votes-8-1-to-close-up-to-15-stations-if-proposed-nov-tax-measure-fails/",
  "https://www.nber.org/papers/w18757",
  "https://doi.org/10.1080/03081060.2015.1127539",
  "https://www.cbsnews.com/sanfrancisco/news/bart-strike-economic-impact-put-at-73-million-no-new-talks-set",
];

const json = (route, body, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const band = (page) => page.locator("#closures");
const cards = (page) => page.locator("[data-closure-station]");

async function openLoaded(page) {
  await page.route("**/api/closures", (route) => json(route, FIXTURE));
  await page.goto("/");
  await expect(cards(page)).toHaveCount(15);
}

test("closures: the band shows 15 stations with verdicts, rules and sources", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openLoaded(page);
  await expect(page.locator("[data-closures-group='1'] [data-closure-station]")).toHaveCount(10);
  await expect(page.locator("[data-closures-group='2'] [data-closure-station]")).toHaveCount(5);
  await expect(page.locator("[data-closures-group='1'] h3")).toHaveText("The first 10: lowest ridership");
  await expect(page.locator("[data-closures-group='2'] h3")).toHaveText("The next 5: line-end segments");
  for (const st of FIXTURE.stations) {
    const card = page.locator(`[data-closure-station="${st.code}"]`);
    await expect(card).toHaveAttribute("data-verdict", st.verdict);
    await expect(card.locator(".verdict-pill")).toHaveText(`Case to keep: ${st.verdict}`);
    await expect(card.locator("h4")).toHaveText(st.name);
    await expect(card.locator("[data-rule]")).toHaveCount(FIXTURE.rules.length);
    for (const [id, met] of Object.entries(st.criteria)) {
      await expect(card.locator(`[data-rule="${id}"]`)).toContainText(met ? ": Met" : ": Not met");
    }
  }
  const verdicts = await cards(page).evaluateAll((els) => els.map((e) => e.dataset.verdict));
  expect(new Set(verdicts)).toEqual(new Set(["strong", "mixed", "weak"]));

  const rules = page.locator("[data-closures-rules]");
  await expect(rules.locator("[data-rule]")).toHaveCount(FIXTURE.rules.length);
  const cost = page.locator("[data-closures-cost-data]");
  await expect(cost).toBeVisible();
  await expect(cost).toContainText(`${FIXTURE.stations.filter((s) => s.criteria.growing).length} of the 15`);
  for (const r of FIXTURE.rules) await expect(rules).toContainText(r.text);
  for (const text of Object.values(FIXTURE.verdicts)) await expect(rules).toContainText(text);

  const summary = page.locator("[data-closures-summary]");
  await expect(summary.locator(".stat-tile")).toHaveCount(3);
  await expect(summary).toContainText(
    `${FIXTURE.system.first_10_in_lowest_10} of the first 10 are among the 10 least-used stations in ${FIXTURE.period_year}.`,
  );
  await expect(summary).toContainText("The press reported about 12%.");

  const hrefs = await page.locator("[data-closures-sources] a").evaluateAll((as) => as.map((a) => a.href));
  for (const url of SOURCES) expect(hrefs).toContain(url);
  await expect(band(page).locator(".skeleton")).toHaveCount(0);
  await expect(page.locator("[data-closures]")).toHaveAttribute("aria-busy", "false");
});

test("closures: the not-final and neutral notes show even without data", async ({ page }) => {
  await page.route("**/api/closures", (route) =>
    json(route, { detail: { code: "warehouse_not_connected", message: "Ridership data isn't connected yet." } }, 503),
  );
  await page.goto("/");
  await expect(page.locator("[data-closures] .message")).toHaveText("Ridership data isn't connected yet.");
  const status = page.locator("[data-closures-status]");
  await expect(status).toBeVisible();
  await expect(status).toContainText("isn't final");
  await expect(status).toContainText("still has to vote");
  const neutral = page.locator("[data-closures-neutral]");
  await expect(neutral).toBeVisible();
  await expect(neutral).toContainText("doesn't take a position on");
  await expect(neutral).toContainText("measure");
  await expect(page.locator("[data-closures-caveats]")).toBeVisible();
  await expect(page.locator("[data-closures-caveats] li")).toHaveCount(5);
  await expect(page.locator("[data-closures-sources]")).toBeVisible();
  await expect(page.locator("[data-closures-sources] a")).toHaveCount(SOURCES.length);
  await expect(page.locator("[data-closures-cost]")).toContainText("47%");
  await expect(page.locator("[data-closures-cost-data]")).toBeHidden();
  await expect(band(page).locator(".skeleton")).toHaveCount(0);
  await expect(cards(page)).toHaveCount(0);
});

test("closures: 404 says the data hasn't been loaded, a server error offers Retry", async ({ page }) => {
  let status = 404;
  await page.route("**/api/closures", (route) =>
    status === 200 ? json(route, FIXTURE) : json(route, { detail: { code: "data_not_available" } }, status),
  );
  await page.goto("/");
  await expect(page.locator("[data-closures] .message")).toHaveText("This data hasn't been loaded yet.");
  status = 500;
  await page.reload();
  const retry = page.locator("[data-closures] [data-action]");
  await expect(retry).toHaveText("Retry");
  status = 200;
  await retry.click();
  await expect(cards(page)).toHaveCount(15);
});

for (const width of [320, 390, 1120]) {
  test(`closures: no horizontal scroll at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await openLoaded(page);
    await band(page).scrollIntoViewIfNeeded();
    const [scrollW, innerW] = await page.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
    expect(scrollW).toBeLessThanOrEqual(innerW);
    // nothing inside the band is wider than the screen (the body clips overflow, so check the boxes too)
    const widest = await band(page).evaluate((el) =>
      Math.max(...[...el.querySelectorAll("*")].map((e) => e.getBoundingClientRect().right)),
    );
    expect(widest).toBeLessThanOrEqual(width);
  });
}

for (const theme of ["light", "dark"]) {
  test(`closures: axe finds no violations in ${theme} mode`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("tp-theme", t), theme);
    await page.setViewportSize({ width: 1440, height: 900 });
    await openLoaded(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await band(page).scrollIntoViewIfNeeded();
    const { violations } = await new AxeBuilder({ page }).include("#closures").analyze();
    expect(violations.flatMap((v) => v.nodes.map((n) => `${v.id} ${n.target.join(" ")}: ${n.failureSummary}`))).toEqual(
      [],
    );
  });
}

test("closures: the nav links to the band", async ({ page }) => {
  await page.setViewportSize({ width: 1120, height: 900 });
  await page.goto("/");
  await expect(page.locator(".nav__links a[href='#closures']")).toHaveText("Closures");
  await expect(page.locator(".nav-overlay__links a[href='#closures']")).toHaveCount(1);
  // six links still fit in the desktop nav, left of the theme toggle
  const link = await page.locator(".nav__links a[href='#about']").boundingBox();
  const toggle = await page.locator("[data-theme-toggle]").boundingBox();
  expect(link.x + link.width).toBeLessThanOrEqual(toggle.x);
  await page.locator(".nav__links a[href='#closures']").click();
  await expect(page).toHaveURL(/#closures$/);
  await expect(page.locator("#closures-title")).toBeInViewport();
});
