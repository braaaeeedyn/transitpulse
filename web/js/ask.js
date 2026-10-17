// Ask TransitPulse (IMPLEMENTATION_PLAN F6). Sends the question to POST /api/ask and renders the streamed
// progress events (thinking → sql → rows → answer, or a refusal/error). While the agent is off the API answers 503
// and this shows a friendly "not connected yet" message. The last 5 answers and refusals (never errors) are kept in
// sessionStorage and shown in the Ask panel after a reload; "Show SQL" has a copy button.

import { apiUrl } from "./util/api.js";
import { toast } from "./util/toast.js";

const STEPS = { thinking: "Understanding the question", sql: "Writing SQL", rows: "Running query", answer: "Writing the answer" };

const HISTORY_KEY = "tp-ask-history";
const HISTORY_MAX = 5;
const HISTORY_ROWS = 20;

/** One stored Q&A in a fixed shape. Also used on read: storage is untrusted, so nothing is taken on trust. */
function historyEntry(e) {
  return {
    question: String(e.question),
    text: String(e.text),
    columns: Array.isArray(e.columns) ? e.columns.map(String) : [],
    rows: Array.isArray(e.rows) ? e.rows.filter(Array.isArray).slice(0, HISTORY_ROWS) : [],
    sql: typeof e.sql === "string" ? e.sql : "",
  };
}

/** The stored Q&As, newest first. Bad or missing storage reads as no history. */
export function readHistory(storage = globalThis.sessionStorage) {
  try {
    const list = JSON.parse(storage?.getItem(HISTORY_KEY) ?? "[]");
    if (!Array.isArray(list)) return [];
    return list
      .filter((e) => typeof e?.question === "string" && typeof e?.text === "string")
      .slice(0, HISTORY_MAX)
      .map(historyEntry);
  } catch {
    return [];
  }
}

