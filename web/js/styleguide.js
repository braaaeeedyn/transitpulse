// Style guide (web/styleguide.html, IMPLEMENTATION_PLAN F1/F7). The token tables are rendered from css/tokens.css's
// own :root rules, so the page can't drift from the stylesheet, and the icon row uses index.html's sprite.

import { initTheme } from "./fx.js";
import { esc } from "./trends.js";

// first match wins; the last group takes whatever is left, so no token can be missed
const COLOUR_DATA = /^--(line-|map-(water|land|shoreline)$|seq-|series-|interval-fill$|gridline$)/;
const GROUPS = [
  ["Colour: interface", /^--color-/],
  ["Colour: data (maps, trains, charts and legends only)", COLOUR_DATA],
  ["Type", /^--(font|type|lh|tracking)-/],
  ["Radius", /^--radius-/],
  ["Spacing", /^--space-/],
  ["Elevation", /^--shadow-/],
  ["Motion", /^--(duration|ease)-/],
  ["Map", /^--map-/],
  ["Layout", /./],
];

/** Map of every custom property set on :root in `sheet` → [[media condition or "", value], ...], in source order. */
export function rootTokens(sheet) {
  const out = new Map();
  const walk = (rules, media) => {
    for (const rule of rules) {
      if (rule.media) walk(rule.cssRules, rule.media.mediaText);
      else if (rule.selectorText === ":root") {
        for (const name of rule.style) {
          if (!name.startsWith("--")) continue;
          if (!out.has(name)) out.set(name, []);
          out.get(name).push([media, rule.style.getPropertyValue(name).trim()]);
        }
      }
    }
  };
  walk(sheet.cssRules, "");
  return out;
}

function sample(name) {
  const v = `var(${name})`;
  if (name.startsWith("--color-") || COLOUR_DATA.test(name)) return `<span class="sg-sample" style="background: ${v}"></span>`;
  if (name.startsWith("--type-")) return `<span style="font-size: ${v}; font-weight: 700; line-height: 1.1">Aa</span>`;
  if (name.startsWith("--font-")) return `<span style="font-family: ${v}">Ag 0123</span>`;
  if (name.startsWith("--radius-")) return `<span class="sg-sample sg-sample--soft" style="border-radius: ${v}"></span>`;
  if (name.startsWith("--space-")) return `<span class="sg-bar" style="width: ${v}"></span>`;
  if (name.startsWith("--shadow-")) return `<span class="sg-sample" style="box-shadow: ${v}"></span>`;
  return "";
}

function tokenTables(tokens) {
  const groups = GROUPS.map(([title]) => [title, []]);
  for (const [name, values] of tokens) groups[GROUPS.findIndex(([, re]) => re.test(name))][1].push([name, values]);
  return groups
    .filter(([, rows]) => rows.length)
    .map(([title, rows]) => {
      const body = rows
        .map(([name, values]) => {
          const value = values.map(([media, v]) => (media ? `${esc(v)} <span class="text-body">at ${esc(media)}</span>` : esc(v))).join("<br />");
          return `<tr><th scope="row"><code>${esc(name)}</code></th><td>${value}</td><td>${sample(name)}</td></tr>`;
        })
        .join("");
      return `<h3>${esc(title)}</h3><div class="table-wrap"><table class="data-table">
        <thead><tr><th scope="col">Token</th><th scope="col">Value</th><th scope="col">Sample</th></tr></thead>
        <tbody>${body}</tbody></table></div>`;
    })
    .join("");
}

async function iconRow(el) {
  const html = await fetch("index.html").then((r) => r.text());
  const sprite = new DOMParser().parseFromString(html, "text/html").querySelector("body > svg");
  if (!sprite) return;
  document.body.prepend(document.importNode(sprite, true));
  el.innerHTML = [...sprite.querySelectorAll("symbol")]
    .map((s) => `<li><svg class="icon" aria-hidden="true"><use href="#${esc(s.id)}"/></svg><code>${esc(s.id)}</code></li>`)
    .join("");
}

initTheme(document.querySelector("[data-theme-toggle]"));
const sheet = [...document.styleSheets].find((s) => s.href?.endsWith("/css/tokens.css"));
document.querySelector("[data-tokens]").innerHTML = tokenTables(rootTokens(sheet));
iconRow(document.querySelector("[data-icons]"))
  .catch((err) => console.error(err))
  .finally(() => {
    document.documentElement.dataset.ready = "";
  });
