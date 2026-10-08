# TransitPulse: implementation plan

> Turns [`TRANSITPULSE_PLAN.md`](TRANSITPULSE_PLAN.md) (the *what* and *why*) into an ordered list of tasks
> (the *how*), and adds the web app: a user-friendly, fully responsive site built on [`DESIGN.md`](DESIGN.md),
> with a live system map of small animated BART trains.
>
> **Status markers:** `[x]` done · `[~]` partly done (the note says what's left) · `[ ]` not started.
> Current progress is summarised in [`CURRENT_STATE.md`](CURRENT_STATE.md); the history is in [`DEVLOG.md`](DEVLOG.md).
>
> **How to use this file:** work top to bottom. Each milestone has tasks you can check off, the files they create,
> and a **Done when** line. Don't start a milestone until the previous one's *Done when* holds, except where a task
> is marked *(parallel)*.

---

## 0. Decisions this plan makes

| Topic | Decision | Why |
|---|---|---|
| Design source of truth | [`DESIGN.md`](DESIGN.md) **v1.0, frozen** from the start of F1 until launch. Gaps found during building go to `docs/DESIGN_BACKLOG.md`, not into `DESIGN.md` (only accessibility fixes are allowed). | So the design doesn't change while the frontend is being built. |
| Frontend | Vanilla HTML/CSS/JS ES modules, no framework, **no build step**. Served as static files by FastAPI. | Matches the main plan ("no React") and BearLM. |
| Fonts | **Inter** (400/500/700), self-hosted `woff2`; system monospace for SQL. | Set in `DESIGN.md §3`. No Uber name, logo or fonts anywhere. |
| Colour | Interface is black/white/grey; **BART line colours only inside data marks** (map, trains, charts, legends). | Set in `DESIGN.md §2`. |
| Map rendering | **SVG** for the static network (lines, stations, labels) + **one `<canvas>` layer** on top for the trains. | SVG scales perfectly with `viewBox`; canvas animates dozens of trains at 60 fps without DOM churn. |
| Train positions | **Interpolated from the BART GTFS schedule** (`stop_times` + `shapes`), computed in the browser. | $0, no API key, works offline. BART's GTFS-Realtime feed has trip *updates* (delays) but no vehicle positions, so it's an optional later layer (F6). |
| Responsiveness | Fluid by default (`clamp()`, `aspect-ratio`, container queries, `ResizeObserver`), with `DESIGN.md` breakpoints only where the layout actually changes. | Must fit any screen from a 320 px phone to a 2560 px monitor. |
| Train visuals | Small line-coloured **pills** with an ink outline, pointing along the track, each in its own line's lane (`DESIGN.md §6`). | Decided up front so F3 is build-only; the pill reuses the system's signature shape. |

---

## 1. Repo layout (create in M0)

```
transitpulse/
├── pyproject.toml / uv.lock      # Python 3.12, managed by uv
├── Makefile                      # make up | test | lint | dbt | spark | web | load
├── docker-compose.yml            # api + ollama for the one-command local run
├── .github/workflows/            # ci.yml (PR), deploy.yml (main)
├── infra/terraform/              # GCP: datasets, buckets, registry, Cloud Run, IAM, WIF
├── pipeline/                     # Dagster definitions
│   ├── assets/                   # downloads, spark, bq loads, forecasts, web data
│   └── spark/                    # PySpark jobs (spark-submit entrypoints)
├── dbt/transitpulse/             # models/ snapshots/ tests/ macros/
├── ml/
│   ├── forecast/                 # LightGBM training + walk-forward eval
│   └── finetune/                 # QLoRA data gen, training, GGUF export
├── analysis/causal/              # DiD + event study notebook/scripts
├── api/                          # FastAPI app
│   ├── main.py, routes/
│   └── agent/                    # LangGraph graph, tools, guardrails
├── eval/                         # question set + gold SQL, A/B harness
├── web/                          # the site (static)
│   ├── index.html
│   ├── css/  tokens.css base.css layout.css components.css map.css
│   ├── js/   main.js map/ ask.js kpis.js forecast.js util/
│   ├── fonts/  data/  img/
├── bi/                           # transitpulse.pbix, PDF export, screenshots
├── tests/                        # pytest (python) + web/ (Playwright)
└── docs/
```

---

## 2. Milestones at a glance

The backend milestones (M) follow the main plan's phases. The frontend track (F) starts early because the train
map only needs the static GTFS feed, not the warehouse, so there's something visible to show from week 2.

| Week | Backend | Frontend | Checkpoint |
|---|---|---|---|
| 0 | **M0** setup, Terraform base | | Repo + GCP ready, $1 alert on |
| 1 | **M1** ingest + PySpark | **F1** design tokens + responsive shell *(parallel)* | |
| 2–3 | **M1** BigQuery load + dbt | **F2** network data · **F3** train map | Data Engineer demo; live train map |
| 4–5 | **M2** KPIs, Looker Studio, Power BI | **F4** KPI + station panels | Data Analyst demo |
| 6 | **M3** forecasting | **F5** forecast explorer | |
| 7 | **M4** causal analysis | Findings section | |
| 8–9 | **M5** agent + eval + A/B | **F6** Ask TransitPulse UI | AI Eng / DS demo |
| 10 | **M6** QLoRA fine-tune | | |
| 11–12 | **M7** deploy, CI/CD, Locust | **F7** polish, a11y, perf, device QA | Public launch |
| 13 | buffer | optional: GTFS-RT delays | |

---

## 3. Backend milestones

Each task below names the gap number from the main plan. Detail on methods lives in `TRANSITPULSE_PLAN.md §5`;
this section is the checklist.

### M0: setup (week 0)
- [x] `git init` done; add `.gitignore` (Python, `.env`, `*.json` keys, `.terraform/`, `target/`, `*.gguf`, `data/raw/`).
- [x] `uv init`, Python 3.12; dev deps: `ruff`, `pytest`, `pre-commit`. Add `make lint` / `make test`.
- [x] GCP project → billing → **budget alerts at $1 and $5** (do this before anything else).
- [x] Enable APIs: BigQuery, Cloud Storage, Cloud Run, Artifact Registry, IAM, IAM Credentials, STS.
- [x] Create the Terraform state bucket by hand (`gs://transitpulse-tfstate`, `us-west1`, versioning on).
- [x] `infra/terraform/`: provider + backend; BigQuery datasets `raw`, `staging`, `marts`, `ml`, `ci`; *(applied to `transitpulse-511002`; `plan` shows no changes)*
      raw bucket; Artifact Registry repo with a cleanup policy (keep last 3); service accounts
      `sa-pipeline` (write raw/staging/marts), `sa-agent` (read-only on `marts`), `sa-deploy`.
- [~] Verify the data source links and licences in `TRANSITPULSE_PLAN.md §4`; record them in `README.md`. *(listed in README; Bay Wheels licence link verified 2026-10-08; the BART terms still to verify)*
- **Done when:** `terraform apply` is clean, `make lint test` passes on an empty project, budget alerts are visible in the console.

### M1: data platform (weeks 1–3) · #4 #10 #11 #17 #2
- [~] Install Java 17 + Spark 3.5 locally; `make spark` runs a hello-world `spark-submit`. *(Spark runs in Docker (`pipeline/spark/Dockerfile`, Java 17) instead — Spark 3.5 hangs on Windows)*
- [x] Dagster assets `bart_od_files`, `baywheels_files`, `bart_gtfs` (download → GCS `raw/…/year=/month=`, idempotent by checksum). *(`baywheels_files` discovers keys from the bucket listing; ETag/size + sha256 manifest; run locally for 2019 + 2025, GCS upload path not run yet)*
- [x] `pipeline/spark/clean_bart_od.py`: explicit schema, trim/cast, drop + count malformed rows, de-dup, derive
      `trip_date/hour/weekday/is_holiday` (broadcast join), write Parquet partitioned by year/month, write `ingest_audit`.
- [x] Unit-test the Spark transforms on a 1,000-row fixture (`tests/spark/`).
- [~] BigQuery load → `raw.bart_od` (partition `trip_date`, cluster `origin`). Same for Bay Wheels. *(BART done and verified; Bay Wheels cleaned locally with DuckDB (`pipeline/baywheels.py`) and modelled in dbt (`stg_baywheels_trips` → `fct_bike_trips_daily` → `mart_bikes_vs_trains`); the `raw/baywheels_trips` BigQuery load is written but not run)*
- [x] Monthly schedule + backfill of all historical years; record final raw size in GB (for the résumé bullet). *(2018–2025 in BigQuery: 67.8M rows, 4.2 GB logical; 2026 not published yet)*
- [x] dbt: `stg_*` → `dim_station` (SCD2 snapshot), `dim_date` → `fct_trips_hourly`, `fct_station_daily` →
      `mart_recovery`, `mart_peak_load`, `mart_od_flows`. Set `maximum_bytes_billed` in `profiles.yml`.
- [x] dbt tests (generic + custom "no negative ridership"); `dbt build` green.
- [~] Deploy Dagster on the Oracle VM as `transitpulse-dagster.service` (systemd), key file gitignored. *(files + runbook ready: `deploy/oracle/` (daemon + web units, `bootstrap.sh`), `docs/ORACLE_VM.md`; not deployed yet)*
- **Done when:** a scheduled Dagster run goes raw → marts end to end on the VM, and every dbt test passes.

### M2: KPIs + BI (weeks 4–5) · #8 #9
- [x] `docs/METRICS.md`: 5–6 KPIs, each with definition, formula, owner question.
- [x] `mart_kpis_daily`: one row per day with every KPI, so the **website, Looker Studio and Power BI all read the same numbers**.
- [ ] Looker Studio dashboard (public link) on the marts.
- [ ] Power BI report per main plan §5 Phase 2; verify 3 KPIs match dbt; ship `.pbix`, PDF, screenshots, recording.
- **Done when:** the same KPI shows the same value in all three places for a chosen week.

### M3: forecasting (week 6) · #7
- [x] `ml/forecast/`: features (lags, rolling, calendar, holidays), LightGBM, seasonal-naive baseline.
- [x] Walk-forward validation; MAE/RMSE with bootstrap CIs → `ml.forecast_runs`. *(6 folds, paired bootstrap over stations, B = 1000)*
- [~] Weekly Dagster asset writes `marts.forecast_station_daily` (14-day horizon, with p10/p90 intervals). *(asset + Monday schedule done and run locally; the BigQuery write path isn't run yet)*
- **Done when:** LightGBM beats the baseline with a CI that excludes zero (or you've written down honestly why not).
  *Met locally: MAE 364.9 vs 548.5, improvement 183.7 [139.5, 234.1]. Caveat: the p10–p90 range covers 48%, not 80%.*

### M4: causal analysis (week 7) · #21 #7
- [ ] Confirm the eBART opening date and pick treated/control stations; write them down *before* looking at results.
- [ ] DiD with station + week FE, SEs clustered by station; event-study plot.
- [ ] `docs/FINDINGS.md`: question → design → assumptions → result (95% CI) → limitations. Export the event-study chart as JSON for the site.
- **Done when:** the write-up is finished and the pre-trends plot is in it.

### M5: agent + evaluation (weeks 8–9) · #19 #5 #6 #7
- [ ] `api/agent/guardrails.py`: sqlglot SELECT-only, auto-`LIMIT`, dry run ≤ 1 GB, `sa-agent` credentials. Unit-test each rejection path.
- [ ] LangGraph graph: router → sql_tool / forecast_tool / chart_tool → answer (cites SQL). Out-of-scope refusal.
- [ ] Ollama for local dev, Gemini Flash for deployed; one env var switches them.
- [ ] Langfuse callback on every run.
- [ ] `eval/questions.yaml`: 60–100 questions with gold SQL; `make eval` reports execution accuracy.
- [ ] Power analysis → A/B (schema card vs. + 5 retrieved examples) → McNemar + bootstrap CI → `docs/AB_TEST.md`.
- [ ] `POST /api/ask` **streams** progress events (Server-Sent Events): `thinking` → `sql` → `rows` → `chart` → `answer`, so the UI can show progress (F6).
- **Done when:** `make eval` runs both arms and the A/B write-up has a decision.

### M6: QLoRA fine-tune (week 10) · #16
- [ ] Generate + validate 1–3K question→SQL pairs; hold out eval templates.
- [ ] QLoRA Qwen2.5-Coder-1.5B-Instruct (r=16, 4-bit) on the RTX 4060; log curves to `ml/finetune/runs/`.
- [ ] Merge → GGUF → Ollama; add as arm C in `make eval`; McNemar + bootstrap vs. A/B.
- **Done when:** arm C results are in `docs/AB_TEST.md`, win or lose.

### M7: ship (weeks 11–12) · #1 #13 #3 #18
- [ ] Dockerfile (multi-stage, non-root); serves `api/` **and** `web/` (static mount with long cache headers on hashed assets).
- [ ] Terraform: Cloud Run (`min=0`, `max=2`), Workload Identity Federation for GitHub.
- [~] `ci.yml` on PR: ruff, pytest, Playwright (F7), `dbt build --target ci`, `terraform plan`. *(`.github/workflows/ci.yml`: ruff, `dbt parse`, pytest (incl. a DuckDB `dbt build` on a generated fixture), shellcheck, Spark, node tests, Playwright, terraform validate; `dbt build --target ci` + `terraform plan` not yet)*
- [ ] `deploy.yml` on `main`: build → push → `terraform apply` → deploy.
- [ ] Locust: forecast + agent (LLM mocked) at 1/10/25 users; p50/p95/p99 + cold start → README.
- [ ] README: architecture diagram, `make up`, results, cost, limitations, screenshots of the site at phone + desktop width.
- **Done when:** a merge to `main` deploys with no manual steps and the public URL loads on a phone.

---

## 4. Frontend track

### Page structure (single page, top to bottom)

Each section uses components from `DESIGN.md §7` and follows its band rhythm:

| # | Section | `DESIGN.md` component | Content |
|---|---|---|---|
| 1 | Sticky nav | `nav-bar`, `button-primary` "Ask a question" | Wordmark "TransitPulse", links: Map · Trends · Forecast · Findings · About. Overlay menu < 1120 px. |
| 2 | Hero | `ask-card`, `chip` | Headline ("See the Bay Area move") + the **Ask card**: input row, 4 suggestion chips, black "Ask" pill. 2 columns ≥ 1120 px, stacked below. |
| 3 | **Live system map** | `map-card`, `map-controls`, `segmented`, `tooltip` | SVG network + canvas trains, time controls, legend, Map/List toggle. |
| 4 | KPI row | `stat-tile` | Recovery %, weekday entries, peak-hour share, busiest station. "Data through <date>". |
| 5 | Trends | chart `card` | Ridership trend, hour × weekday heatmap, bikes vs. trains. Links to Looker Studio + Power BI. |
| 6 | Forecast explorer | chart `card`, combobox, `chip` | Station picker → 14-day forecast with interval band. |
| 7 | Findings | `card-ink` (the black band) | eBART DiD result in one sentence + event-study chart + `button-on-ink` "Read the analysis". |
| 8 | How it's built | `faq-row` | Pipeline, agent guardrails, eval results, costs. |
| 9 | Footer | `footer` (ink) | Data sources + licences, GitHub link, author. |

### F1: design tokens + responsive shell (week 1, parallel with M1)
- [x] `web/css/tokens.css`: transcribe **every** token in the `DESIGN.md` front matter (colours, data palette, fluid type,
      spacing incl. `gutter`/`section`, radii, elevation, motion, map sizes) into CSS custom properties, 1:1 with the token names
      (`--color-ink`, `--line-yellow`, `--type-display-xxl`, `--space-gutter`, `--radius-pill`, `--shadow-1`, `--ease-standard` …).
      After this, CSS uses only variables, never raw hex/px values.
- [x] Layout per `DESIGN.md §4`: fluid container + gutters, `auto-fit` grids, `@container` queries inside components,
      media queries only at 600 / 768 / 1120 px. `100dvh`, safe-area insets, `color-scheme: light`.
- [x] Self-host Inter (`woff2`, Latin subset, `font-display: swap`, preload 700); tabular numerals utility class.
- [x] Every component in `DESIGN.md §7` in `components.css` (buttons, icon button, chip, segmented, text input, cards, stat tile,
      tooltip, sql block, table, toast, skeleton, faq row, focus ring). Touch targets ≥ 44 px (`@media (pointer: coarse)`).
- [x] Nav: overlay menu below 1120 px; focus trapped while open; `Esc` closes; body scroll locked. Skip link "Skip to map".
- [x] Lucide icons as an inline SVG sprite (only the icons used).
- [ ] `web/styleguide.html`: every component and token on one page, for visual checks against `DESIGN.md`.
- [x] Create an empty `docs/DESIGN_BACKLOG.md` for design gaps found while building.
- **Done when:** the shell and style guide render with **no horizontal scroll from 320 px to 2560 px** and pass a keyboard-only walkthrough.

### F2: network data (week 2)
- [x] `pipeline/assets/web_data.py` (Dagster asset, also runnable as a script) turns the BART GTFS zip into small static JSON in `web/data/`:
  - `network.json`: stations (code, name, lon/lat → projected x/y), lines (route id, colour, ordered stops, path polyline).
    Use `shapes.txt` for line geometry; if a route has no shape, fall back to straight segments between stops.
  - `schedule-<service>.json`: for each trip, `[route, direction, [[stop_idx, arr_sec, dep_sec], …]]`, for weekday / Saturday / Sunday services.
    Delta-encode times and gzip. Target **< 300 KB** gzipped total.
- [x] Projection: a fixed equirectangular projection centred on the Bay, normalised to a `0–1000` coordinate box, so the SVG
      `viewBox` is constant and the browser handles scaling.
- [x] Simplify polylines (Douglas–Peucker, ~1 px tolerance at 1000 px) to keep the file small.
- [x] Map each GTFS `route_id` to a `DESIGN.md` line token (`yellow`, `red`, …); ignore GTFS `route_color`.
- [~] **Parallel lanes** for shared track: find segments used by several lines, assign each line a lane index in the *(lane order + per-edge line lists are precomputed; pixel offsets are computed in the browser on resize)*
      `DESIGN.md §6` order, and store per-segment offsets so the client can draw lines (and place trains) side by side.
- [~] Per-station label side (N/E/S/W) and a `hub` flag for the 9 phone-size labels; hand-tune in a small `label_overrides.yaml`. *(label side + `hub` flag precomputed; final placement is collision-checked at render time)*
- [~] `land.json`: Bay Area coastline clipped to the map box, from Natural Earth (public domain), simplified. *(built from US Census cartographic boundaries instead (see DESIGN_BACKLOG.md))*
- [x] pytest: every trip's stops exist in `network.json`; times are monotonic; each route has a path and a line token.
- **Done when:** `make web-data` regenerates both files deterministically (same input → byte-identical output).

### F3: the train map (weeks 2–3)

Build exactly to `DESIGN.md §6` (base layer, train glyph, controls, tooltips). The tasks below are the engineering side.

- [x] `js/map/network.js`: render `land.json` + `network.json` to inline SVG with
      `viewBox="0 0 1000 1000" preserveAspectRatio="xMidYMid meet"`. Line strokes use `vector-effect: non-scaling-stroke`
      so lines stay crisp and the same thickness at any size; lanes, casing, station markers and label halos per `DESIGN.md §6`.
- [x] `js/map/trains.js`: for the current service-day time `t`, find active trips, find the segment `(stop_i, stop_i+1)`
      they're on, and interpolate position **along the shape polyline** (precompute cumulative distances per segment).
      Dwell at stations between `arr` and `dep`. Heading from the path tangent so trains point along the track.
- [x] `js/map/canvas.js`: a canvas absolutely positioned over the SVG.
  - `ResizeObserver` on the map container → resize the canvas to `cssSize × devicePixelRatio` (sharp on retina) and
    recompute the same `meet` transform the SVG uses, so trains sit exactly on the lines.
  - **Train size scales with the map**: `trainLen = clamp(6, mapWidth * 0.012, 14)` CSS px, width ≈ 40% of length.
    Small enough to read as "small trains", never smaller than 6 px on phones.
  - Draw with `requestAnimationFrame`; skip frames when nothing moved; 40–70 trains at peak should cost < 2 ms/frame.
- [x] **Map sizing**: container uses `aspect-ratio: 1 / 1` on phones, `4 / 3` at ≥ 768 px, `16 / 9` at ≥ 1120 px,
      capped by `max-height: 80dvh`. The SVG viewBox crop shifts with the ratio so the network always fills the frame.
- [x] **Label density by width** (container query on the map): < 600 px shows only ~8 hub labels (Embarcadero, 12th St,
      MacArthur, Balboa Park, SFO, Richmond, Antioch, Berryessa); ≥ 768 px shows all labels; labels never overlap the
      line (precomputed offset side per station in `network.json`).
- [x] **Time control** (pill row under the map): `Now` · scrubber over the service day · speed `1× / 10× / 60×` · play/pause.
      Clock readout in `America/Los_Angeles` regardless of the visitor's timezone. Outside service hours, show
      "No trains running — BART service resumes at 5:00 AM" and offer "Jump to 8 AM".
- [x] **Interaction**:
  - Hover/tap a train → tooltip: line colour dot, "to Daly City", next stop + ETA.
  - Hover/tap a station → tooltip: name, lines served, entries today vs. same weekday 2019 (from `/api/stations/{code}/summary`, after M2).
  - Hit targets: invisible ≥ 44 px radius for touch, nearest-train lookup on the canvas.
  - Pinch/scroll zoom is **off** by default (avoids hijacking page scroll on phones); a `+ / −` pill pair zooms the viewBox instead.
- [x] **Performance + battery**: pause the animation when the map is off-screen (`IntersectionObserver`) or the tab is hidden (`visibilitychange`).
- [x] **Reduced motion**: with `prefers-reduced-motion: reduce`, trains are drawn as static positions refreshed every 30 s, no tweening.
- [~] **Accessibility**: map has a text alternative: "42 trains running. Busiest station right now: Embarcadero." in an *(live summary + List view done; 'busiest station' waits for ridership in the API (F4))*
      `aria-live="polite"` region updated every minute; a "View as list" toggle shows trains as a table (line, destination, next stop).
- **Done when:** trains move smoothly along the correct lines matching the published schedule at three spot-checked times,
  and the map looks right at 320, 390, 768, 1024, 1440 and 2560 px wide, in portrait and landscape.

### F4: KPI tiles + station panel (weeks 4–5, after M2)
- [x] API: `GET /api/kpis` (from `mart_kpis_daily`), `GET /api/stations/{code}/summary`. Cache in memory 1 h (data is daily). *(plus `/api/trends/ridership`, `/api/trends/bikes-vs-trains`; DuckDB or BigQuery via `TP_WAREHOUSE`)*
- [x] KPI tiles: grid with `repeat(auto-fit, minmax(min(100%, 220px), 1fr))`, so 1 column on phones, up to 4 on desktop, with no media queries.
- [x] Each tile: value, delta vs. 2019, one-line definition (from `METRICS.md`) behind an ⓘ toggle.
- [~] Trend charts: inline SVG with `viewBox` (no chart library needed; or Vega-Lite, which the agent's chart tool already uses).
      Re-layout on container resize; fewer x-axis ticks below 600 px. *("Ridership since 2019" and "Bikes and trains" done; hour × weekday heatmap not started)*
- [x] Skeleton loaders while loading; an error tile with "Retry" if the API fails; never a blank box.
- **Done when:** tiles show the same numbers as Looker Studio for the same date. *(tiles = mart values, checked by `tests/local`; Looker Studio doesn't exist yet)*

### F5: forecast explorer (week 6)
- [x] `GET /api/forecast/{station}` → 14 days with p10/p50/p90 + last 28 days of actuals.
- [~] Station picker: searchable combobox (type "mac" → MacArthur), plus chips for 5 popular stations. Clicking a station on the map also selects it. *(combobox + chips done; map click → forecast not done)*
- [x] Chart: actuals line + forecast line + shaded interval; plain-English caption ("Expect about 12,400 entries next Tuesday, likely between 11,100 and 13,600").
- **Done when:** works with keyboard only and on a phone in portrait. *(met: Playwright `forecast:` tests)*

### F6: Ask TransitPulse (weeks 8–9, after M5)
- [x] The hero Ask card: one input row ("Ask about BART or Bay Wheels ridership…"), 4 suggestion chips that fill and submit
      the question, black "Ask" pill. `Enter` submits.
- [~] Results open as a panel below the hero (full-screen sheet on phones), streaming `/api/ask` events: *(streaming client + all message states done; the agent itself is M5)*
  progress steps ("Writing SQL… Running query… Drawing chart…") → answer text → table/chart → **"Show SQL"** disclosure with copy button.
- [~] Friendly states: refusal ("I can only answer questions about the transit data. Try: …" + chips), guardrail rejection *(refusal / rate-limit / error / offline states in `web/js/ask.js`; guardrail message arrives with M5)*
      ("That query would scan too much data; try narrowing the date range"), rate limit ("Lots of questions right now — try again in a minute"), network error with Retry.
- [x] Tables scroll horizontally *inside* their card on small screens (never the page); first column sticky.
- [x] `aria-live` on the answer region; focus moves to the answer heading when it arrives.
- [ ] Keep the last 5 Q&As in `sessionStorage` so a refresh doesn't lose them.
- **Done when:** the 10 suggested/sample questions all return a correct answer on the deployed site, on a phone.

### F7: polish + QA (weeks 11–12, with M7)
- [~] **Playwright** tests (`tests/web/`) at 320, 390, 768, 1024, 1440, 1920 px: *(27 tests in `site.spec.js` + `data.spec.js` (API mocked with fixtures) cover all of these except screenshot snapshots)*
  - `document.documentElement.scrollWidth <= innerWidth` (no horizontal scroll) on every viewport
  - map canvas size equals container size × DPR after a resize
  - nav overlay opens/closes; Ask flow with the API mocked
  - screenshot snapshots for visual regression
- [ ] Lighthouse (mobile): Performance ≥ 90, Accessibility ≥ 95, Best Practices ≥ 95. LCP < 2.5 s, CLS < 0.1 (reserve space with `aspect-ratio` for map, charts and embeds).
- [ ] Contrast check with axe in Playwright: every text token on its allowed surfaces (`DESIGN.md §2`) meets WCAG AA.
- [ ] Design review: walk `web/styleguide.html` and every page section against `DESIGN.md`; fix drift in code, not in the doc.
      Move anything left in `DESIGN_BACKLOG.md` into a v1.1 list.
- [ ] Real-device check: an iPhone (Safari), an Android (Chrome), a tablet in both orientations, a desktop at 125% and 200% zoom.
- [ ] Looker Studio embed in a responsive wrapper (`aspect-ratio`, `loading="lazy"`); on phones show a "Open dashboard" pill instead of the iframe.
- [~] Meta: favicon, Open Graph image (a screenshot of the train map), `<title>`, description. *(favicon, title, description done; Open Graph image pending)*
- **Done when:** all of the above pass in CI and on the real devices.

---

## 5. API contract for the site

| Method | Path | Source | Cache |
|---|---|---|---|
| GET | `/data/network.json`, `/data/schedule-*.json` | static files from F2 | 1 day, hashed filenames |
| GET | `/api/kpis` | `marts.mart_kpis_daily` | 1 h |
| GET | `/api/stations/{code}/summary` | `marts.fct_station_daily` | 1 h |
| GET | `/api/forecast/{code}` | `marts.forecast_station_daily` | 6 h |
| GET | `/api/findings` | static JSON exported in M4 | 1 day |
| POST | `/api/ask` | LangGraph agent, SSE stream | none; rate-limited per IP (e.g. 10/min) to protect the Gemini quota |
| GET | `/healthz` | | none |

All BigQuery reads go through `sa-agent` (read-only) with `maximum_bytes_billed` set.

---

## 6. Definition of done for the whole project
- [ ] Public URL on Cloud Run; trains running on the map on a phone and a desktop.
- [ ] `make up` brings up the whole thing locally (API + web + Ollama) from a fresh clone.
- [ ] CI green: ruff, pytest, Playwright, dbt CI build, terraform plan.
- [ ] README has real numbers: raw data size, forecast MAE vs. baseline, agent accuracy (A/B/C), McNemar p-values, DiD estimate with CI, Locust p95, monthly cost.
- [ ] GCP bill for the month: $0.
- [ ] Portfolio entry added (see `TRANSITPULSE_PLAN.md §9`).

---

## 7. Risks

| Risk | Mitigation |
|---|---|
| GTFS shapes missing or misaligned with stops | Straight-segment fallback (F2); snap stops to the nearest polyline vertex. |
| Schedule ≠ reality (delays) | Label the map "Scheduled positions"; GTFS-RT delay overlay is an optional week-13 task. |
| Gemini free-tier rate limits during a demo | Per-IP rate limit, cached answers for the suggestion chips, friendly rate-limit message. |
| Cloud Run cold start makes the first visit slow | Static site loads independently of the API; map works from static JSON even while the API is cold. |
| Canvas blurry or misaligned after rotate/zoom | Single `ResizeObserver` handles every size change; DPR re-read on each resize; Playwright test covers it. |
| Scope creep on the frontend | F-track tasks are capped to the weeks shown; polish beyond F7 goes to a "later" list. |
