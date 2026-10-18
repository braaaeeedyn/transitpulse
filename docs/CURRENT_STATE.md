# TransitPulse: current state

> **Scope of this file:** how the application works *right now*, and nothing else. No history, no plans.
> It is rewritten whenever behaviour changes. History lives in [`DEVLOG.md`](DEVLOG.md); the task list in
> [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).
>
> **Last verified:** 2026-10-14, on Windows 11 (the live pages, `/api/health` and `/api/findings` answer 200).
> **Live at https://braedynthompson.com/transitpulse/**: the pages are
> published by the portfolio's GitHub Pages (`portfolio/static/transitpulse/`, exported with `tasks.py export
> --api-base`) and call the API on Cloud Run (https://transitpulse-api-etumz4pfva-uw.a.run.app) across origins
> (CORS allows `https://braedynthompson.com`). The Dagster pipeline runs on the Oracle VM against BigQuery.

---

## 1. What exists and runs

| Part | State | How to run |
|---|---|---|
| Website (static, `web/`) | **Working**: live train map, ridership tiles + charts, forecast explorer, Ask panel with a train mascot (history, Copy SQL), Findings band, a Station closures band, an optional Looker Studio card, Open Graph tags, and a style guide at `/styleguide.html` | `uv run python tasks.py api` → http://localhost:8000 |
| API (`api/`) | **Working**: serves the site; data endpoints (incl. `GET /api/closures`) read the local DuckDB or BigQuery marts when a warehouse is configured; `POST /api/ask` streams the agent's answer when `TP_AGENT_ENABLED=true`, 503 otherwise (the default) | same as above |
| Ask TransitPulse agent (`api/agent/`) | **Working** locally: LangGraph text-to-SQL with guardrails, 5 retrieved example queries in the SQL prompt (the M5 A/B winner), fake / Ollama / Gemini LLM, optional Langfuse | `TP_AGENT_ENABLED=true TP_AGENT_LLM=ollama uv run --group agent python tasks.py api` |
| Agent eval + A/B (`eval/`) | **Working**: 66 in-scope questions with gold SQL + 10 out-of-scope; arms A (no examples) and B (5 examples), compared by `eval.ab` ([`AB_TEST.md`](AB_TEST.md)) | `uv run python tasks.py eval --llm ollama --arm A\|B`, then `uv run --group agent python -m eval.ab` |
| Map data build (`pipeline/webdata/`) | **Working** | `uv run python tasks.py web-data` |
| Spark cleaning job (`pipeline/spark/`) | **Working** (Docker on Windows, native on Linux) | `uv run python tasks.py spark` |
| Bay Wheels download + cleaning (`pipeline/baywheels.py`) | **Working** (DuckDB, no Spark) | `uv run python tasks.py baywheels` |
| dbt warehouse models (`dbt/transitpulse/`) | **Working**: `local` (DuckDB) has BART + Bay Wheels; `dev` (BigQuery) has BART 2018–2025 and Bay Wheels 2018 → 2026-09 | `uv run python tasks.py stations` then `uv run python tasks.py dbt` (`DBT_TARGET=dev` for BigQuery) |
| Forecast (`ml/forecast/`) | **Working** locally and on BigQuery (LightGBM, 14 days, every station, split-conformal calibrated band) | `uv run python tasks.py forecast` |
| Dagster orchestration (`pipeline/definitions.py`) | **Working** in `local` and `gcp` mode, run from this PC | `uv run python tasks.py dagster` → http://localhost:3000 |
| Oracle VM deployment (`deploy/oracle/`) | **Running**: Dagster daemon + UI on the VM (2 OCPU / 12 GB), on `1fd224a`+, `gcp` mode. Sensors and schedules start as RUNNING (until 2026-10-14 the schedules had never been switched on, so nothing scheduled had run) | [`ORACLE_VM.md`](ORACLE_VM.md) |
| Terraform (`infra/terraform/`) | M0 **applied** to GCP project `transitpulse-511002` (33 resources). `cloudrun.tf` + `wif.tf` (10 more resources) are **applied** | see `infra/README.md` |
| Container image (`Dockerfile`) | **Built, tested and pushed by `deploy.yml`** on every push to `main` (non-root, 119 MB compressed) | `uv run python tasks.py image` |
| Local stack (`docker-compose.yml`) | **Working**: the API image with the agent on, an Ollama container and a one-shot model pull (see §5 "`make up`") | `make up` / `uv run python tasks.py up` → http://localhost:8000 |
| Cloud Run service `transitpulse-api` (us-west1) | **Live** (Terraform applied; image `api:<commit sha>`, deployed by `deploy.yml`). Ask agent **on** since 2026-10-16 (`agent_enabled = true` in the local tfvars), on `gemini-3.5-flash-lite` | [`CLOUD_RUN.md`](CLOUD_RUN.md) |
| Cloud Run deploy (`.github/workflows/deploy.yml`) | **On** (`DEPLOY_ENABLED=true`): every push to `main` builds, smoke-tests, pushes and deploys (first seen for `ab55544`, 2026-10-14) | [`CLOUD_RUN.md`](CLOUD_RUN.md) |
| Pages at braedynthompson.com/transitpulse/ | **Live**: the portfolio repo publishes `static/transitpulse/`; re-export only when the website code changes | [`CLOUD_RUN.md`](CLOUD_RUN.md) §5 |
| Load test (`load/`) | **Working** locally: Locust at 1/10/25 users on a fixture warehouse with the fake LLM | `uv run python tasks.py load` |
| CI (`.github/workflows/ci.yml`) | **Runs on GitHub** (python, spark, web, container, terraform jobs) | — |
| eBART causal study (`analysis/causal/`) | **Done** (pre-registered + Amendment 1; one real run): verdict **new**, served by `GET /api/findings` and the Findings band; write-up in [`FINDINGS.md`](FINDINGS.md). A post-hoc trend-adjusted estimate (not pre-registered) is in `trend_adjusted.json` and FINDINGS.md only | `uv run python tasks.py causal`; `uv run --group ml python -m analysis.causal.trend_adjusted` (see §5 "Causal study") |
| BI (`bi/README.md`) | **Guide only**: Looker Studio and Power BI build steps, DAX measures and a check week (2025-W39) whose values a localdata test checks. The dashboards themselves are not built | — |
| Fine-tuning (M6) | **Not implemented**; deferred to its own build loop (owner decision 13 in [`OWNER_STEPS.md`](OWNER_STEPS.md)) | — |
| Owner steps | The remaining steps that need accounts, tools, devices or decisions, in order: [`OWNER_STEPS.md`](OWNER_STEPS.md) | — |

---

## 2. Data flow (local mode)

```
bart.gov GTFS zip ──► pipeline/webdata ──► web/data/{network,schedule,land}.json ──► browser map
        │
        └──────────► pipeline/stations ──► data/parquet/bart_stations/stations.csv ─┐
                                                                                     ▼
bart.gov OD CSV.gz ─► data/raw/bart_od/ ─► Spark clean_bart_od ─► data/parquet/bart_od/year=/month=/*.parquet
                                                                                     │
S3 baywheels-data ──► data/raw/baywheels/*.zip ─► DuckDB clean ─► data/parquet/baywheels_trips/year=/month=/
                                                                                     │
                                       dbt (DuckDB, data/transitpulse.duckdb) ◄──────┘
                                       staging ─► snapshot ─► core (dims/facts) ─► marts
                                                                                     │
                       ml/forecast ◄── marts.fct_station_daily       API (read-only) ◄┘
                            └──► marts.forecast_station_daily + ml.forecast_runs ──► API ──► site
```

- Everything under `data/` is generated and gitignored. `web/data/*.json` is generated **and committed**
  (the site needs it to run).
- In `gcp` mode (`TP_PIPELINE_MODE=gcp`, `DBT_TARGET=dev`) the same assets upload to GCS
  (`gs://transitpulse-511002-raw`) and load BigQuery (`raw.bart_od`, `raw.bart_stations`, and the code path for
  `raw.baywheels_trips`); dbt then builds `staging` and `marts` in BigQuery, and the forecast asset writes its two
  tables to BigQuery. Spark runs are queued one at a time (`pipeline/dagster.yaml`).
- Years BART hasn't published yet (currently 2026: an empty gzip) are skipped: the three yearly assets succeed with
  `published: false` and a warning.

