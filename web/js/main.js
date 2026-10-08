// Page bootstrap: nav behaviour, the Ask card, the live map, the Trends band and the Forecast explorer.

import { initAsk } from "./ask.js";
import { initForecast } from "./forecast.js";
import { initMap } from "./map/map.js";
import { initTrends } from "./trends.js";

// --- nav: hairline once scrolled -------------------------------------------------------------------
const nav = document.querySelector("[data-nav]");
const onScroll = () => nav.classList.toggle("is-scrolled", window.scrollY > 4);
window.addEventListener("scroll", onScroll, { passive: true });
onScroll();

// --- nav overlay (< 1120 px): focus trapped, Esc closes, body scroll locked -------------------------
const menu = document.querySelector("[data-menu]");
const openBtn = document.querySelector("[data-menu-open]");
const closeBtn = document.querySelector("[data-menu-close]");

function focusables() {
  return [...menu.querySelectorAll("a, button")];
}

function openMenu() {
  menu.hidden = false;
  requestAnimationFrame(() => menu.classList.add("is-open"));
  document.body.classList.add("is-scroll-locked");
  openBtn.setAttribute("aria-expanded", "true");
  closeBtn.focus();
}

function closeMenu({ restoreFocus = true } = {}) {
  menu.classList.remove("is-open");
  document.body.classList.remove("is-scroll-locked");
  openBtn.setAttribute("aria-expanded", "false");
  menu.hidden = true;
  if (restoreFocus) openBtn.focus();
}

openBtn.addEventListener("click", openMenu);
closeBtn.addEventListener("click", () => closeMenu());
menu.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeMenu();
  if (e.key !== "Tab") return;
  const f = focusables();
  const first = f[0];
  const last = f[f.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
});
menu.addEventListener("click", (e) => {
  if (e.target.closest("a")) closeMenu({ restoreFocus: false });
});
matchMedia("(min-width: 1120px)").addEventListener("change", (e) => {
  if (e.matches && !menu.hidden) closeMenu({ restoreFocus: false });
});

// --- "Ask a question" links scroll to and focus the input ------------------------------------------
for (const a of document.querySelectorAll("[data-focus-ask]")) {
  a.addEventListener("click", (e) => {
    e.preventDefault();
    const input = document.getElementById("ask-input");
    input.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
    input.focus({ preventScroll: true });
  });
}

// --- toast -----------------------------------------------------------------------------------------
const toastEl = document.querySelector("[data-toast]");
let toastTimer = 0;
export function toast(text) {
  toastEl.textContent = text;
  toastEl.classList.add("is-visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.remove("is-visible"), 4000);
}

initAsk(document.querySelector("[data-ask]"), document.querySelector("[data-ask-result]"));
initMap(document.querySelector("[data-map]"));
initTrends(document.querySelector("[data-trends]"));
initForecast(document.querySelector("[data-forecast]"));
