// F1/F3/F7 browser checks: fits every screen, map sizes itself, controls and fallbacks work.
import { expect, test } from "@playwright/test";

const WIDTHS = [320, 390, 768, 1024, 1440, 1920];
const RUSH_HOUR = new Date("2026-10-07T08:15:00-07:00"); // a Wednesday
const NIGHT = new Date("2026-10-07T03:00:00-07:00"); // between last and first trains

async function open(page, time = RUSH_HOUR) {
  await page.clock.install({ time });
  await page.goto("/");
  await page.locator("[data-map-summary]").waitFor({ state: "attached" });
  await expect(page.locator(".map-loading")).toHaveCount(0);
}

for (const width of WIDTHS) {
  test(`no horizontal scroll and a correctly sized map at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await open(page);
    const [scrollW, innerW] = await page.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
    expect(scrollW).toBeLessThanOrEqual(innerW);

    // canvas backing store = CSS size × devicePixelRatio, so trains are sharp and line up with the SVG
    const sizes = await page.evaluate(() => {
      const stage = document.querySelector(".map-stage").getBoundingClientRect();
      const c = document.querySelector(".map-canvas");
      return { w: stage.width, h: stage.height, cw: c.width, ch: c.height, dpr: devicePixelRatio };
    });
    expect(sizes.cw).toBe(Math.round(sizes.w * sizes.dpr));
    expect(sizes.ch).toBe(Math.round(sizes.h * sizes.dpr));
  });
}

test("canvas follows the container on resize", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page);
  await page.setViewportSize({ width: 600, height: 900 });
  await page.waitForTimeout(200);
  const ok = await page.evaluate(() => {
    const r = document.querySelector(".map-stage").getBoundingClientRect();
    return document.querySelector(".map-canvas").width === Math.round(r.width * devicePixelRatio);
  });
  expect(ok).toBe(true);
});

test("trains are running at rush hour and the summary says so", async ({ page }) => {
  await open(page);
  await expect(page.locator("[data-map-summary]")).toContainText(/\d+ trains running on \d lines/);
  await expect(page.locator(".map-notice")).toBeHidden();
});

test("out of service hours shows the notice and Jump to 8 AM starts a replay", async ({ page }) => {
  await open(page, NIGHT);
  await expect(page.locator(".map-notice")).toBeVisible();
  await expect(page.locator("[data-notice-text]")).toContainText("Service resumes at");
  await page.locator("[data-jump]").click();
  await expect(page.locator(".map-notice")).toBeHidden();
  await expect(page.locator("[data-clock-time]")).toHaveText("8:00 AM");
  await expect(page.locator("[data-now]")).toHaveAttribute("aria-pressed", "false");
});

test("map: an expired timetable says so", async ({ page }) => {
  // a Monday at 8 AM, after every service in web/data/schedule.json has ended
  await open(page, new Date("2027-02-01T08:00:00-08:00"));
  await expect(page.locator(".map-notice")).toBeVisible();
  await expect(page.locator("[data-notice-text]")).toHaveText(
    "This site's BART timetable ended on Jan 10, 2027. Positions can't be shown until it's updated.",
  );
  await expect(page.locator("[data-notice-text]")).not.toContainText("No trains running");
  await expect(page.locator("[data-jump]")).toBeHidden();
});

test("list view shows a table of trains", async ({ page }) => {
  await open(page);
  await page.locator("[data-view=list]").click();
  await expect(page.locator(".map-list")).toBeVisible();
  expect(await page.locator(".map-list tbody tr").count()).toBeGreaterThan(10);
  await expect(page.locator("[data-list-count]")).toContainText("trains running");
});

test("speed buttons switch to replay and Now returns to live", async ({ page }) => {
  await open(page);
  await page.locator("[data-speed='60']").click();
  await expect(page.locator("[data-clock-status]")).toHaveText("Replay 60×");
  await page.locator("[data-now]").click();
  await expect(page.locator("[data-clock-status]")).toHaveText("Live schedule");
});

test("tapping a train shows its tooltip", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page);
  // find a train position from the page and click it
  const pos = await page.evaluate(() => {
    const r = document.querySelector(".map-stage").getBoundingClientRect();
    return { x: r.left, y: r.top };
  });
  // probe a grid of points until a train tooltip appears (positions depend on the schedule)
  let found = false;
  for (let y = 60; y < 560 && !found; y += 6) {
    for (let x = 300; x < 900 && !found; x += 6) {
      await page.mouse.move(pos.x + x, pos.y + y);
      const t = page.locator(".tooltip");
      if ((await t.isVisible()) && /to /.test(await t.textContent())) found = true;
    }
  }
  expect(found).toBe(true);
  await expect(page.locator(".tooltip")).toContainText(/Next: .+ · (arriving|\d+ min)|Arrived at/);
});

test("zoom buttons enable and disable at the limits", async ({ page }) => {
  await open(page);
  await expect(page.locator("[data-zoom-out]")).toBeDisabled();
  await page.locator("[data-zoom-in]").click();
  await expect(page.locator("[data-zoom-out]")).toBeEnabled();
  await expect(page.locator(".map-stage")).toHaveClass(/is-zoomed/);
});

test("phone menu opens, traps focus and closes with Escape", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  await page.locator("[data-menu-open]").click();
  await expect(page.locator("[data-menu]")).toBeVisible();
  await expect(page.locator("[data-menu-close]")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator("[data-menu]")).toBeHidden();
  await expect(page.locator("[data-menu-open]")).toBeFocused();
});

test("asking a question while the agent is offline shows a friendly message", async ({ page }) => {
  await open(page);
  await page.locator("[data-suggest]").first().click();
  await expect(page.locator("[data-ask-result]")).toContainText("isn't connected yet");
});

test("map data failing to load shows a retry message instead of a blank box", async ({ page }) => {
  await page.route("**/data/network.json", (r) => r.fulfill({ status: 500 }));
  await page.goto("/");
  await expect(page.locator(".map-card .message--error")).toContainText("didn't load");
});

test("respects reduced motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await open(page);
  await expect(page.locator("[data-map-summary]")).toContainText("trains running");
});
