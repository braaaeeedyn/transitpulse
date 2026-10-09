// Ask TransitPulse in the browser (F6 + M5), with POST /api/ask mocked by page.route, so no agent or warehouse
// is needed. The streams use CRLF and multi-line data on purpose: any spec-valid stream must work.
import { expect, test } from "@playwright/test";

const sse = (events, eol = "\n") =>
  events.map(([event, data]) => `event: ${event}${eol}data: ${JSON.stringify(data)}${eol}${eol}`).join("");

const ANSWER = {
  text: "Embarcadero had the most entries.",
  columns: ["station", "entries"],
  rows: [
    ["Embarcadero", 260924],
    ["Powell Street", 258528],
  ],
  sql: "SELECT station_name AS station, SUM(entries) AS entries FROM marts.fct_station_daily LIMIT 200",
};

async function mockAsk(page, { status = 200, body = "", contentType = "text/event-stream" } = {}) {
  const requests = [];
  await page.route("**/api/ask", async (route) => {
    requests.push(route.request().postDataJSON());
    await route.fulfill({ status, contentType, body });
  });
  return requests;
}

async function ask(page, question) {
  await page.goto("/");
  await page.locator("#ask-input").fill(question);
  await page.locator("[data-ask-form] [type=submit]").click();
}

const result = (page) => page.locator("[data-ask-result]");

test("ask: streamed answer renders text, table and SQL", async ({ page }) => {
  const body = sse(
    [
      ["thinking", { message: "Understanding the question" }],
      ["sql", { sql: ANSWER.sql }],
      ["rows", { count: 2, columns: ANSWER.columns }],
      ["answer", ANSWER],
    ],
    "\r\n",
  );
  const requests = await mockAsk(page, { body: `: keep-alive\r\n\r\n${body}` });
  await ask(page, "Which station is busiest?");
  await expect(result(page).locator("h3")).toHaveText(ANSWER.text);
  await expect(result(page).locator("h3")).toBeFocused();
  await expect(result(page).locator("thead th")).toHaveText(["station", "entries"]);
  await expect(result(page).locator("tbody tr")).toHaveCount(2);
  await expect(result(page).locator("tbody tr").first().locator("td")).toHaveText(["Embarcadero", "260924"]);
  await expect(result(page).locator("tbody td.is-num")).toHaveCount(2);
  await result(page).getByText("Show SQL").click();
  await expect(result(page).locator("pre code")).toHaveText(ANSWER.sql);
  expect(requests).toEqual([{ question: "Which station is busiest?" }]);
});

test("ask: refusal shows suggestion chips", async ({ page }) => {
  const suggestions = ["Which stations had the most entries in 2025?", "How close is weekday ridership to 2019?",
    "What's the 14-day forecast for Embarcadero?"];
  // the payload split over two data: lines, joined with a newline (valid JSON either way)
  const body = `event: thinking\ndata: {"message": "Understanding the question"}\n\nevent: refusal\ndata: {"message": "I can only answer questions about BART and Bay Wheels.",\ndata: "suggestions": ${JSON.stringify(suggestions)}}\n\n`;
  const requests = await mockAsk(page, { body });
  await ask(page, "What's the weather tomorrow?");
  await expect(result(page).locator(".message")).toContainText("I can only answer questions about BART");
  await expect(result(page).locator(".message")).not.toHaveClass(/message--error/);
  const chips = result(page).locator("[data-suggest]");
  await expect(chips).toHaveText(suggestions);
  await chips.first().click(); // a chip asks its question
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1]).toEqual({ question: suggestions[0] });
});

test("ask: a stream that ends without an answer shows an error", async ({ page }) => {
  await mockAsk(page, { body: sse([["thinking", {}], ["sql", { sql: "SELECT 1" }]]) });
  await ask(page, "Which station is busiest?");
  await expect(result(page).locator(".message--error")).toContainText("stopped before answering");
  await expect(page.locator("[data-ask-form] [type=submit]")).toBeEnabled();
});

test("ask: a 422 says the question couldn't be read, not a connection problem", async ({ page }) => {
  await mockAsk(page, {
    status: 422,
    contentType: "application/json",
    body: JSON.stringify({ detail: [{ type: "string_too_long", loc: ["body", "question"] }] }),
  });
  await ask(page, "Which station is busiest?");
  await expect(result(page).locator(".message--error")).toContainText("couldn't be read");
  await expect(result(page)).not.toContainText("connection");
});

test("ask: an error event is shown as an error", async ({ page }) => {
  await mockAsk(page, {
    body: sse([["thinking", {}], ["error", { code: "sql_rejected", message: "I couldn't write a safe query." }]]),
  });
  await ask(page, "Which station is busiest?");
  await expect(result(page).locator(".message--error")).toContainText("I couldn't write a safe query.");
});
