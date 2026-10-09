// Ask TransitPulse (IMPLEMENTATION_PLAN F6). Sends the question to POST /api/ask and renders the streamed
// progress events (thinking → sql → rows → answer, or a refusal/error). While the agent is off the API answers 503
// and this shows a friendly "not connected yet" message.

const STEPS = { thinking: "Understanding the question", sql: "Writing SQL", rows: "Running query", answer: "Writing the answer" };

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function message(text, { error = false, chips = [] } = {}) {
  const icon = error ? "i-circle-alert" : "i-info";
  return `<div class="message${error ? " message--error" : ""}" style="margin-top: var(--space-2xl)">
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

export function initAsk(card, result) {
  const form = card.querySelector("[data-ask-form]");
  const input = form.querySelector("input");
  const submit = form.querySelector("[type=submit]");
  let busy = false;

  async function ask(q) {
    if (busy || !q.trim()) return;
    busy = true;
    submit.disabled = true;
    result.innerHTML = `<div style="margin-top: var(--space-2xl)"><p class="text-body">Asking: <strong>${esc(q)}</strong></p>
      <ol class="text-body" data-steps style="margin: var(--space-md) 0 0; padding-left: 1.25rem"></ol></div>`;
    const steps = result.querySelector("[data-steps]");
    const fail = (text) => {
      result.innerHTML = message(text, { error: true });
    };
    try {
      let res;
      try {
        res = await fetch("api/ask", {
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
          "The analyst isn't connected yet. In the meantime, explore the live train map below.",
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
            return;
          }
          if (event === "answer") {
            result.innerHTML = renderAnswer(q, data);
            result.querySelector("h3")?.focus();
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

  // suggestion chips (in the card and in any message) fill the field and submit
  document.addEventListener("click", (e) => {
    const chip = e.target.closest("[data-suggest]");
    if (!chip) return;
    input.value = chip.textContent.trim();
    ask(input.value);
  });
}

function renderAnswer(q, data) {
  const cols = data.columns ?? [];
  const rows = data.rows ?? [];
  const table = cols.length
    ? `<div class="table-wrap"><table class="data-table"><thead><tr>${cols.map((c) => `<th scope="col">${esc(c)}</th>`).join("")}</tr></thead>
       <tbody>${rows.map((r) => `<tr>${r.map((v) => `<td${typeof v === "number" ? ' class="is-num"' : ""}>${esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`
    : "";
  const sql = data.sql
    ? `<details><summary class="btn btn--subtle">Show SQL</summary><pre class="sql-block" style="margin-top: var(--space-md)"><code>${esc(data.sql)}</code></pre></details>`
    : "";
  return `<article class="card" style="margin-top: var(--space-2xl); display: grid; gap: var(--space-lg)">
    <p class="text-body">${esc(q)}</p>
    <h3 tabindex="-1">${esc(data.text)}</h3>${table}${sql}</article>`;
}
