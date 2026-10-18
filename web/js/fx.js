// Motion and delight (redesign round 1): numbers that count up when they scroll into view, sections that rise in,
// the nav's current section, the hero's live strip and the mascot's hello. Decoration only: every number is set in
// the DOM first, so the page is complete without this running (and under prefers-reduced-motion nothing moves).

import { getKpis } from "./trends.js";

const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

// --- count-up ---------------------------------------------------------------------------------------
const NUM = /-?\d[\d,]*(\.\d+)?/;

/** Animates the first number in el's text from 0 to its value over ~900 ms, keeping its decimals and formatting. */
export function countUp(el) {
  const text = el.textContent;
  const m = NUM.exec(text);
  if (!m || reduced()) return;
  const target = Number(m[0].replace(/,/g, ""));
  if (!Number.isFinite(target)) return;
  const decimals = m[1] ? m[1].length - 1 : 0;
  const grouped = m[0].includes(",");
  const fmt = (v) =>
    v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals, useGrouping: grouped });
  const start = performance.now();
  const step = (now) => {
    const t = Math.min(1, (now - start) / 900);
    const eased = 1 - (1 - t) ** 3;
    el.textContent = text.slice(0, m.index) + fmt(target * eased) + text.slice(m.index + m[0].length);
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

const counted = new WeakSet();
const countObserver = new IntersectionObserver(
  (entries) => {
    for (const e of entries) {
      if (!e.isIntersecting || counted.has(e.target)) continue;
      counted.add(e.target);
      countObserver.unobserve(e.target);
      countUp(e.target);
    }
  },
  { threshold: 0.6 },
);

/** Every [data-count] on the page, now or rendered later, counts up when it scrolls into view. */
export function initCounts() {
  const watch = (root) => {
    if (root.nodeType !== 1) return;
    if (root.matches("[data-count]")) countObserver.observe(root);
    for (const el of root.querySelectorAll("[data-count]")) countObserver.observe(el);
  };
  watch(document.body);
  new MutationObserver((muts) => {
    for (const m of muts) for (const n of m.addedNodes) watch(n);
  }).observe(document.body, { childList: true, subtree: true });
}

// --- reveal on scroll -------------------------------------------------------------------------------
export function initReveal() {
  const targets = document.querySelectorAll(".band .section-head, .band .container > :not(.section-head), .hero__actions");
  if (reduced() || !targets.length) return;
  const io = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        e.target.classList.add("is-in");
        io.unobserve(e.target);
      }
    },
    { rootMargin: "0px 0px -10% 0px" },
  );
  for (const el of targets) {
    // anything already on screen stays put: no flash on load
    if (el.getBoundingClientRect().top < innerHeight) continue;
    el.classList.add("reveal");
    io.observe(el);
  }
}

// --- nav: which section is on screen ----------------------------------------------------------------
export function initScrollSpy() {
  const links = [...document.querySelectorAll(".nav__links a[href^='#']")];
  const sections = links.map((a) => document.querySelector(a.hash)).filter(Boolean);
  if (!sections.length) return;
  const io = new IntersectionObserver(
    (entries) => {
      const top = entries.filter((e) => e.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!top) return;
      for (const a of links) {
        if (a.hash === `#${top.target.id}`) a.setAttribute("aria-current", "true");
        else a.removeAttribute("aria-current");
      }
    },
    { rootMargin: "-40% 0px -50% 0px", threshold: [0, 0.1, 0.5] },
  );
  for (const s of sections) io.observe(s);
}

// --- hero live strip --------------------------------------------------------------------------------
export function initHeroLive(root) {
  if (!root) return;
  const trains = root.querySelector("[data-live-trains]");
  const summary = document.querySelector("[data-map-summary]");
  let lastCount = null;
  const sync = () => {
    const m = /(\d+) trains running/.exec(summary.textContent);
    const n = m ? Number(m[1]) : /No trains/.test(summary.textContent) ? 0 : null;
    if (n === null || n === lastCount) return;
    trains.textContent = String(n);
    if (lastCount === null) countUp(trains); // the first value counts up; later ticks just update
    lastCount = n;
  };
  new MutationObserver(sync).observe(summary, { childList: true, characterData: true, subtree: true });
  sync();
  getKpis().then(
    (kpis) => {
      const rec = kpis.tiles?.find((t) => t.id === "recovery");
      const el = root.querySelector("[data-live-recovery]");
      if (rec?.value !== undefined && rec?.value !== null) {
        el.textContent = `${Math.round(rec.value * 100)}%`;
        countUp(el);
      }
      if (kpis.data_through) root.querySelector("[data-live-through]").textContent = formatThrough(kpis.data_through);
    },
    () => {},
  );
}

function formatThrough(iso) {
  const [y, mo, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, mo - 1, d)).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

// --- the mascot says hello once per session ---------------------------------------------------------
export function initMascotHello(launcher) {
  if (!launcher || reduced()) return;
  try {
    if (sessionStorage.getItem("tp-hello")) return;
    sessionStorage.setItem("tp-hello", "1");
  } catch {
    return; // no storage: no bubble, rather than one on every page load
  }
  setTimeout(() => launcher.classList.add("has-bubble"), 1800);
  setTimeout(() => launcher.classList.remove("has-bubble"), 7000);
}

// --- dark mode ---------------------------------------------------------------------------------------
// The theme lives on <html data-theme>; an inline script in index.html sets it before paint. The toggle stores
// the choice (localStorage) and tells the map to re-read its colours (tp:theme).
export function initTheme(button) {
  if (!button) return;
  const root = document.documentElement;
  const sync = () => {
    const dark = root.dataset.theme === "dark";
    button.setAttribute("aria-pressed", String(dark));
    button.setAttribute("aria-label", dark ? "Light mode" : "Dark mode");
  };
  button.addEventListener("click", () => {
    root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
    try {
      localStorage.setItem("tp-theme", root.dataset.theme);
    } catch {
      // no storage: the choice lasts for this page only
    }
    sync();
    document.dispatchEvent(new CustomEvent("tp:theme"));
  });
  sync();
}

// --- the hero's departure board ---------------------------------------------------------------------
// The map publishes the six soonest arrivals (tp:arrivals). Rows keep their place between ticks, so the board
// reads like a station display: the minutes tick down and a train that arrives slides off.
export function initBoard(board) {
  if (!board) return;
  const rows = board.querySelector("[data-board-rows]");
  const clock = board.querySelector("[data-board-clock]");
  const esc = (v) => String(v).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  document.addEventListener("tp:arrivals", (e) => {
    const { rows: next, clock: now, live } = e.detail;
    clock.textContent = live ? now : `${now} (replay)`;
    board.hidden = next.length === 0;
    rows.innerHTML = next
      .map(
        (r) => `<li class="board__row">
          <span class="swatch" style="background: var(--line-${esc(r.line)})" title="${esc(r.lineName)}"></span>
          <span class="board__dest"><strong>${esc(r.next)}</strong><span class="board__to">to ${esc(r.dest)}</span></span>
          <span class="board__eta num">${r.mins < 1 ? "now" : `${r.mins} min`}</span>
        </li>`,
      )
      .join("");
  });
}

// --- the footer mascot hops when poked --------------------------------------------------------------
export function initMascotHop(button) {
  if (!button) return;
  button.addEventListener("click", () => {
    button.classList.remove("is-hopping");
    void button.offsetWidth; // restart the animation on a quick second poke
    button.classList.add("is-hopping");
  });
}
