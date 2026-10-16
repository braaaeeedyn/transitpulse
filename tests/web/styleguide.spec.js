// The style guide (web/styleguide.html, F1/F7): every token in tokens.css and every component block in
// components.css is on the page, it logs no errors, and it never scrolls sideways.
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

// comments stripped, so "DESIGN.md" in a comment isn't read as a class
const css = (name) =>
  readFileSync(new URL(`../../web/css/${name}`, import.meta.url), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "");
const TOKENS = [...new Set([...css("tokens.css").matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1]))];
// block names only: no __element, --modifier or is-* state classes
const BLOCKS = [...new Set([...css("components.css").matchAll(/\.([a-z][\w-]*)/g)].map((m) => m[1]))].filter(
  (c) => !c.includes("__") && !c.includes("--") && !c.startsWith("is-"),
);

async function open(page, errors = []) {
  page.on("console", (msg) => msg.type() === "error" && errors.push(msg.text()));
  page.on("pageerror", (err) => errors.push(String(err)));
  await page.goto("/styleguide.html");
  await page.locator("html[data-ready]").waitFor({ state: "attached" });
  return errors;
}

test("styleguide: every token in tokens.css is listed", async ({ page }) => {
  await open(page);
  expect(TOKENS.length).toBeGreaterThan(80);
  const listed = await page.locator("[data-tokens] th[scope=row] code").allTextContents();
  expect(listed.toSorted()).toEqual(TOKENS.toSorted());
  // values come from the stylesheet, including the media-query overrides
  await expect(page.locator("[data-tokens] tr", { hasText: "--color-mute" }).first()).toContainText("#767676");
  await expect(page.locator("[data-tokens] tr", { hasText: "--map-line-width" })).toContainText("(min-width: 768px)");
});

test("styleguide: every component block in components.css is used", async ({ page }) => {
  await open(page);
  expect(BLOCKS).toEqual(expect.arrayContaining(["btn", "chip", "card", "stat-tile", "tooltip", "data-table", "toast"]));
  const missing = await page.evaluate((blocks) => blocks.filter((c) => !document.querySelector(`main .${c}`)), BLOCKS);
  expect(missing).toEqual([]);
  expect(await page.locator("[data-icons] li").count()).toBeGreaterThan(10);
});

test("styleguide: no console errors", async ({ page }) => {
  const errors = await open(page);
  await page.waitForLoadState("networkidle");
  expect(errors).toEqual([]);
});

test("styleguide: no horizontal scroll from 320 to 2560 px", async ({ page }) => {
  await open(page);
  for (const width of [320, 390, 768, 1024, 1440, 1920, 2560]) {
    await page.setViewportSize({ width, height: 900 });
    const [scrollW, innerW] = await page.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
    expect(scrollW, `${width}px`).toBeLessThanOrEqual(innerW);
  }
});
