// Ask TransitPulse (IMPLEMENTATION_PLAN F6). Sends the question to POST /api/ask and renders the streamed
// progress events (thinking → sql → rows → answer). Until the agent exists (M5) the API answers 503 and this shows
// a friendly "not connected yet" message.

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

/** Parse a text/event-stream body into {event, data} objects. */
async function* readEvents(res) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i);
      buf = buf.slice(i + 2);
      let event = "message";
      let data = "";
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      yield { event, data: data ? JSON.parse(data) : null };
    }
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
    try {
      const res = await fetch("api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ question: q }),
      });
      if (res.status === 503) {
        result.innerHTML = message(
          "The analyst isn't connected yet. In the meantime, explore the live train map below.",
        );
        return;
      }
      if (res.status === 429) {
        result.innerHTML = message("Lots of questions right now. Try again in a minute.", { error: true });
        return;
      }
      if (!res.ok || !res.body) throw new Error(String(res.status));
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
      result.innerHTML = message("Something went wrong reaching the analyst. Check your connection and try again.", {
        error: true,
      });
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
