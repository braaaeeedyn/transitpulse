// The Ask TransitPulse stream parser (web/js/ask.js), run with Node's built-in runner:
//   node --test tests/web/
import assert from "node:assert/strict";
import { test } from "node:test";

import { createEventParser, parseEventStream } from "../../web/js/ask.js";

const STREAM = [
  ["thinking", { message: "Understanding the question" }],
  ["sql", { sql: "SELECT 1" }],
  ["answer", { text: "One.", columns: ["n"], rows: [[1]], sql: "SELECT 1" }],
];

const encode = (eol) => STREAM.map(([e, d]) => `event: ${e}${eol}data: ${JSON.stringify(d)}${eol}${eol}`).join("");
const decoded = (events) => events.map(({ event, data }) => [event, JSON.parse(data)]);

test("parses LF and CRLF event streams", () => {
  for (const eol of ["\n", "\r\n", "\r"]) {
    assert.deepEqual(decoded(parseEventStream(encode(eol))), STREAM, JSON.stringify(eol));
  }
  // the same stream cut into every possible pair of chunks, including between the CR and LF of a CRLF
  const crlf = encode("\r\n");
  for (let i = 0; i <= crlf.length; i++) {
    const p = createEventParser();
    const events = [...p.push(crlf.slice(0, i)), ...p.push(crlf.slice(i))];
    assert.deepEqual(decoded(events), STREAM, `split at ${i}`);
  }
  // no space after the colon, and an unfinished event at the end is not dispatched
  assert.deepEqual(parseEventStream('event:sql\ndata:{"sql":"x"}\n\nevent: answer\ndata: {}'), [
    { event: "sql", data: '{"sql":"x"}' },
  ]);
});

test("joins multi-line data with newlines", () => {
  const events = parseEventStream('event: answer\ndata: {"text":\ndata: "two lines"}\n\n');
  assert.equal(events.length, 1);
  assert.equal(events[0].data, '{"text":\n"two lines"}');
  assert.deepEqual(JSON.parse(events[0].data), { text: "two lines" });
  // an event with no event: field is a "message"; one with no data is not dispatched
  assert.deepEqual(parseEventStream("data: 1\n\nevent: ping\n\n"), [{ event: "message", data: "1" }]);
});

test("ignores comment lines", () => {
  const events = parseEventStream(': keep-alive\n\nevent: thinking\n: a comment inside an event\ndata: {"message":"hi"}\n\n');
  assert.deepEqual(events, [{ event: "thinking", data: '{"message":"hi"}' }]);
});