### Data currently loaded
| Dataset | Where | Coverage | Size |
|---|---|---|---|
| BART hourly origin-destination | **BigQuery** `raw.bart_od` → `marts.*` | 2018–2025 (2020 is missing 4 days in BART's file) | 67,770,440 rows; 4.2 GB logical |
| BART hourly origin-destination | local DuckDB facts/marts | 2018–2025, the same as BigQuery (2020 is missing 4 days) | 67,770,440 rows in `fct_trips_hourly`; 143,958 in `fct_station_daily`; `data/transitpulse.duckdb` 369 MB |
| Bay Wheels trips | local Parquet / DuckDB (`stg_baywheels_trips`) | 2019 (Ford GoBike schema) and 2025 (Lyft schema) | 6,901,983 trips (2,506,867 + 4,395,116); 236 MB Parquet |
| Bay Wheels trips | BigQuery `raw.baywheels_trips` → `marts.fct_bike_trips_daily`, `mart_bikes_vs_trains` | 2018 → 2026-09 | 25,989,969 trips; 3,165 days; 105 months |
| Station forecast | local DuckDB `marts.forecast_station_daily`, `ml.forecast_runs` | 2026-01-01 → 2026-01-14 (from data through 2025-12-31, trained on 2024-01-02 → 2025-12-31), 50 stations, with `lower`/`upper` | 700 rows; run `fc-20261009T131810Z-a3cda6` is the latest |
| Station forecast | BigQuery `marts.forecast_station_daily`, `ml.forecast_runs` | same window; written by the VM's weekly run with the pre-calibration code (p10/p50/p90 only) until the VM pulls this code | 700 rows |
| BART GTFS | web/data, `raw.bart_stations` | feed version 72 (service 2026-08-10 → 2027-01-10) | 50 stations, 3,762 rail trips |

---

## 3. The website

### Page (single page, `web/index.html`)
1. **Nav**: sticky; links (the one for the section on screen is underlined, `aria-current`), a sun/moon theme
   toggle (`[data-theme-toggle]`, `localStorage` `tp-theme`, default = system preference; an inline `<script>` in
   `<head>` applies it before paint; the map re-reads its colours on `tp:theme`) and the "Ask a question" pill; a
   4 px pulse stripe of the line colours underneath. Below 1120 px the links move into a full-screen menu
   (focus trapped, Esc closes, body scroll locked). Below 600 px the CTA becomes a search icon.
2. **Hero**: headline (last word on a line-colour stripe), lead, a live strip (`[data-hero-live]`: trains moving
   now from the map's summary, % of 2019 and the data date from `/api/kpis`, counted up), "Ask TransitPulse"
   (opens the panel) and "See the live map"; in the second column from 1120 px (below the copy otherwise) a
   **departure board** (`[data-board]`): the six soonest arrivals anywhere, which the map publishes every 10 s as
   `tp:arrivals` (line swatch, next stop, destination, minutes; hidden when nothing is running).
   **Ask panel** (`#ask-panel`, at the end of `<body>`): opened by the corner launcher (`.ask-launcher`, the mascot
   symbol `#i-mascot`), the nav's "Ask a question" buttons and the hero button (all `[data-ask-open]`, with
   `aria-expanded`); ✕ or Esc closes it and focus returns to the opener (`web/js/main.js`). A 440 px side panel under
   the nav from 768 px, not modal; full screen below, where it locks the page scroll. It holds a greeting, 6 suggestion
   chips (each in `api/agent/suggested.py`, or the forecast one), the answer, earlier answers, and the question input
   with a send button. The input clears when a question is sent. Submitting POSTs to `/api/ask` and reads
   the streamed answer (`web/js/ask.js`):
   - Progress steps are listed as `thinking` / `sql` / `rows` / `answer` events arrive. The answer renders in a card:
     the question (body-md-strong), the answer as a `display-md` heading (focused), a table (numeric columns
     right-aligned, header included) and a "Show SQL" disclosure.
   - **Copy SQL:** inside the disclosure, an icon button ("Copy SQL") writes the query with
     `navigator.clipboard.writeText`; the toast (`aria-live`) says "Copied", or "Couldn't copy…" when the browser
     refuses.
   - **History:** each answer or refusal (never an error) is stored in `sessionStorage` (`tp-ask-history`): question,
     answer text, columns, the first 20 rows and the SQL, at most 5, newest first. After a reload they render in
     the Ask panel as "Earlier answers" through the same escaping as a live answer; while asking, the list shows the
     stored ones except the newest, which is on screen. Stored entries count as untrusted: they are reshaped on read
     (wrong types dropped) and every field is escaped. Storage that is full, off or corrupt reads as no history. In
     static mode (no server) nothing is stored or shown.
   - A refusal shows its message and suggestion chips (a chip asks its question); an `error` event shows the message.
   - 503 → "The analyst isn't connected yet…" (the default: the agent is off); 429 → "Lots of questions right now";
     other 4xx (e.g. 422) → "That question couldn't be read…"; 5xx → "The analyst ran into a problem…"; a failed
     request → "Check your connection"; a dropped stream or one that ends without answer/refusal/error → an error
     message instead of a half-finished step list.
   - The stream parser follows the SSE spec: LF, CRLF or CR line ends, multi-line `data:` joined with a newline,
     comment lines ignored, chunks split anywhere.
3. **Live map** (see below).
4. **Trends** (`web/js/trends.js`, see below).
5. **Forecast** explorer (`web/js/forecast.js`, see below).
6. **Findings** (black band, `web/js/findings.js`, see below).
7. **Station closures** (`#closures`, `web/js/closures.js`, see below).
8. **About**: three FAQ rows (`<details>`).
9. **Footer**: data sources with licences (Bay Wheels links its Data License Agreement); links to GitHub, the eBART,
   A/B and station closures write-ups and the style guide; credits; "Data through Dec 31, 2025." from the KPIs (left out without them).

**`<head>`:** title, description, favicon, and Open Graph tags: `og:title`, `og:description`, `og:type` website,
`og:url` `https://braedynthompson.com/transitpulse/`, `og:image` `https://braedynthompson.com/transitpulse/img/og.png`
(absolute, as crawlers need) with its width 1200, height 630 and alt text, and `twitter:card`
`summary_large_image`. `web/img/og.png` is the train map at 8:00 AM on a Wednesday (104 KB), written by
`tasks.py screenshots`. `<meta name="tp-looker-url" content="">` holds the dashboard URL (see Trends band).

### Forecast explorer: v1.1 additions
- Under the caption, two **badges** (`[data-fc-badges]`, height reserved): the fortnight's busiest and quietest
  expected days (max/min p50) with their values.
- A 🎲 **"Surprise me"** chip (`[data-fc-random]`) loads a random station other than the one on screen.

### Findings band
`web/js/findings.js` reads `GET /api/findings` (through `apiUrl`, so the exported pages call Cloud Run). Every
number comes from the JSON:
- **Verdict sentence:** one per pre-registered code (new / moved / fewer / inconclusive), hedged: each says what the
  data are "consistent with" and none says eBART "brought" or "caused" anything. For **new** (the committed result):
  "The whole line from Concord to Antioch carried a few percent more riders than the comparison stations would
  predict: consistent with eBART bringing a modest number of new riders, on top of the many it moved from the old
  stations to the new ones."
- **Two figures:**
  - "Whole line, Concord → Antioch (incl. new stations)": the corridor % with its 95% interval and "about N more
    entries a day" (rounded to tens);
  - "Pittsburg/Bay Point, North Concord, Concord": the legacy % with its interval.

  Signed percentages use a true minus sign.
- **Hedge note** (`VERDICTS_HEDGE_NOTE`, muted `findings__note` at the caption size): shown under the figures only
  when the verdict is `new`. It is fixed copy, not from the JSON, because the run is final: the effect is largest in
  the first months and the monthly data show the line already rising before the opening, so part of it may be trend.
- **Caution sentence:** shown only when `caution` is true (separate from the hedge note).
- **Method line:** "Difference-in-differences against 34 BART stations far from the line, pre-registered on Oct 9,
  2026. 95% intervals from placebo tests." The count and the date come from the JSON. It ends with a link to
  `docs/FINDINGS.md` on GitHub.
- **Event-study charts:** two white `card`s (legacy, corridor), side by side from 768 px and stacked below.
  - Each draws, in %, the `interval-fill` placebo band, gridlines with a `color-mute` zero line, a dashed "Opening"
    marker, and the 2 px ink line with a dot per 4-week bin.
  - The x axis is "weeks since opening". Each card has a visually hidden table of the bins.
- **States:** skeletons of the loaded size while loading; 404 → "The analysis is in progress."; any other error →
  an error message with Retry.

### Station closures band
A white band after Findings (`<section id="closures" data-accent="beige">`, nav link "Closures" in both nav lists,
so the desktop nav has 6 links), about the stations BART could close from July 2027 if the Connect Bay Area measure
fails. Write-up: [`STATION_CLOSURES.md`](STATION_CLOSURES.md).
- **Static copy** (in `index.html`, shown with or without data): the context (the Connect Bay Area measure, SB 63,
  on the November 3, 2026 ballot in five counties; the BART board's Alternative Service Plan adopted 8–1 on
  February 26, 2026; it applies only if the measure fails and no other money is found; up to 15 closures from July
  2027); `[data-closures-status]` (the stations are the ones named in BART staff's February 2026 presentation as
  reported by the press; the list "isn't final" because the board "still has to vote" on stations or segments);
  `[data-closures-neutral]` (TransitPulse "doesn't take a position on the measure"; the verdicts weigh ridership,
  recovery and distance); `[data-closures-cost]` "What closing would cost" (left border in the band's accent): a
  data line `[data-closures-cost-data]` (hidden until the API answers; `costSentence`: the share of weekday trips at
  the 15, how many grew on the previous year, how many meet Distance and the farthest one's miles) and three cited
  findings: the 2003 Los Angeles transit strike (peak-hour highway delay +47%, Anderson 2014), the 2013 BART strike
  (Bay Bridge travel times and volumes nearly doubled on the worst day, roads parallel to BART as bad as a typical
  week's worst day, regional freeways little changed; Moylan, Foti and Skabardonis 2016) and the Bay Area Council
  Economic Institute's ~$73M a day in lost productivity, with a caption that these were whole-system shutdowns;
  `[data-closures-caveats]` "What the data can't see" (cost, who rides, parking/bus/shuttle links,
  transfers such as Caltrain at Millbrae and air travellers at OAK, whether riders switch or stop riding;
  `[data-closures-sfo]`: SFO isn't on the list and the sources don't say how it would be served, the page counts it as
  still open, so it is the nearest open station for San Bruno and Millbrae, and if it lost service both would meet the
  Distance rule; distances are straight lines; a link to the write-up);
  `[data-closures-sources]` (13 links with publisher and date); a caption naming BART's ridership data.
- **From `GET /api/closures`** (`web/js/closures.js`, every number from the API; strings escaped with `esc`):
  - `[data-closures-summary]`: three `stat-tile`s with sentences built from the data: "9 of the first 10 are among
    the 10 least-used stations in 2025. Also among them: Milpitas, which isn't on the list."; "12.6% of weekday trips
    in 2025 start or end at the first 10. The press reported about 12%."; "24.1% … at one of all 15."
  - `[data-closures-rules]`: "How the verdicts work": the four rules (Riders, Recovery, Distance, Growing) and the
    verdict mapping, as text from the API (the page never states a threshold itself), and a line saying the first three
    were set before the section was built and Growing was added afterwards.
  - Two groups (`[data-closures-group]`, h3): "The first 10: lowest ridership" and "The next 5: line-end segments"
    (closing those as well would close all the listed stations on the three named segments, listed from the data).
  - One `card` per station (`[data-closure-station=CODE]`, `data-verdict`, in an `auto-fit` grid, min 280 px):
    name (h4) and segment; a **verdict pill** "Case to keep: strong / mixed / weak" (ink / outlined / soft grey,
    never green/red); weekday trips and rank of 50 from the fewest; % of 2019 with BART's %; change vs 2024 (▲/▼);
    the nearest station still open and its miles; the top 3 destinations with shares; each rule as "Met" / "Not met"
    (with a decorative ✓/✗).
  - Locally: strong 6 (Pittsburg Center, Orinda, San Bruno, Antioch, Pittsburg/Bay Point, Dublin/Pleasanton),
    mixed 7, weak 2 (Oakland International Airport, North Concord/Martinez).
- **States:** skeletons (3 tiles, a rules card, 3 cards) while loading; 503 → "Ridership data isn't connected yet.";
  404 → "This data hasn't been loaded yet."; other errors → an error message with Retry.
- **Styles:** `web/css/fx.css` (closures section: the band layout, station cards, `.verdict-pill`, the beige accent),
  tokens only, so dark mode needs nothing extra.

### Live map: what if stations close? (`web/js/map/whatif.js`)
- A card under the legend (`[data-whatif]`): presets "Today's map", "Close the first 10", "Close all 15", then one
  chip per listed station (`[data-whatif-code]`, `aria-pressed="true"` = closed, struck through). `AT_RISK` holds
  the list; `tests/web/whatif.test.mjs` checks it equals the dbt seed.
- Closed stations get no marker, no label and no hit target (`renderNetwork(…, closed)`); the track stays. Trains
  are the same trips at the same times at every open station: `schedule.closedStops` marks each pattern's closed
  stops (never a trip's first or last), and `tripPosition(…, skip)` moves a train from the last open stop's departure
  to the next open stop's arrival without dwelling, spreading the time over the hops by their scheduled running
  times. "Next stop" (tooltip, list view, departure board) is the next open one.
- The clock pill adds "· what if: N closed"; the hero board's clock adds "· what if". A status line says how many are
  closed and, once `/api/closures` answers, the share of weekday trips that start or end at them (exact for the
  presets, "up to" the summed station shares for a custom pick). The map works without the API.

### Live map: v1.1 additions
- **Legend filter:** each legend entry is a toggle (`[data-legend-line]`, `aria-pressed`). One pressed line sets
  `data-focus-line` on the map card: other lines' track paths (`data-line`) fade to 15% and `drawTrains` paints
  their trains grey (`focusLine`/`dim`). Pressing it again clears.
- **Station card:** the station tooltip shows, when `/api/stations/{code}/summary` has answered, a 2×2 grid
  (`.tooltip__stats`): entries on the latest day, % of 2019, the 28-day weekday average and the peak hour with its
  share, then "See its forecast →". The old one-line sentence stays as visually-hidden text (`[data-station-entries]`).

### Trends band
- Loads `/api/kpis`, `/api/trends/ridership` and (in parallel, optional) `/api/trends/bikes-vs-trains`. `/api/kpis` is
  fetched once per page (`getKpis()`), and the map's text alternative and the footer reuse that response; Retry
  fetches it again.
- **While loading:** skeletons of the final size; tiles and charts don't shift when the data arrives.
- **"Data through Dec 31, 2025. Tiles cover the 28 days to that date."** (caption, `mute`).
- **Four `stat-tile`s** (`auto-fit` grid: 1 column on phones, 4 on desktop), each with a value, a delta line and an
  ⓘ button that reveals the definition:
  - Recovery vs 2019
  - Average daily entries (▲/▼ % vs a year earlier, when that year is loaded)
  - Peak-hour share (▲/▼ pts vs the same ISO weeks of 2019)
  - Busiest station (+ its share of entries)

  Deltas use ink arrows, never green/red. Locally: 38%, 115,501, 10.9% (▼ 0.9 pts vs 2019), Powell Street (9.9%).
- **"Ridership since 2019"** chart card: monthly average daily entries as an inline SVG sized to its container
  (re-drawn on resize; 3 y-ticks and every other year below 600 px). The line breaks at months with no data
  (locally 2020–2024). A takeaway sentence sits above it and a visually hidden table holds the numbers.
- **"Bikes and trains"** chart card: BART entries per day (solid black) and Bay Wheels trips per day (dashed grey),
  each as % of the same month in 2019. The legend names both; below 600 px card width it moves under the chart.
- **States:**
  - 503 → "Ridership numbers will appear here once the data pipeline is connected." (info message).
  - Any other failure → error message + Retry.
  - Empty marts → one-sentence message.
  - Bike data missing (404) → only the bikes card shows a message; the BART parts stay.
- **Dashboard card** (`initDashboard`): only when `<meta name="tp-looker-url">` holds an `https:` URL; empty or
  anything else renders nothing. It is a chart card titled "Dashboard" under the bikes card, independent of the API.
  On cards at least 768 px wide (a container query) it shows the URL as given in an `iframe` (`loading="lazy"`,
  4:3 `aspect-ratio`, a title); narrower cards show an "Open dashboard" pill link instead. The live pages have no
  URL yet (owner step, `bi/README.md`).

### Trends band: v1.1 additions
- Both line charts have a **crosshair readout** (`renderLineChart`'s `readout` option, `attachReadout`): a dashed
  rule at the nearest month, a dot per series and an ink box with the month and values; pointer events are assigned
  (not added) so a resize redraw doesn't stack handlers. The hidden tables remain the accessible version.

### Forecast explorer
- **Station picker:** an ARIA combobox matching names or codes ("mac" → MacArthur, "12" → 12th St Oakland). A
  click or tap on a station on the live map picks it too (a `tp:station` event on `document`), without scrolling.
  ↑/↓ moves through the options, Enter picks, Esc closes the list. Below it, chips for Embarcadero, Montgomery St,
  Powell St, 12th St Oakland and MacArthur (the selected chip is outlined). Embarcadero loads by default.
- **Chart card:** station name; a caption about the first Tuesday in the forecast, with the year and in the past
  tense ("For Tue, Jan 6, 2026 the model expected about 14,200 entries; calibrated model range
  10,500–16,800."); the last 28 days of actuals (solid), the 14-day p50 forecast (dashed) and the published band
  (`lo`–`hi` from the API, `interval-fill`); a legend; a visually hidden table of the 14 days (with the year).
- **What the band is called** depends on the API's `model.interval`:
  - calibrated and held 75–85% of back-test days → "80% range";
  - calibrated but outside 75–85% → "calibrated model range" (the drawn `lo`/`hi` are p10/p90 widened, so it is
    never called the 10th–90th percentile); the source line says "the calibrated model range (the model's
    10th–90th percentile, widened using earlier back-test weeks)" and the hidden table's headers are "Calibrated
    model range: low/high";
  - not calibrated → "model range (10th–90th percentile)".

  The caption, legend, table headers and the chart's text alternative all use the same label. Locally (calibrated,
  73%) it is the calibrated model range; production (uncalibrated, 70%) is the model range (10th–90th percentile).
- **Source line:** "Forecast from data through Dec 31, 2025. It covers Jan 1–14, 2026, the 14 days after the latest
  ridership BART has published.", the model's back-test error vs the baseline's, then what the band is and how often
  it held the actual value against the 80% target, adding "so it is narrower than it should be" below 75% or "so it
  is wider than needed" above 85%.
- **Section heading:** "A 14-day forecast, station by station" (it doesn't say "from today").
- **Layout:** picker beside the chart from 768 px; stacked on phones.
- **States:**
  - 503 → "Forecasts will appear here once the forecasting model has run."
  - 404 → "There's no forecast for X yet." + "Try another station", which focuses the search box.
  - Other errors → Retry.

### Motion layer (`web/js/fx.js`, `web/css/fx.css`)
Decoration only, off under `prefers-reduced-motion`: `[data-count]` numbers count up when scrolled into view (a
MutationObserver catches ones rendered later); `.band` children and section heads get `.reveal` (a 28 px slide, no
fade) when below the fold and `.is-in` when they enter; an IntersectionObserver marks the nav's current section; the
Ask launcher's mascot bobs and shows "Ask me anything about BART" once per session (`sessionStorage` `tp-hello`);
the footer mascot hops when clicked; `/` outside a field opens Ask. Section accents: `data-accent` on each `<section>`
sets `--accent` (map blue, trends green, forecast orange, findings yellow, closures beige, about red), drawn as a dot before the
eyebrow; the Findings band has a line-colour top border.

### Live map: how it works
- **Data**: `network.json` (50 stations, 51 track edges with their lines in lane order, label hints),
  `schedule.json` (11 service calendars, 34 stop patterns, 55 timing profiles, 3,762 trips, in minutes),
  `land.json` (Bay Area land polygons). 88 KB total.
- **Positions are scheduled, not live.** For the current Pacific time, `schedule.js` picks the services running on
  that date (weekday rules + holiday exceptions), includes the previous day's after-midnight trips, and interpolates
  each running trip linearly in time between its departure and next arrival. Trains dwell at stations between
  arrival and departure.
- **Rendering**: the SVG (land, track, stations, labels) and the canvas (trains) share one pixel coordinate space
  sized to the container. A `ResizeObserver` re-fits the network on every size change and resizes the canvas to
  container × `devicePixelRatio`.
- **Shared track** is drawn as parallel lanes (fixed order: yellow, red, green, blue, orange, airport), each line
  offset to the west/south side by lane index. Each train sits in its own line's lane.
- **Trains**: pills filled with the line colour, 1 px ink outline, pointing along the track. Length =
  `clamp(6px, 1.2% of map width, 14px)`. The selected train is 1.5× with an ink halo.
- **Stations**: white circles; on maps ≥ 600 px wide, transfer stations are capsules spanning all lanes.
- **Labels**: below 600 px map width only 9 hub stations are labelled. Above that, labels are placed greedily and
  any that would overlap a label, station or track are left out (reachable by hover/tap and the List view).
- **Map shape**: 1:1 on phones, 4:3 from 768 px, 16:9 from 1120 px, never taller than 80% of the viewport.
- **Controls**: clock ("8:15 AM · Wed, Oct 7 · Live schedule"; time only on narrow maps); Map/List toggle; zoom −/+
  (5 levels; drag to pan when zoomed); Now (live); time scrubber 4:00 AM → 2:30 AM; replay speed 1×/10×/60×;
  play/pause. Floating over the map when the map is ≥ 720 px wide, stacked under it otherwise.
- **Interaction**: hover (mouse) or tap shows a tooltip. Train: "Yellow line to SFO Airport / Next: 16th St Mission ·
  2 min". Station: name + lines and, once its summary has loaded (one request per station, cached in the page),
  "Entries on Dec 31, 2025: 4,956 (17% of 2019)". With no warehouse (503) or on an error there's no numbers line.
  Tap elsewhere to dismiss.
- **Map → forecast:** clicking or tapping a station (not hovering) pins its tooltip and selects it in the forecast
  explorer; the page doesn't scroll. The station tooltip ends with a "See its forecast" link to `#forecast`, the
  only part of a tooltip that takes clicks (24 px tall, 44 px on touch). Tooltips are rewritten only when their
  text changes, so the link stays clickable while trains move.
- **List view**: table of running trains (line, destination, next stop, minutes), refreshed every 5 s.
- **Out of service** (current feed: last train ends 1:52 AM; first departs 4:28 AM weekdays, 5:28 AM Saturdays,
  7:28 AM Sundays): a card says when service resumes, with *Jump to 8:00 AM*.
- **Outside the timetable** (before the first service's start or after the last one's end, counting added dates;
  the bundled feed ends **Jan 10, 2027**): the card says "This site's BART timetable ended on Jan 10, 2027. Positions
  can't be shown until it's updated." (or "starts on …"), without the Jump button.
- **Performance**: redraws ~4×/s at 1×, ~20×/s at 10×, every frame at 60×; stops while off-screen or in a hidden tab.
- **Accessibility**: a polite live region announces "N trains running on K lines at h:mm" once a minute, followed by
  "Busiest station in the latest data: Powell Street." from the KPIs' busiest-station tile (never "right now": the
  ridership data ends Dec 31, 2025; left out when the KPIs are unavailable); reduced
  motion → positions update every 30 s with no animation; all controls are buttons ≥ 44 px on touch; skip link.
- **Failure**: if the map data can't load, the map area shows an error message with Retry.

### Design system
`web/css/tokens.css` mirrors `docs/DESIGN.md` **v1.1.3**: sizes are in rem on a fluid root size (`html` in
`base.css`: 16px up to ~1500px wide, 20px at 2560px, so large screens scale up rather than leaving a 1200px strip;
only hairlines, focus rings and the map's stroke tokens are px); in dark mode the ink surfaces (Findings band,
footer, departure board, chart readout, `card--ink`) stay dark grey with white text; the v1.0.1 base (black/white interface, Inter 400/500/700,
pills for controls, 16 px cards) plus a **dark palette** under `:root[data-theme="dark"]` and the v1.1
motion/delight layer in `web/css/fx.css` + `web/js/fx.js` (pulse stripe, live hero strip, departure board,
count-ups, scroll reveal, scroll-spy, section accents, legend filter, station cards, chart readout,
forecast badges, mascot, dark-mode toggle; see DESIGN.md's changelog). Chart, trends, forecast and dashboard
styles are in `web/css/charts.css`. Deviations awaiting v1.1 are the numbered "v1.1 list" in `DESIGN_BACKLOG.md` (19 items).
- **Style guide** (`web/styleguide.html` + `web/js/styleguide.js`, linked from the footer, `noindex`): each text
  token on the surfaces DESIGN.md §2 allows; type samples; tables of every custom property, read from
  `tokens.css`'s own `:root` rules (media-query overrides included, with a sample swatch, size, radius, bar or
  shadow); the icon sprite, copied from `index.html`; and every component block in `components.css`.
- **Accessibility tests:** axe's `color-contrast` rule finds 0 violations on the page with every section loaded
  (390 and 1440 px) and on the style guide (`tests/web/a11y.spec.js`). No token value needed changing.
- **Lighthouse** (`tests/web/lighthouse.mjs`, `tasks.py lighthouse`): starts its own server (local DuckDB when
  present), runs the default mobile config N times in Playwright's Chromium and prints the median-performance run.
  Last result (3 runs): performance 98, accessibility 100, best practices 100, LCP 2.3 s, CLS 0. `--assert` gates
  90/95/95. Not in CI, because performance scores on shared runners vary.

---

## 4. API (`api/`)

| Method | Path | Current behaviour |
|---|---|---|
| GET | `/` and static files | serves `web/`. Cache: `/fonts/*` 1 year, `/data/*` 1 day, everything else `no-cache`. Responses over 1 KB are gzipped when the client accepts it (pages and JSON alike; the `text/event-stream` of `/api/ask` never is) |
| GET | `/healthz` | `{"ok": true}` |
| GET | `/api/kpis` | `{data_through, window:{start,end,days}, tiles:[{id,label,value,unit,delta,delta_label,definition}], source}` over the 28 days ending at the latest date in `mart_kpis_daily` |
| GET | `/api/trends/ridership` | `{data_through, rows:[{month_start, days, avg_daily_entries, avg_service_weekday_recovery}], source}` from `mart_ridership_monthly` |
| GET | `/api/trends/bikes-vs-trains` | `{rows:[{month_start, bart_entries, bike_trips, bart_avg_daily_entries, bike_avg_daily_trips, bart_index_2019, bike_index_2019, bikes_per_1000_bart_entries}], source}`; 404 `data_not_available` if the mart doesn't exist |
| GET | `/api/stations/{code}/summary` | `{code, name, data_through, entries, recovery_ratio, avg_weekday_entries_28d, peak_hour, peak_hour_share}` for the station's latest day |
| GET | `/api/forecast/{code}` | `{code, name, data_through, forecast_start, forecast_end, generated_at, forecast:[{date,p10,p50,p90,lo,hi}] ×14, actuals:[{date,entries}] ×28, model:{mae, baseline_mae, mae_diff_ci, interval_coverage, interval:{method, nominal, coverage, coverage_ci, calibrated}}}`; 404 `forecast_not_available` if there's no forecast for a known station. Reads both forecast-table schemas (see Forecast below); every run-log column is optional (missing → `null`, `mae_diff_ci` is `null` unless both bounds exist) |
| GET | `/api/findings` | the eBART study's `api/data/findings.json` (path: `TP_FINDINGS_PATH`), read once per process and returned unchanged, `Cache-Control: public, max-age=86400`. Never touches the warehouse (works with `TP_WAREHOUSE=none`); a missing or invalid file → **404** `findings_not_available`. Included in the static export (`pipeline/webexport.py`) |
| GET | `/api/closures` | `{period_year, baseline_year, data_through, system:{stations, recovery_pct, share_first_10, share_all_15, lowest_10:[{code,name,listed}], first_10_in_lowest_10}, rules:[{id,text}] ×4, verdicts:{strong,mixed,weak}, stations:[{code, name, group, segment, weekday_trips, weekday_entries, weekday_exits, rank_lowest, share_of_trips, recovery_pct, change_vs_prev_year, nearest_open:{code,name,miles}, destinations:[{code,name,share}] ×3, criteria:{riders,recovery,distance,growing}, points, verdict}] ×15, source}` from `mart_station_closures`, `mart_closure_destinations` and `mart_closure_scenarios`; stations ordered by group, then weekday trips. The rules are module constants in `api/routes/data.py` (`CLOSURE_RULES`): **riders** = `rank_lowest > 10`; **recovery** = whole-percent recovery (half up) ≥ BART's whole-percent recovery, null = not met; **distance** = nearest open station ≥ 3.0 mi (rounded to 0.1, half up); **growing** = change vs the previous year,
rounded half up to 0.1%, above 0. 3–4 met = strong, 2 = mixed, 0–1 = weak. Cached an hour; 503 without a warehouse; **404** `data_not_available` when a mart is missing or no listed station has data. Locally ~11 KB, ~140 ms cold, ~3 ms warm. In the static export |
| POST | `/api/ask` | body `{"question": str (1–300)}`. Agent off (default): **503** `agent_unavailable`. On: `text/event-stream` (below); **429** `rate_limited` (with `Retry-After: 60`) or `agent_busy` before the stream starts; 422 for an empty/too-long question |
| GET | `/api/docs` | OpenAPI UI |

- Every data endpoint answers **503** `{"code": "warehouse_not_connected"}` when no warehouse is configured.
  Codes that don't match `^[A-Z0-9]{4}$` or aren't in the data get **404** `{"code": "unknown_station"}`.
  Errors are under `detail` (FastAPI's format).
- **Warehouse** (`api/warehouse.py`), chosen by `TP_WAREHOUSE`:
  - `none` (default): no warehouse; every data endpoint answers 503. If `TP_WAREHOUSE` is unset but
    `TP_GCP_PROJECT` is set, the default is `bigquery`.
  - `duckdb`: reads `TP_DUCKDB_PATH` (default `data/transitpulse.duckdb`, relative to the repo). A read-only
    connection is opened per query and closed straight away.
  - `bigquery`: reads `` `TP_GCP_PROJECT.marts.*` `` with typed query parameters, a 100 MB `maximum_bytes_billed`
    cap per query and location `us-west1`.

  The app never looks for the DuckDB file on its own; `tasks.py api` sets `TP_WAREHOUSE=duckdb` when the file exists.
- **Cache** (`api/cache.py`): results are kept in memory per warehouse + endpoint + arguments, for 1 h (KPIs,
  trends, stations) or 6 h (forecasts). Errors are not cached.
- On Windows, a running API briefly locks `data/transitpulse.duckdb` during each query; stop it before a full
  `dbt build` or forecast run if they report the file as locked.

Configuration: environment variables with prefix `TP_` (`api/settings.py`).

### Ask TransitPulse (`api/agent/`, `api/routes/ask.py`)
- **Off by default.** `TP_AGENT_ENABLED=true` turns it on; only then are the agent packages (`agent` dependency
  group: LangGraph, LangChain, sqlglot) imported, so the rest of the API runs without them.
- **Stream:** `fastapi.sse`, LF-delimited, `event:` + one JSON `data:` line each:
  `thinking {message}` → `sql {sql}` → `rows {count, columns}` → `answer {text, columns, rows (lists), sql}`, or
  `thinking` → `refusal {message, suggestions ×3}`, or an `error {code, message}` at any point. Every run ends with
  exactly one of answer / refusal / error.
- **Graph** (`graph.py`, LangGraph `StateGraph`):
  - `route`, in order: a keyword pre-filter refuses requests to change data, prompt-injection phrases and secrets;
    with `AgentDeps.suggested` (on in the service, off in the eval) a site suggestion (`suggested.py`, matched
    ignoring case, spacing and end punctuation) goes straight to `execute` with its reviewed query (still
    guardrails, dry run and byte budget; one LLM repair if it fails) and the forecast suggestion to `forecast`; a
    question with data words (ridership, riders, entries, exits, trips, passengers, busiest, Bay Wheels, bikes,
    stations, recovery, commute) and no off-topic word (weather, fares, tickets, delays, arrival, schedule, parking,
    plan, directions…) or forecast word goes to `sql` without asking the model; anything else asks the LLM for `sql`,
    `forecast` or `refuse` (told to refuse only clear off-topic requests). A suggestion costs one model call (the
    answer), a plain data question two, the rest three.
  - `sql`: the LLM writes BigQuery Standard SQL against `marts.<table>` → guardrails → dry run → execute. The SQL
    prompt carries `TP_AGENT_EXAMPLES_K` (default **5**) retrieved examples (see Examples below). A rejected
    or failed query is retried **once** with the error in the prompt; a second failure ends with `error`
    (`sql_rejected`, `query_failed` or `too_expensive`).
  - `forecast`: finds the station (4-letter code or the longest station name in the question) and runs a fixed query
    on the latest `forecast_station_daily` run (date, p50, p10, p90); no station → a refusal asking which one.
  - `answer`: the LLM writes 1–3 sentences from the first 20 rows; the payload carries the SQL that ran.
- **Guardrails** (`guardrails.py`, sqlglot, BigQuery dialect): exactly one SELECT / WITH / set operation; no
  DML/DDL, `SELECT INTO`, `COPY`, `PRAGMA`, `SET`, `ATTACH`, `EXPORT`…; tables only from the allowlist
  (`marts.dim_date, dim_station, fct_station_daily, fct_bike_trips_daily, mart_kpis_daily, mart_recovery,
  mart_peak_load, mart_od_flows, mart_ridership_monthly, mart_bikes_vs_trains, forecast_station_daily` and
  `ml.forecast_runs`; not `fct_trips_hourly`), no other projects, `INFORMATION_SCHEMA`, table functions or file
  readers. `LIMIT` is added or clamped to `TP_AGENT_ROW_LIMIT` (200), then the SQL is transpiled to the warehouse's
  dialect with tables qualified (`` `project.marts.x` `` on BigQuery).
- **Execution** (`api/warehouse.py`): DuckDB uses a read-only connection with `enable_external_access=false` and a
  locked configuration, `EXPLAIN` as the dry run and an interrupt after `TP_AGENT_TIMEOUT_S` (20 s). BigQuery dry-runs
  (no cache) and refuses over `TP_AGENT_MAX_BYTES` (1 GB), then runs with that as `maximum_bytes_billed` and
  `job_timeout_ms` = `TP_AGENT_TIMEOUT_S`, so BigQuery stops the job itself; if the client-side wait times out the
  job is also cancelled and it counts as a failed query ("The query took longer than 20 s."; retried once, then
  `query_failed`).
- **Limits:** `TP_AGENT_RATE_PER_MIN` (10) questions per client IP per minute, in memory (above 10,000 tracked
  IPs, every IP with no hit in the last minute is forgotten); the IP is
  `request.client.host`, or the right-most `X-Forwarded-For` entry only with `TP_TRUST_PROXY=true`. A per-process
  daily budget of warehouse bytes (`TP_AGENT_DAILY_BYTES`, 10 GB, resets at UTC midnight): spent → 429 `agent_busy`
  before streaming, or an `agent_busy` error if a query would exceed it.
- **Examples** (`prompts.py`, `api/agent/examples.json`):
  - The pool is the eval set's 63 in-scope `sql` questions with their gold SQL (id, question, sql, tags), exported
    by `python -m eval.examples --write`; `python -m eval.examples` exits 1 if the file is out of date. It ships in
    the image (`api/` is copied whole).
  - `retrieve_examples(question, k, exclude)`: BM25 (k1 1.2, b 0.75) over lower-cased word tokens of the pool's
    questions, standard library only, ties in pool order. Production excludes nothing; the eval excludes the
    question's own id (leave-one-out, via the graph state's `exclude_examples`).
  - `sql_prompt(question, previous_sql, error, *, examples=())`: with examples the user message starts with
    "Examples of questions and SQL that answers them:" and each `Question: …` / `SQL: …` pair, then
    "Now write the SQL for this." and the question. With `TP_AGENT_EXAMPLES_K=0` the prompts are byte-identical to
    arm A (fingerprint `85a1cbe8…da56`). Route and answer prompts never carry examples.
- **LLM** (`llm.py`, `TP_AGENT_LLM`): `fake` (default; deterministic test double with a few canned queries),
  `ollama` (`TP_OLLAMA_MODEL` llama3.1:8b at `TP_OLLAMA_URL`), `gemini` (`TP_GEMINI_MODEL`, default `gemini-3.5-flash-lite`, key from
  `GOOGLE_API_KEY`). A Gemini quota error (`GoogleRateLimitError`, the free tier's per-model daily cap) ends the
  stream with `agent_busy`, "The analyst is out of free questions for now".
- **Tracing** (`tracing.py`): Langfuse v4 callback only when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set;
  otherwise langfuse isn't imported.
- **Eval** (`eval/`): `questions.yaml` has 66 in-scope questions (tags kpi, station, trend, bikes, forecast, od) with
  BigQuery-dialect gold SQL and 10 that must be refused (sha256 frozen in `eval/ab.py`).
  - `python -m eval.run_eval --llm fake|ollama|gemini --warehouse duckdb [--arm A|B] [--duckdb-path] [--ids]
    [--json] [--save-summary] [--results-dir]` scores execution accuracy (`eval/scoring.py`, defined in
    `docs/METRICS.md`), refusal accuracy, guardrail rejections, latency and the mean SQL-prompt length, and writes
    the per-question detail to `eval/results/<llm>-<arm>-<ts>.json` (gitignored). `--arm A` (default) runs with no
    examples, `--arm B` with 5 (each question's own left out). `--llm fake` is an oracle (1.0 by construction).
  - `--save-summary` also writes `summary-<llm>-<arm>-<ts>.json` (committed), which adds `arm`, `examples_k`,
    `eval_sha256`, `ollama_version` and `per_question` ({id: {correct, outcome}}). Committed: the two A/B arms
    (`summary-ollama-A-20261015T013021Z.json`, `summary-ollama-B-20261015T013355Z.json`) and the older
    `summary-ollama-20261009T143938Z.json`.
  - `python -m eval.ab [--llm ollama:llama3.1:8b] [--json] [--power] [--check]` (standard library only) pairs the
    newest A and B summaries by question: exact McNemar, a paired bootstrap CI (10,000, seed 0), the decision rule,
    and `--power` (simulation from arm A's accuracy). `--check` exits 1 if an arm is missing, `per_question` doesn't
    cover all 76 ids, `eval_sha256` isn't the frozen hash, `docs/AB_TEST.md`'s Results numbers differ from a
    recomputation, or `Settings.agent_examples_k`'s default isn't what the rule gives.
  - **llama3.1:8b on the local DuckDB (Ollama 0.40.4):** arm A 0.2727 (18/66), arm B **0.5000 (33/66)**; refusal
    accuracy 1.0 in both; discordant b = 5, c = 20, McNemar p = 0.0041; acc_B − acc_A +0.227 [+0.091, +0.364];
    p50 / p95 2.5 / 6.7 s (A) and 1.7 / 4.7 s (B). Minimum detectable improvement at 80% power: +14 points.

---

## 5. Pipeline

### Spark job (`pipeline/spark/clean_bart_od.py`)
Input: headerless CSV(.gz) `date,hour,origin,destination,trips`. Every row is tagged with a drop reason or kept:
`malformed_row`, `bad_date`, `bad_hour` (not 0–23), `bad_origin` / `bad_destination` (not 4 alphanumerics),
`bad_trips`, `non_positive_trips`, `duplicate` (same date/hour/origin/destination; the latest source file wins).
Kept rows get `weekday` (1 = Sunday), `is_holiday`/`holiday` (US federal), and are written as Parquet partitioned
by `year`/`month`, replacing only the months present. Writes `audit.json` (rows in/out, drops per reason).
Local mode needs ~4 GB driver memory for two years.

### Bay Wheels (`pipeline/baywheels.py`)
- **Discovery:** monthly zips are found by listing the public bucket (`s3.amazonaws.com/baywheels-data`) and matching
  keys that start with `YYYYMM-`, whatever the rest of the name. The yearly 2017 file is ignored; missing months
  (2020-04, 2024-12) simply have no file.
- **Download:** skipped when ETag + size match `data/raw/baywheels/manifest.json` (which also stores the sha256).
- **Cleaning (DuckDB):** each month is read with an explicit all-text schema from its header, and the two source
  schemas (Ford GoBike "legacy", Lyft) are normalised to one:
  - Columns: `ride_id`, `started_at`, `ended_at`, `duration_sec`, start/end station id + name, start/end lat/lng,
    `rideable_type`, `member_type`, `trip_date`, `source_file`, `schema_version`.
  - Legacy rows: `ride_id` is an md5 of the source fields; Subscriber/Customer → member/casual; bike type `unknown`.
  - Drop reasons: `malformed_row`, `bad_timestamp`, `non_positive_duration`, `over_24h`, `missing_coordinates`,
    `outside_bay_area`, `outside_file_month`, `duplicate`.
- **Output:** `data/parquet/baywheels_trips/year=/month=/part-0.parquet` (only the months processed are replaced)
  and `data/parquet/baywheels_audit/year=YYYY/audit.json`.

### dbt models (`dbt/transitpulse/`)
| Layer | Models | Materialization |
|---|---|---|
| staging | `stg_bart_od`, `stg_bart_stations`, `stg_baywheels_trips` | views |
| snapshot | `snap_bart_stations` (SCD2, check strategy on name/lat/lon) | snapshot |
| core | `dim_station` (SCD2, first version back-dated to 1900), `dim_date` (incl. `iso_week` with its `iso_year`), `fct_trips_hourly` (incremental: re-processes the last 35 days, anything newer, and any date not loaded yet, so a backfilled older year is picked up), `fct_station_daily`, `fct_bike_trips_daily` | tables |
| seed | `bart_closure_candidates` (15 rows: `station_code`, `closure_group` 1 = the first 10 / 2 = the next 5, `closure_segment`; schema `staging`). The one place the closure list lives | seed |
| marts | `mart_recovery`, `mart_peak_load`, `mart_od_flows`, `mart_kpis_daily`, `mart_ridership_monthly`, `mart_bikes_vs_trains`, `mart_station_closures`, `mart_closure_destinations`, `mart_closure_scenarios` | tables |

73 data tests (incl. a singular test that every staged OD date is in `fct_trips_hourly`). KPI definitions:
`docs/METRICS.md`:
- The 2019 recovery baselines (`mart_recovery`, `mart_kpis_daily`) are the same ISO week of **ISO year** 2019
  (2018-12-31 → 2019-12-29); `mart_recovery` leaves out ISO-year-2019 days.
- `mart_kpis_daily.rolling_28d_avg_entries` averages the days present in the calendar window [d − 27, d], and
  `rolling_28d_days` counts them (28 without gaps; locally 26–27 around BART's four missing 2020 days).
- **Closure marts** (all on service weekdays of the *period year*, the latest calendar year whose data reaches
  Dec 31; locally 2025):
  - `mart_station_closures`: one row per station with data that year (50 locally): average weekday entries, exits
    and trips (entries + exits), `rank_lowest` (`rank()` from the fewest) and `stations_ranked`, share of systemwide
    weekday trips, the calendar-2019 baseline (null with fewer than 200 baseline weekdays: Milpitas, Berryessa),
    `recovery_ratio` and `system_recovery_ratio`, change vs the year before, and the nearest current station **not
    in the seed** (haversine, Earth radius 3958.8 mi). Group and segment from the seed (null when not listed).
  - `mart_closure_destinations`: each listed station's top 3 destinations (other stations; ties by code), average
    weekday trips and share of all trips starting there.
  - `mart_closure_scenarios`: `first_10` and `all_15`: weekday trips starting or ending at a listed station (a trip
    between two listed stations counts once) and their share of all weekday trips.
  - Portable SQL only (no `filter`, `radians`, `make_date` or `string_agg`); built on DuckDB, not yet on BigQuery.
    On the CI fixture (no full year) they build empty.

Targets:
- `local` (DuckDB, default): 88/88 pass in the last full run, ~2.3 min; the closures subset (`dbt build --select
  bart_closure_candidates+`: the seed, 3 marts, 11 tests) 15/15 in under 1 s. Needs the Bay Wheels Parquet: the
  source glob fails with no files.
- `dev` (BigQuery): all models, built by the VM's `warehouse` runs; the closures seed and marts only after the VM
  pulls this code and runs a dbt build (owner step 4). Until then `/api/closures` answers 404 there.
- `ci`: never run.

On BigQuery, facts are partitioned by `trip_date` (and the BART facts clustered by station), and queries are capped
at 20 GB billed in `dev` / 500 MB in `ci` (`maximum_bytes_billed`). The forecast tables are written by
`ml/forecast`, not dbt; dbt leaves them alone.

### Forecast (`ml/forecast/`)
- **Input:** `marts.fct_station_daily` (daily entries per station).
- **Model:** one global LightGBM per quantile (p10, p50, p90). Rows are (station, forecast origin t, horizon 1–14),
  and every feature uses only data up to t:
  - last value, previous day and 7-day mean;
  - the seasonal-naive value and the mean of the last 4 same weekdays;
  - 28-day coefficient of variation;
  - horizon, target weekday and month, and US federal holiday flags for the target day, its neighbours and the
    naive reference day;
  - station (categorical).

  Values are scaled by the station's 28-day mean, so one model fits busy and quiet stations. Predictions are sorted
  (p10 ≤ p50 ≤ p90) and clipped at 0. Rows whose 28-day history has a missing day are dropped.
- **Baseline:** seasonal naive, i.e. the last observed value on the target's weekday at or before the origin.
- **Validation:** walk-forward over 12 origins every 14 days, the last one 14 days before the end of the data: 6
  warm-up (calibration) folds, then 6 test folds. Each fold trains only on targets dated at or before its origin,
  within a 730-day window. Errors are pooled over the 6 test folds, stations and horizons; a paired bootstrap over
  stations (B = 1000, seed 0) gives 95% CIs.
- **Interval calibration (split-conformal, CQR):** score = max(p10 − actual, actual − p90) ÷ the station's 28-day
  level. Each test fold moves both band edges by the ⌈(n+1)·0.8⌉-th smallest score of the 6 folds before it (all
  targets at or before its origin); the published forecast uses the last 6 folds' scores. The band is clipped at 0
  and always contains p50. p50 is untouched, so MAE/RMSE are identical with and without calibration.
  `--calib-folds 0` publishes the raw p10–p90. Calibration needs fold step ≥ horizon.
- **Latest local run** (`fc-20261009T131810Z-a3cda6`, data through 2025-12-31, trained from 2024-01-02, 123 s on 4
  threads; the same data and numbers as the production BigQuery run):

  | | LightGBM | Seasonal naive |
  |---|---|---|
  | MAE | **283.1** [215.9, 364.6] | 548.5 [416.9, 698.2] |
  | RMSE | 642.6 [430.9, 842.8] | 1246.7 [857.4, 1630.2] |

  MAE improvement 265.4 [199.6, 339.9]. Coverage against 0.80 nominal: raw p10–p90 **0.705** [0.691, 0.719],
  calibrated **0.730** [0.717, 0.744]. Mean band width 0.241 → 0.251 of the station's level; the published
  forecast's adjustment q = 0.023 (folds 0–5 used q ≈ 0.004–0.006). Per test fold, raw → calibrated: 0.807 → 0.833,
  0.757 → 0.786, 0.697 → 0.726, 0.650 → 0.683, 0.896 → 0.909, 0.420 → 0.444 (Christmas).
- **Output:**
  - `marts.forecast_station_daily` (replaced each run): `run_id, generated_at, station_code, forecast_date,
    horizon_day, p10, p50, p90, lower, upper` (`lower`/`upper` = the published band).
  - `ml.forecast_runs` (appended): run id, timestamps, `data_through`, training window, folds, horizon, stations,
    every metric with `_lo`/`_hi` bounds, raw coverage, `coverage_calibrated(_lo/_hi)`, `interval_nominal`,
    `interval_method`, `conformal_q`, `calib_folds`, `mean_width_raw`, `mean_width_calibrated`, `params_json`,
    `fold_metrics_json` (per test fold, incl. calibrated coverage and q), duration.
  - New run-log columns are added to an existing table before appending (DuckDB `ALTER TABLE`, BigQuery
    `ALLOW_FIELD_ADDITION`); older rows have NULL there.
- **CLI:** `python -m ml.forecast.run [--warehouse duckdb|bigquery] [--duckdb-path] [--horizon 14] [--folds 6]
  [--calib-folds 6] [--seed 0] [--train-days 730] [--bootstrap 1000]`. The Dagster asset runs 6 + 6 folds.

### Causal study (`analysis/causal/`)
The question: did the eBART extension to Pittsburg Center and Antioch (opened Sat 2018-05-26) change ridership at
the nearby legacy stations, and did it bring new riders or only move them? The write-up is
[`FINDINGS.md`](FINDINGS.md).

- **Pre-registration.**
  - `analysis/causal/preregistration.json`: fixed 2026-10-09, sha256 `a05df985…40f4`, committed in `4c80c9b`.
  - `analysis/causal/preregistration-amendment-1.json`: fixed 2026-10-10, sha256 `96395c97…6061`, committed in
    `39b1a70`.
  - Neither file is ever edited. `design.load()` reads the original and applies the amendment, which is required. It
    checks `amends_sha256` and that each changed value equals its `was`. `Design.sha256` is the original's, and
    `Design.amendments` lists (file, sha256, fixed_on).
  - Every station set, window, bin, draw count, interval quantile, threshold and the seed is read from these files;
    no station list is written in code.
  - The sets:
    - treated legacy: PITT, NCON, CONC;
    - new: ANTC, PCTR;
    - corridor: the five summed into one unit;
    - buffer (its own spillover estimate): ORIN, LAFY, WCRK, PHIL;
    - excluded: WARM, FRMT, SFIA, OAKL, COLS, MLPT, BERY;
    - controls: the other 34 stations (16 suburban park-and-ride as a secondary set).
  - Weekly bins: pre [−21,−18] … [−5,−2] (reference [−5,−2]), post [0,3] … [88,90]. Monthly bins: [−29,−26], then
    3-month bins to the reference [−4,−2], post [0,2] … [18,20].
- **Data (committed, LF).**
  - `data/station_week.csv` (`panel.py`, from `marts.fct_station_daily`, read-only).
    - Columns `station_code, week_start, days, entries, exits`; ISO weeks 2018-01-01 → 2020-02-17; 5,412 rows.
    - All 50 stations. ANTC/PCTR have a row for every week (missing days = 0).
    - Two weeks (2020-01-20 and 2020-02-17) have 6 days system-wide, so the analysis panel has 109 weeks (20 pre,
      89 post).
  - `data/station_month_weekday.csv` (`monthly.py`).
    - Columns `station_code, month, avg_weekday_entries`; 2016-01 → 2020-02; 2,388 rows.
    - From BART's monthly workbooks (`ridership_YYYY.zip`, cached in `data/raw/bart_monthly/`): the "Weekday OD" /
      "Avg Weekday OD" sheet, found by header text.
    - Entries are column sums, each checked against the sheet's "Entries" row (±1).
  - `data/station_codes_2letter.csv`: the workbooks' 2-letter codes → our 4-letter codes (50 stations).
  - Cross-check with the daily warehouse (non-holiday Mon–Fri means, 25 months):
    - median |% diff| over controls + treated **0.78%**;
    - corridor stations at most 3.5% (ANTC).

    Command: `python -m analysis.causal.monthly --crosscheck --json`.
- **Estimators (`did.py`).**
  - `twfe`: statsmodels OLS, CR1 by station. `event_study`: bins, CR1 CIs and the pre-bin F test.
  - `dd` / `dd_bins`: exact double differences, equal to statsmodels to 1e-8.
  - `aggregate_unit`: sums levels before the log.
  - `placebo`: the placebo interval [b − q.975, b − q.025], the two-sided RI p, per-bin bands and the pre-trend RI p.
    Treatment goes to control stations only:
    - legacy: all 5,984 sets of 3;
    - corridor: all 5,984 sets of 3, each summed (Amendment 1);
    - buffer: 10,000 random sets of 4 (seed 20180526);
    - per station: the 34 single controls;
    - 16 suburban controls: every combination.
  - `verdict` and `caution`: the pre-registered rules.
- **Synthetic validation (`synthetic.py`).**
  - The data: station FE + a shared seasonal week effect + AR(1) station noise (σ = 0.04, ρ = 0.5), on the
    pre-registered stations and weeks.
  - Scenarios: null, moved (PITT −20% to ANTC) and new (corridor +15%).
  - Command: `python -m analysis.causal.synthetic --sims 200 --seed 0 --json` (about 2.2 min). The output includes
    `placebo_n_draws` per estimand and the amendment hashes.
  - Current results (the design as amended):

    | | legacy placebo cov. | legacy CR1 cov. | corridor placebo cov. | RI reject @5% (null) |
    |---|---|---|---|---|
    | null | 0.935 | 0.79 | 0.925 | legacy 0.065, corridor 0.075 |
    | moved | 0.965 | 1.00 | 0.96 | — |
    | new | 0.95 | 0.825 | 0.935 | — |
- **The run (`run.py`, `tasks.py causal`).**
  - It reads only the committed CSVs and the pre-registration, and computes the primary weekly estimates plus four
    robustness analyses: exits, suburban controls, monthly 2016–2020, and the in-time placebo.
  - It writes `api/data/findings.json`. That file has sorted keys and 6-decimal floats, and `generated_at` =
    `data_through` = 2020-02-16, taken from the data. `--plots` writes `docs/img/findings-event-study-weekly.png`
    and `-monthly.png`.
  - `--check` recomputes and exits 1 if the committed file differs. `--summary` prints the headline numbers. A run
    takes about 4 s.
  - The JSON's top-level keys: `question`, `generated_at`, `data_through`, `preregistration {sha256, fixed_on,
    amendments}`, `design`, `estimates {legacy, corridor, buffer, per_station}`, `pretrend`, `robustness`,
    `verdict`, `caution`, `event_study`, `source`.
- **Results (committed `findings.json`).**
  - **Verdict: new; caution: off.**
  - Corridor **+4.2%** [+1.6%, +7.1%], about 505 extra entries a day [199, 824].
  - Legacy **−23.9%** [−25.8%, −21.8%]: PITT −40.1%, NCON −23.1%, CONC −4.3%.
  - Buffer +0.5% [−1.7%, +3.0%].
  - Weekly pre-trend RI p: legacy 0.43, corridor 0.66. Legacy CR1 Wald p = 0.027.
  - Monthly: corridor +6.4% [+2.2%, +12.3%], with pre-trend RI p 0.11 (legacy 0.069).
- **Post-hoc trend-adjusted estimate (`trend_adjusted.py`; not pre-registered, decided 2026-10-14).**
  - Per unit (corridor aggregate, pooled legacy), gap_t = treated log − mean control log. Monthly: OLS of gap_t on
    t over the 28 pre months, then the mean over the 21 post months of gap_t − (α + β·t). Weekly: the weekly
    double difference minus the unit's monthly β × 12.77 months (mean post week − mean pre week).
  - Inference: the same procedure on all 5,984 pre-registered sets of 3 controls (corridor sets summed);
    [b − q.975, b − q.025] and the two-sided RI p.
  - `--write` writes `analysis/causal/trend_adjusted.json` (sorted keys, 6 decimals); `--check` recomputes and exits
    1 on any difference; `--summary` prints the headline numbers. It never touches `findings.json`, the PNGs or
    the site.
  - Results: corridor monthly −0.1% [−4.3%, +3.2%], weekly +1.0% [−2.4%, +4.2%] (β = +0.0025 log points a month);
    legacy monthly −26.5% [−29.1%, −24.0%], weekly −25.9% [−28.2%, −23.8%]. The corridor intervals contain 0.

### Dagster (`pipeline/definitions.py`)
- **Assets:**
  - `bart_gtfs`, `bart_stations_raw`, `web_map_data`.
  - `bart_od_files` → `bart_od_parquet` → `raw/bart_od` and `baywheels_files` → `baywheels_parquet` →
    `raw/baywheels_trips` (static yearly partitions 2018 → current year).
  - Every dbt model/snapshot as an asset (group `warehouse`).
  - `forecast_station_daily` (group `ml`, downstream of `marts/fct_station_daily`).
- **Jobs and schedules** (Pacific time):

  | Job | Schedule / sensor | What it does |
  |---|---|---|
  | `yearly_ingest` | sensor `bart_od_updates`, every 6 hours | HEADs BART's files for the last two `years` partitions and reloads a year when its `Last-Modified` changes (cursor = last stamp per year). BART posts on no fixed day; the 2025 file last changed 2026-01-03 and the 2026 file is still empty |
  | `baywheels_ingest` | 7th of each month, 06:30 | the Bay Wheels partition of the previous month's year |
  | `refresh_reference_and_models` | 6th of each month, 08:00, **and** sensor `models_after_ingest` after every successful BART or Bay Wheels ingest run (backfill runs skipped) | GTFS, stations, map data, `dbt build` |
  | `weekly_forecast` | Mondays, 09:00 | retrain and publish the forecast |
- **Resources:** `Storage` (`local` | `gcp`), `SparkRunner` (`python` | `docker`), `DbtCliResource`.
- Runs locally against `.dagster_home/` (gitignored), started by `tasks.py dagster`, which includes the `ml` group.
- The static `years` partitions are computed when the code location loads, so a daemon started in 2026 has no
  "2027" partition until it is restarted; the BART sensor checks the last two loaded partitions and the Bay Wheels
  schedule only asks for the previous month's year. Both sensors start as RUNNING (`default_status`).

### Oracle VM (`deploy/oracle/`, running)
- Two systemd units: `transitpulse-dagster-daemon` (schedules) and `transitpulse-dagster-web` (UI on 127.0.0.1,
  reached by SSH tunnel).
  - Both run as the non-root `transitpulse` user from `/opt/transitpulse`, with the venv first on `PATH`.
  - Environment from `/etc/transitpulse/transitpulse.env` (mode 600). The key file is
    `/etc/transitpulse/sa-pipeline-key.json` (owner `transitpulse`, 600).
  - Memory caps `MemoryMax` 7 G (daemon, includes a Spark run) / 1 G (UI), `Nice=10` and `OOMScoreAdjust=500`,
    so SeismicSoCal keeps priority and is not the one killed if memory runs out.
  - Sized for a 2 OCPU / 12 GB VM (the Always Free maximum): `TP_SPARK_DRIVER_MEMORY=4g`, `TP_ML_THREADS=2`,
    `DBT_THREADS=2` in the env file. The VM (shared with SeismicSoCal) is 2 OCPU / 12 GB with a 4 GB swap file.
  - The weekly forecast with calibration fits 12 folds instead of 6 (about twice the ~21 min the uncalibrated run
    took there). The VM runs whatever code was last pulled; `git pull` + restarting the units picks up new code.
- `bootstrap.sh` installs and updates everything (apt or dnf, Java 17, uv, `uv sync --frozen`, `dbt parse`). It
  starts the services only once the key is in place. Steps are in [`ORACLE_VM.md`](ORACLE_VM.md).

### Cloud Run (`Dockerfile`, `infra/terraform/cloudrun.tf` + `wif.tf`, `deploy.yml`; live, deploys on every push to `main`)
- **Image.**
  - Build stage: `python:3.12-slim-bookworm` + the uv binary. It runs
    `uv sync --frozen --no-dev --no-default-groups --group agent --no-install-project` into `/app/.venv` (main
    dependencies + the agent group; no dev, dbt, ML or pipeline packages; bytecode precompiled).
  - Runtime stage: the same base, with only the venv, `api/` and `web/` (`.dockerignore` is an allowlist), owned by
    root and run as uid 10001.
  - `CMD`: `uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}`.
  - Size: 120 MB (`docker image inspect`), 119 MB gzip-compressed.
  - Locally it answers `/healthz` about 1.5 s after `docker run` and idles at ~76 MiB.
  - Without a warehouse its data endpoints answer 503. `/api/ask` answers 503 unless `TP_AGENT_ENABLED=true`.
- **Service (Terraform).**
  - `transitpulse-api` in us-west1: 0–2 instances, 1 vCPU / 512 MiB, `cpu_idle`, concurrency 80, timeout 60 s,
    startup probe on `/healthz`.
  - Runs as `sa-agent` (read-only on `marts` + `ml`).
  - Env: `TP_WAREHOUSE=bigquery`, `TP_GCP_PROJECT`, `TP_TRUST_PROXY=true`, `TP_AGENT_ENABLED` from
    `var.agent_enabled` (default **false**; the owner's tfvars sets it true). Only when that is true do `TP_AGENT_LLM=gemini`, `TP_GEMINI_MODEL` and
    `GOOGLE_API_KEY` (Secret Manager `transitpulse-gemini-api-key`, version `latest`, added by hand) appear, along
    with `sa-agent`'s access to that secret. `TP_AGENT_EXAMPLES_K` is not set, so the agent uses the default 5.
  - The image is in `ignore_changes`: the first revision uses Google's `hello` placeholder, and CI owns the image
    after that.
  - `allUsers` has `run.invoker` on this service only.
- **Workload Identity Federation.**
  - Pool `github`, provider `transitpulse` (GitHub OIDC), with the condition
    `assertion.repository == "braaaeeedyn/transitpulse" && assertion.ref == "refs/heads/main"`.
  - The principalSet for the repository may impersonate `sa-deploy`.
  - `sa-deploy` has `artifactregistry.writer` on the `transitpulse` repo, `run.developer` on the service, and
    `iam.serviceAccountUser` on `sa-agent` only.
- **`deploy.yml`.**
  - Runs on push to `main` and on `workflow_dispatch`. The job runs only if `vars.DEPLOY_ENABLED == 'true'`.
  - Auth: `id-token: write`, then `google-github-actions/auth` with `vars.GCP_WIF_PROVIDER` /
    `vars.GCP_DEPLOY_SA`.
  - Steps: `docker build` (tag `us-west1-docker.pkg.dev/<project>/transitpulse/api:<sha>`), then the container
    smoke tests (`uv run pytest -m docker tests/deploy` with `TP_TEST_IMAGE` = that image), then auth and
    `docker push`, then `gcloud run deploy --image`, then curl `/healthz` and `/`.
  - It doesn't wait for `ci.yml` (both start on the same push); only the container smoke tests gate the push.
  - No Terraform in Actions.
- Applying it, switching it on, enabling the agent, quotas, rollback, costs and teardown are in
  [`CLOUD_RUN.md`](CLOUD_RUN.md).

### `make up` (`docker-compose.yml`, `tasks.py up`)
- **Services:** `ollama` (`ollama/ollama:0.40.4`, pinned to the version the A/B ran on; models in the named volume
  `transitpulse_ollama`, or in a host folder when `TP_OLLAMA_DATA` is set; healthy once `ollama list` answers);
  `ollama-pull` (one shot: `ollama pull ${TP_OLLAMA_MODEL:-llama3.1:8b}` against `ollama`, then exits); `api` (built
  from the `Dockerfile`, `${TP_PORT:-8000}:8080`, healthy once `/api/health` answers, checked with Python because the
  image has no curl). `api` starts only after the pull completed.
- **The API's settings:** `TP_AGENT_ENABLED=true`, `TP_AGENT_LLM=${TP_AGENT_LLM:-ollama}`,
  `TP_OLLAMA_URL=${TP_OLLAMA_URL:-http://ollama:11434}`, `TP_OLLAMA_MODEL`, `TP_WAREHOUSE=${TP_WAREHOUSE:-none}`,
  `TP_DUCKDB_PATH=/app/data/transitpulse.duckdb`, with `./data` mounted read-only.
- **`tasks.py up`** runs `docker compose up --build` and, like `tasks.py api`, sets `TP_WAREHOUSE=duckdb` when
  `data/transitpulse.duckdb` exists (unless `TP_WAREHOUSE` or `TP_GCP_PROJECT` is set). The Makefile's `up` calls it.
- **From a fresh clone** (no warehouse) the data endpoints answer 503 and a data question ends with one `error` event
  (`agent_unavailable`, "The analyst isn't connected to the data right now."), never a 500.
- **CPU by default.** The compose file's comment names the GPU options: `gpus: all` on `ollama`, or
  `TP_OLLAMA_URL=http://host.docker.internal:11434` for a host Ollama.
- **Size:** the Ollama image is 9.4 GB on disk; `llama3.1:8b` adds about 4.9 GB to the volume.
- **Last run** (2026-10-14, by hand, `TP_OLLAMA_MODEL=qwen2.5-coder:0.5b` because RAM was short, local warehouse): the
  pull succeeded, the API turned healthy, `/api/kpis` answered from the read-only DuckDB on the Windows bind mount,
  and "Which station had the most entries on 2025-12-31?" streamed `thinking → sql → rows → answer` in 8.3 s on CPU.
  The 0.5B model's SQL summed all of 2025 while the answer said "on 2025-12-31", so the wiring works but that small
  model's answers can't be trusted.

### Load test (`load/`)
- `load/run_local.py`:
  - builds the dbt fixture warehouse (3 stations, Jan 2019 + Jan 2025, synthetic forecast with a complete run row)
    in a child `uv run --group dbt` process, in a temp dir
  - starts uvicorn on it with `TP_AGENT_ENABLED=true`, `TP_AGENT_LLM=fake` and the per-IP rate limit lifted
  - runs `load/locustfile.py` headless for each user count (default 1, 10, 25; 20 s each)
  - reads Locust's CSV percentiles, stops the server, and prints p50/p95/p99, RPS and failures per endpoint
    (`--json` for JSON)
  - exits non-zero if the server doesn't start or any request fails
- Users wait 0.5–1.5 s between tasks: `/api/kpis` 3, `/api/forecast/{code}` 3, `/api/ask` 1 (an SQL question, a
  recovery question or an off-topic one). Each user calls all three once on start. An ask counts as failed unless
  its SSE stream ends in `answer` or `refusal`.
- Last run on this PC: 0 failures. At 25 users, ~30 req/s; forecast p50/p95/p99 5/14/30 ms; kpis 4/22/29 ms; ask
  37/140/140 ms. Full table in the README.

---

## 6. Tests

| Suite | Command | Count | Status |
|---|---|---|---|
| Python unit (map data, API data endpoints, Bay Wheels cleaning, dbt build on a generated fixture, dbt regressions (backfill, ISO year, rolling window), forecast + calibration, Dagster definitions and schedules, VM files, agent guardrails / graph / `/api/ask` / eval, the M5 A/B (McNemar, bootstrap, power, BM25 retrieval, arm prompts, examples pool, default k, AB_TEST.md), Cloud Run Terraform + deploy workflow, cross-origin, causal study (prereg + amendment, synthetic data, inference, monthly parser, FINDINGS.md vs findings.json, the post-hoc trend adjustment), `/api/findings`, `/api/closures` (shape, rule edges, system block, 503/404, cache, static export), gzip never on the Ask stream, the docs deliverables (BI guide, README diagram + screenshots, design backlog v1.1 list, owner steps, the station closures write-up and docs), the compose file) | `uv run --group dbt --group ml --group pipeline --group agent pytest -m "not spark and not gcp and not localdata and not docker"` | 180 (37 in `tests/test_causal.py`, 8 in `tests/test_ab.py`, 10 in `tests/test_api_findings.py`, 7 in `tests/test_api_closures.py`, 6 in `tests/test_docs_deliverables.py`, 4 in `tests/test_compose.py`) | pass (~55 s) |
| Local warehouse (real data, incl. every gold SQL of the agent eval) | `uv run --group dbt --group ml --group agent pytest -m localdata tests/local` | 25 (4 in `test_causal_local.py`: the committed weekly CSV equals a fresh build, the opening date, the monthly cross-check, new-station trips recorded through; 1 in `test_bi_week.py`: the BI guide's check-week values; 6 in `test_suggested.py`; 6 in `test_closures_local.py`: the 15 stations in the mart, the marts against an independent Python recomputation, the API's verdicts, the write-up's verdicts and every other column of its results table against the API, the write-up's SFO assumption recomputed without SFO) | pass (needs `data/transitpulse.duckdb` with Bay Wheels + forecast) |
| Spark job | in Docker: `docker run --rm -v "$PWD:/app" transitpulse-spark python -m pytest tests/spark -m spark` | 1 | pass (auto-skipped on Windows outside Docker) |
| Browser maths (schedule, timetable range, chart helpers, station search, forecast wording, SSE parser, findings wording, closures wording and escaping) | `node --test tests/web/` | 45 | pass |
| Browser (Playwright, Chromium; API mocked for data, Ask and Findings tests): layout, map, Trends, forecast, map → forecast, busiest station, dashboard slot, Ask (incl. history, escaping, Copy SQL), Findings, Station closures (15 cards, notes without data, 404/Retry, no sideways scroll at 320/390/1120 px, axe in light and dark, the nav link), Open Graph, style guide, axe contrast | `npx playwright test` | 69 (4 in `styleguide.spec.js`, 3 in `a11y.spec.js`, 9 in `closures.spec.js`) | pass |
| Lighthouse (mobile, local server; not in CI) | `uv run python tasks.py lighthouse --runs 3 --assert` | — | 98 / 100 / 100 (gate 90 / 95 / 95) |
| README and Open Graph images | `uv run python tasks.py screenshots` (fails if a file is over its size limit) | — | og 104 KB, phone 68 KB, desktop 203 KB |
| dbt data tests | `uv run python tasks.py dbt` | 84 (+18 models/snapshot, 1 seed) | pass (incremental ~2.3 min; the 11 closures tests checked with `--select bart_closure_candidates+`) |
| Shellcheck (VM bootstrap) | `docker run --rm -v "$PWD:/mnt" -w /mnt koalaman/shellcheck:stable deploy/oracle/bootstrap.sh` | — | clean |
| ARM wheels (pipeline, dbt, ml groups) | `uv pip compile pyproject.toml --group pipeline --group dbt --group ml --python-platform aarch64-manylinux_2_28 --python-version 3.12 --only-binary :all:` | — | resolves |
| Container (marker `docker`; needs the built image `transitpulse-api:loop`) | `docker build -t transitpulse-api:loop . && uv run pytest -m docker tests/deploy` | 6 (incl. `/api/findings` served from the image) | pass |
| `make up` without Docker (the compose file as YAML, `tasks.py up`'s warehouse rule) | `uv run pytest tests/test_compose.py` | 4 (in the default suite) | pass |
| `make up` smoke (marker `docker`): the `api` service only, fake LLM, port 8814, project `tp-compose-smoke`, always taken down | `uv run pytest -m docker tests/compose` | 3 (health and site, `/api/kpis` 200 with the DuckDB file else 503, one terminal Ask event) | pass |
| Load test (Locust, fixture warehouse, fake LLM) | `uv run --group load --group agent python load/run_local.py [--users N --seconds S]` | — | 0 failures |
| Workflows | `docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest` | — | clean (`ci.yml`, `deploy.yml`) |
| A/B and post-hoc reproducibility | `uv run --group agent python -m eval.ab --check`, `uv run python -m eval.examples`, `uv run --group ml python -m analysis.causal.trend_adjusted --check` | — | pass |
| Lint/format | `uv run ruff check . && uv run ruff format --check .` | — | clean |
| Terraform | `terraform validate` / `fmt -check`; `plan` for the applied M0 resources | — | clean; the M0 plan showed no changes (the M7 files were never planned against the real backend) |

---

## 7. Known limitations (current behaviour)
- Train positions follow the timetable; delays and disruptions are not shown.
- Local Bay Wheels data covers 2019 and 2025 only (BigQuery has 2018 → 2026-09).
- The bundled GTFS timetable (`web/data/schedule.json`) ends on 2027-01-10; after that the map shows no trains and
  says the timetable has ended until `web/data` is rebuilt from a newer feed (`tasks.py web-data`).
- The agent's accuracy with llama3.1:8b is 50% on the eval set with the retrieved examples (27% without); it is
  off unless `TP_AGENT_ENABLED=true`. The A/B used llama3.1:8b with leave-one-out retrieval from a pool of near-twin
  questions, so the lift for new kinds of question, and for Gemini (production), is unmeasured. Its rate limit
  and byte budget are per process and in memory.
- The forecast's band held 73% of back-test days after calibration (raw p10–p90: 70.5%; nominal 80%), mostly because
  of the Christmas fold (44%), so the site calls it the "model range" and says it is narrower than it should be.
- Production (BigQuery) serves the pre-calibration run until the Oracle VM runs this code; the API then shows the raw
  band at 70% coverage, worded the same way.
- The forecast covers the 14 days after the latest published data (currently 2026-01-01 → 14), not the next two
  weeks from today; the site says "forecast from data through".
- On Windows, Spark runs only through Docker.
- The eBART study has 3 treated stations and 1 corridor unit, and 20 weekly pre-periods. In the monthly series the
  corridor already drifts up against the controls before the opening, which the pre-registered caution rule doesn't
  test. A post-hoc trend-adjusted estimate (not pre-registered) puts the corridor effect at about 0 with an
  interval containing 0; the pre-registered verdict stays "new" (see `FINDINGS.md`).
- On `*.run.app`, `/healthz` is answered by Google's front end (404), so outside checks use `/api/health`.
- The BI dashboards (Looker Studio, Power BI) are not built yet; `bi/README.md` is the guide. Until the owner puts
  a URL in `<meta name="tp-looker-url">`, the Trends band has no dashboard card.
- The Open Graph image URL is absolute to braedynthompson.com, the only public host. A copy hosted elsewhere would
  still point crawlers there.
- Ask history lives in `sessionStorage`: per tab, gone when the tab closes, and not shared between devices.
- Lighthouse runs locally only; its numbers come from this PC (simulated mobile throttling), not from the live
  pages on GitHub Pages and Cloud Run.
- `make up` runs Ollama on the CPU unless the compose file is edited for a GPU; `llama3.1:8b` needs about 5–6 GB of
  free RAM there. The compose smoke test runs only the `api` service with the fake LLM, so it doesn't prove the
  Ollama path; that was checked once by hand with a 0.5B model.
- The first API request after the service scales to zero takes ~5 s (cold start + first BigQuery queries); later
  ones ~0.15 s. The map needs no API and shows immediately.
- The load-test numbers are from this PC on a tiny fixture warehouse, not from Cloud Run or BigQuery.
- Static assets have no hashed names: JS/CSS are served `no-cache` (revalidated), fonts are cached a year, and map
  data a day. The timetable is part of the image, so refreshing it means deploying a new image.
- **Station closures:** the list is the one reported from BART staff's February 2026 presentation, not a board
  decision; the analysis assumes all 15 close (the nearest open station excludes all of them) and counts every other
  station as open, including SFO, which the sources don't cover: it is the nearest open station for San Bruno and
  Millbrae, and if it lost service too both would meet Distance (San Bruno strong, Millbrae mixed; the write-up's
  "The SFO assumption"); distances are straight lines, not travel by road or rail; the period is 2025 only (BART
  hasn't published 2026); the verdicts weigh ridership only (no cost, equity or travel-time data); the context copy
  describes the November 3, 2026 measure as upcoming and goes stale after the election (owner step 3). The closure
  marts' SQL has run on DuckDB only, not yet on BigQuery.
