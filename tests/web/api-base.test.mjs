// web/js/util/api.js: same-origin by default, or the live API named in <meta name="tp-api-base">.
import assert from "node:assert/strict";
import { test } from "node:test";

import { apiBase, apiUrl } from "../../web/js/util/api.js";

const docWith = (content) => ({
  querySelector: (sel) => (sel === 'meta[name="tp-api-base"]' && content !== undefined ? { content } : null),
});

test("same origin when the page has no tp-api-base", () => {
  assert.equal(apiBase(docWith(undefined)), "");
  assert.equal(apiUrl("api/kpis", docWith(undefined)), "api/kpis");
});

test("calls the live API named in tp-api-base, with or without a trailing slash", () => {
  assert.equal(apiUrl("api/forecast/EMBR", docWith("https://tp.a.run.app/")), "https://tp.a.run.app/api/forecast/EMBR");
  assert.equal(apiUrl("api/ask", docWith(" https://tp.a.run.app ")), "https://tp.a.run.app/api/ask");
});

test("an empty tp-api-base means same origin", () => {
  assert.equal(apiUrl("api/kpis", docWith("")), "api/kpis");
});

test("works without a document (node)", () => {
  assert.equal(apiUrl("api/kpis", undefined), "api/kpis");
});
