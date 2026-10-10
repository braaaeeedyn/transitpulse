// Where the API lives. Same origin by default (`api/...` relative to the page). Pages hosted elsewhere (the
// portfolio copy at braedynthompson.com/transitpulse/) carry <meta name="tp-api-base" content="https://…/">,
// written by pipeline/webexport.py --api-base, and call the API on Cloud Run instead.
export function apiBase(doc = globalThis.document) {
  const base = doc?.querySelector?.('meta[name="tp-api-base"]')?.content?.trim();
  return base ? (base.endsWith("/") ? base : `${base}/`) : "";
}

/** URL for an API path such as "api/kpis". */
export function apiUrl(path, doc = globalThis.document) {
  return apiBase(doc) + path;
}