/** Puts a Q&A first in the stored list (at most 5) and returns the new list. */
export function remember(entry, storage = globalThis.sessionStorage) {
  const list = [historyEntry(entry), ...readHistory(storage)].slice(0, HISTORY_MAX);
  try {
    storage?.setItem(HISTORY_KEY, JSON.stringify(list));
  } catch {
    // storage full or switched off: the history is a convenience, the answer on screen still stands
  }
  return list;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function message(text, { error = false, chips = [] } = {}) {
  const icon = error ? "i-circle-alert" : "i-info";
  return `<div class="message${error ? " message--error" : ""}" style="margin-top: var(--space-lg)">
    <p class="message__text"><svg class="icon" aria-hidden="true"><use href="#${icon}"/></svg>${esc(text)}</p>
    ${chips.length ? `<div class="chip-row">${chips.map((c) => `<button class="chip" type="button" data-suggest>${esc(c)}</button>`).join("")}</div>` : ""}
  </div>`;
}

/**
 * Incremental text/event-stream parser (WHATWG server-sent events): lines end in LF, CRLF or CR; a blank line ends
 * an event; `data:` lines are joined with "\n"; lines starting with ":" are comments; one leading space after the
 * colon is dropped. push(text) returns the events completed so far as {event, data} (data is the raw string).
 * An event left unfinished when the stream ends is discarded, as the spec says.
 */
export function createEventParser() {
  let buf = "";
  let event = "";
  let data = [];
  function line(text, out) {
    if (text === "") {
      if (data.length) out.push({ event: event || "message", data: data.join("\n") });
      event = "";
      data = [];
      return;
    }
    if (text.startsWith(":")) return;
    const i = text.indexOf(":");
    const field = i < 0 ? text : text.slice(0, i);
    let value = i < 0 ? "" : text.slice(i + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return {
    push(chunk) {
      buf += chunk;
      const out = [];
      for (;;) {
        const m = buf.search(/[\r\n]/);
        if (m < 0) break;
        if (buf[m] === "\r" && m === buf.length - 1) break; // a CR at the end may be half of a CRLF
        line(buf.slice(0, m), out);
        buf = buf.slice(m + (buf[m] === "\r" && buf[m + 1] === "\n" ? 2 : 1));
      }
      return out;
    },
    /** The stream ended: a final CR still ends its line. */
    end() {
      const out = [];
      if (buf.endsWith("\r")) line(buf.slice(0, -1), out);
      buf = "";
      return out;
    },
  };
}

/** Parse a whole event-stream string (tests, and small bodies). */
export function parseEventStream(text) {
  const parser = createEventParser();
  return [...parser.push(text), ...parser.end()];
}

/** Read a fetch Response's text/event-stream body as {event, data} objects, data parsed as JSON. */
async function* readEvents(res) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const parser = createEventParser();
  for (;;) {
    const { value, done } = await reader.read();
    const events = done
      ? [...parser.push(decoder.decode()), ...parser.end()]
      : parser.push(decoder.decode(value, { stream: true }));
    for (const { event, data } of events) yield { event, data: data ? JSON.parse(data) : null };
    if (done) break;
  }
}

// The static export (pipeline/webexport.py) marks its index.html with <meta name="tp-mode" content="static">:
// it's served without the API, so there is nothing to POST a question to.
export const isStaticSite = () => document.querySelector('meta[name="tp-mode"]')?.content === "static";

export function initAsk(card, result, history) {
  const form = card.querySelector("[data-ask-form]");
  const input = form.querySelector("input");
  const submit = form.querySelector("[type=submit]");
  let busy = false;

  // stored answers render through the same escaping path as a live answer
  function showHistory(list) {
    if (!history) return;
    history.innerHTML = list.length
      ? `<h2 class="eyebrow" style="margin-top: var(--space-lg)">Earlier answers</h2>${list.map((e) => renderAnswer(e.question, e)).join("")}`
      : "";
  }

  // the newest stored entry is the one on screen, so the list below it starts at the second
  const keep = (entry) => showHistory(remember(entry).slice(1));

  async function ask(q) {
    if (busy || !q.trim()) return;
    input.value = ""; // a chat box: the question is echoed above the answer
    if (isStaticSite()) {
      result.innerHTML = message(
        "The analyst needs TransitPulse's live server, which this public snapshot doesn't run. " +
          "Every number on this page is real warehouse data, as of the date shown in each section.",
      );
      return;
    }
    busy = true;
    submit.disabled = true;
    result.innerHTML = `<div style="margin-top: var(--space-lg)"><p class="text-body">Asking: <strong>${esc(q)}</strong></p>
      <ol class="text-body" data-steps style="margin: var(--space-md) 0 0; padding-left: 1.25rem"></ol></div>`;
    const steps = result.querySelector("[data-steps]");
    const fail = (text) => {
      result.innerHTML = message(text, { error: true });
    };
    try {
      let res;
      try {
        res = await fetch(apiUrl("api/ask"), {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
          body: JSON.stringify({ question: q }),
        });
      } catch (err) {
        console.error(err);
        fail("Something went wrong reaching the analyst. Check your connection and try again.");
        return;
      }
      if (res.status === 503) {
        result.innerHTML = message(
          "The analyst isn't connected yet. In the meantime, explore the live train map.",
        );
        return;
      }
      if (res.status === 429) {
        fail("Lots of questions right now. Try again in a minute.");
        return;
      }
      if (res.status >= 400 && res.status < 500) {
        fail("That question couldn't be read. Try rephrasing it in under 300 characters.");
        return;
      }
      if (!res.ok || !res.body) {
        fail("The analyst ran into a problem. Try again in a moment.");
        return;
      }
      try {
        for await (const { event, data } of readEvents(res)) {
          if (STEPS[event]) {
            const li = document.createElement("li");
            li.textContent = STEPS[event];
            steps.appendChild(li);
          }
          if (event === "refusal" || event === "error") {
            result.innerHTML = message(data.message, { error: event === "error", chips: data.suggestions ?? [] });
            if (event === "refusal") keep({ question: q, text: data.message });
            return;
          }
          if (event === "answer") {
            result.innerHTML = renderAnswer(q, data);
            result.querySelector("h3")?.focus();
            keep({ ...data, question: q });
            return;
          }
        }
      } catch (err) {
        console.error(err);
        fail("The connection to the analyst dropped before it answered. Try again.");
        return;
      }
      // the stream ended without an answer, a refusal or an error
      fail("The analyst stopped before answering. Try asking again.");
    } finally {
      busy = false;
      submit.disabled = false;
    }
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    ask(input.value);
  });

  document.addEventListener("click", (e) => {
    // "Copy SQL" in any answer, current or earlier; the toast is the aria-live confirmation
    const copy = e.target.closest("[data-copy-sql]");
    if (copy) {
      const sql = copy.closest("details").querySelector("code").textContent;
      Promise.resolve()
        .then(() => navigator.clipboard.writeText(sql))
        .then(
          () => toast("Copied"),
          () => toast("Couldn't copy. Select the SQL to copy it."),
        );
      return;
    }
    // suggestion chips (in the card and in any message) fill the field and submit
    const chip = e.target.closest("[data-suggest]");
    if (!chip) return;
    input.value = chip.textContent.trim();
    ask(input.value);
  });

  if (!isStaticSite()) showHistory(readHistory());
}

function renderAnswer(q, data) {
  const cols = data.columns ?? [];
  const rows = data.rows ?? [];
  const table = cols.length
    ? `<div class="table-wrap"><table class="data-table"><thead><tr>${cols.map((c, i) => `<th scope="col"${typeof rows[0]?.[i] === "number" ? ' class="is-num"' : ""}>${esc(c)}</th>`).join("")}</tr></thead>
       <tbody>${rows.map((r) => `<tr>${r.map((v) => `<td${typeof v === "number" ? ' class="is-num"' : ""}>${esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`
    : "";
  const sql = data.sql
    ? `<details><summary class="btn btn--subtle">Show SQL</summary><pre class="sql-block" style="margin-top: var(--space-md)"><code>${esc(data.sql)}</code></pre>
       <button class="icon-btn" type="button" aria-label="Copy SQL" data-copy-sql style="margin-top: var(--space-sm)"><svg class="icon" aria-hidden="true"><use href="#i-copy"/></svg></button></details>`
    : "";
  // DESIGN.md §7 answer: the question echo in body-md-strong, the answer as a display-md heading (the panel is narrow)
  return `<article class="card" style="margin-top: var(--space-lg); display: grid; gap: var(--space-lg)">
    <p style="font-weight: 500; line-height: var(--lh-tight)">${esc(q)}</p>
    <h3 tabindex="-1" style="font-size: var(--type-display-md); line-height: var(--lh-display-md)">${esc(data.text)}</h3>${table}${sql}</article>`;
}
