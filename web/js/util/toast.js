// The page's one toast (DESIGN.md §7: bottom-centre, ink, hides after 4 s, for "Copied" and similar confirmations).
// The element is looked up on each call so modules that import this still load under node:test (no document).
let timer = 0;

export function toast(text) {
  const el = document.querySelector("[data-toast]");
  if (!el) return;
  el.textContent = text;
  el.classList.add("is-visible");
  clearTimeout(timer);
  timer = setTimeout(() => el.classList.remove("is-visible"), 4000);
}
