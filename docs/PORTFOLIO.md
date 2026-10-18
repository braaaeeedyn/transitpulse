# TransitPulse: Bay Area transit analytics, from raw ridership to a live site

**Live:** https://braedynthompson.com/transitpulse/ · **Code:** github.com/braaaeeedyn/transitpulse · **Role:** sole
developer (data platform, warehouse, models, causal study, AI agent, website, cloud deployment)

> Eight years of BART ridership (67.8 million hourly origin-destination rows) and Bay Wheels bike trips (26 million),
> cleaned with PySpark, modelled with dbt on BigQuery and orchestrated by Dagster on a free Oracle VM. On top: a
> 14-day forecast for every station, a pre-registered causal study of the eBART extension, an analysis of the BART
> stations named for possible closure, and an AI analyst that answers questions in plain English by writing guarded
> SQL. The website draws every BART train from the timetable on a live map.

This file is the portfolio's summary of the project as it is now (2026-10-18). Every number comes from the docs
linked in §8; nothing here is newer than they are.

---

## 1. Status

Everything below is live and runs itself:
- **Site:** static pages on GitHub Pages (braedynthompson.com/transitpulse), calling the API across origins.
- **API + Ask agent:** FastAPI on Cloud Run (us-west1), scales to zero, at most 2 instances. Ask runs on Gemini
  (`gemini-3.5-flash-lite`) since 2026-10-16. Every push to `main` builds, smoke-tests and deploys the image.
- **Pipeline:** Dagster on the Oracle VM it shares with SeismicSoCal, in `gcp` mode. BART is checked every 6 hours and
  reloaded when its file changes; dbt rebuilds after each ingest; Bay Wheels reloads on the 7th; a full rebuild runs
  on the 6th; the forecast retrains every Monday.
- **Cost:** $0 expected (every service inside its free tier; $1 and $5 budget alerts as code).

Not built: the Looker Studio and Power BI reports (a build guide, DAX measures and a check week are ready in
`bi/README.md`), and the M6 QLoRA fine-tune (deferred). LLM tracing (Langfuse) was dropped: it was wired in but
never switched on.

## 2. What a visitor sees (top to bottom)

1. **Nav and hero.** A pulse stripe in the six line colours, "See the Bay Area move", a live strip (trains moving
   now, % of 2019 ridership, the data date, counted up) and a **departure board** with the six soonest arrivals,
   fed by the map every 10 seconds. A sun/moon toggle switches the whole page to dark mode.
2. **Live map.** Every BART train where the timetable says it is, moving in real time (or 10× / 60×, or scrubbed
   with a time slider). Tap a train or a station for details; a list view shows the running trains as a table;
   the legend filters lines.
3. **What if stations close?** Under the map: close BART's listed stations (the first 10, all 15, or one at a time).
   They disappear from the map, and the same trains keep their timetable at every open station but run through the
   closed ones without stopping. A status line gives the share of weekday trips that start or end there.
4. **Trends.** Tiles (recovery vs 2019, average daily entries, peak-hour share, busiest station) and two charts,
   ridership over time and bikes vs trains, with a hover readout.
5. **Forecast explorer.** Pick a station (or tap it on the map): 14 days ahead with a calibrated model range and the
   fortnight's busiest and quietest days.
6. **Findings.** The eBART causal study: the verdict, the estimates with placebo intervals and two event-study
   charts.
7. **Station closures.** The 15 stations BART staff named in February 2026 if the Nov 3 sales-tax measure fails:
   summary tiles, a cited "What closing would cost" card, one card per station (2025 weekday trips, rank, nearest
   open station, top destinations, the four rules met or not, a "case to keep" verdict), caveats and 13 sources.
   The page takes no position on the measure.
8. **Ask TransitPulse.** A side panel (the train mascot in the corner, or `/`): ask in plain English and watch the
   steps stream in (thinking → SQL → rows → answer), then "Show SQL" / "Copy SQL". Off-topic questions are refused
   with suggestions. The last 5 answers survive a reload.

A style guide (`/transitpulse/styleguide.html`) shows every token and component in light and dark mode.

## 3. Headline numbers

| What | Number | Source |
|---|---|---|
| BART ridership in BigQuery | 67,770,440 hourly origin-destination rows, 2018–2025, 4.2 GB | README |
| Bay Wheels | 25,989,969 trips, 2018 → Sep 2026 | README |
| Warehouse | 17 dbt models, 84 data tests | `dbt ls` |
| Forecast (14 days, every station, 6 walk-forward folds) | MAE **283.1** vs **548.5** for the seasonal-naive baseline: 265.4 fewer entries/day off, 95% CI [199.6, 339.9]. The p10–p90 band holds 73% of days (nominal 80%), so the site calls it a "model range" | `METRICS.md` |
| Ask agent A/B (llama3.1:8b, local, pre-registered) | Execution accuracy **0.27 → 0.50** with 5 retrieved example queries: +22.7 points, 95% CI [+9.1, +36.4], exact McNemar p = 0.004. Refusal accuracy 1.0 in both arms | `AB_TEST.md` |
| eBART (pre-registered difference-in-differences, 34 control stations) | Whole line **+4.2%** [+1.6%, +7.1%]; the three old stations **−23.9%**. Verdict: "new" riders, mostly moved from the old stations. Net of the pre-opening trend (post-hoc): +1.0% [−2.4%, +4.2%], not distinguishable from trend | `FINDINGS.md` |
| Station closures | 9 of the first 10 are among BART's 10 least-used stations; 12.6% of weekday trips start or end at the first 10, 24.1% at all 15. Case to keep: strong 6, mixed 7, weak 2 | `STATION_CLOSURES.md` |
| Cloud Run | Cold start about 4.4 s to the first byte; warm requests 0.09–0.17 s; image 119 MB compressed | README |
| Load test (local, fixture warehouse, fake LLM) | 25 users: ~30 req/s, forecast p95 14 ms, Ask p95 140 ms, 0 failures | README |
| Lighthouse (mobile, 2026-10-14, before the v1.1 redesign) | 98 / 100 / 100 (performance / accessibility / best practices) | README |
| Tests | 179 pytest, 52 node, 75 Playwright (incl. axe contrast in light and dark mode at 390 and 1440 px), plus checks on the real local data | CI |

## 4. How it's built

- **Ingest and cleaning.** PySpark with an explicit schema, `PERMISSIVE` corrupt-record handling and one drop reason
  per bad row, logged to an audit table; Bay Wheels through DuckDB (irregularly named monthly zips in two schemas). Raw
  files stay unchanged in GCS.
- **Warehouse.** dbt on BigQuery (DuckDB locally, same models): staging → a star schema → marts, an SCD2 station
  snapshot, incremental facts, 84 data tests. One KPI definition per number (`METRICS.md`) feeds the site and the
  agent.
- **Orchestration.** Dagster software-defined assets with lineage from download to marts, yearly partitions, a
  sensor on BART's files, schedules; systemd units on the VM with memory caps so SeismicSoCal keeps priority.
- **Forecasting.** Three LightGBM quantile regressors (p10/p50/p90) on level-scaled targets across all stations,
  with calendar and holiday features, walk-forward evaluation
  against a seasonal-naive baseline with a bootstrap CI, and a split-conformal calibrated band.
- **Causal inference.** Pre-registered before any result was seen (plus one dated amendment): difference-in-differences
  with placebo intervals, weekly and monthly event studies, a spillover check, and a post-hoc trend-adjusted
  estimate reported as such.
- **AI agent.** LangGraph: a router, SQL generation with 5 retrieved example queries and one repair retry, a forecast
  tool, and an answer that cites its SQL. Guardrails: a sqlglot AST check (one SELECT, a table allowlist, no file
  readers, LIMIT clamped), a read-only service account, a BigQuery dry run that refuses anything over 1 GB, a 10 GB
  daily byte budget, and 10 questions per IP per minute. Evaluated on 66 gold-SQL questions + 10 off-topic ones.
- **Policy analysis.** A dbt seed of the 15 listed stations and three marts (per-station 2025 trips, ranks, recovery,
  distance to the nearest open station, change on the year; top destinations; scenario shares), four "case to keep"
  rules on rounded numbers, and a write-up that checks the press's claims against the data.
- **Website.** Vanilla ES modules, no framework: an SVG network with trains on a canvas, interpolated from the GTFS
  timetable; the what-if picker re-times trips past closed stations; design tokens, fluid sizing from 320 px phones to
  2560 px screens, dark mode, reduced-motion support.
- **Shipping.** Terraform for everything in GCP (BigQuery, GCS, Artifact Registry, Cloud Run, IAM, budgets), keyless
  GitHub → GCP deploys through Workload Identity Federation pinned to this repo's `main`, a multi-stage non-root
  container smoke-tested before every deploy.

## 5. Proofs by role

| Role | Proof |
|---|---|
| Data Engineer | Dagster + PySpark + dbt on BigQuery, 68M rows, 84 data tests, running unattended on a VM; Terraform; keyless CI/CD |
| Data Analyst | dbt KPI marts (recovery vs 2019, peak share, bikes vs trains); the station closures analysis with stated rules and sources |
| Data Scientist | Pre-registered DiD with placebo intervals; a pre-registered A/B with a power analysis and McNemar's test |
| ML Engineer | LightGBM station forecasts with walk-forward folds, a bootstrap CI and conformal calibration, retrained weekly |
| AI Engineer | A guarded text-to-SQL agent on LangGraph, an execution-accuracy eval set, an A/B of retrieval, live on Gemini |
| Front-end | A live timetable map, the what-if simulation, axe-tested contrast in both themes, Lighthouse 98/100/100 |

## 6. Honest limits

- The agent's 50% is llama3.1:8b on its own eval set; the live agent runs Gemini, which hasn't been scored on the full
  set.
- The eBART "new riders" verdict rests on 3 treated stations and is not distinguishable from the pre-opening trend.
- The forecast band under-covers (73% for a nominal 80%), which the site says.
- The map shows the timetable, not live train positions.
- The closures verdicts weigh ridership, recovery, distance and growth only; they can't see cost, fairness or what
  riders would do instead, and BART's list is not final.

## 7. Images

| File | What |
|---|---|
| `docs/img/screenshot-desktop.png` | 1440 px: the hero with the departure board, the live map, the what-if card |
| `docs/img/screenshot-phone.png` | 390 px: the live map band on a phone |
| `docs/img/findings-event-study-weekly.png`, `findings-event-study-monthly.png` | The eBART event studies |
| `web/img/og.png` | The train map, 1200 × 630 (the link preview) |

Worth taking from the live site: the Station closures band (a strong and a weak card side by side), the map with
"Close the first 10" on, an Ask answer with "Show SQL" open, and the page in dark mode.

## 8. Sources (read these for detail)

| File | What |
|---|---|
| [`README.md`](../README.md) | Overview, progress, results, architecture diagram, how to run |
| [`CURRENT_STATE.md`](CURRENT_STATE.md) | How every part works right now |
| [`SKILLS_MAP.md`](SKILLS_MAP.md) | Each skill, where it is in the code (exact lines) and how it works |
| [`METRICS.md`](METRICS.md) | KPI and forecast definitions |
| [`FINDINGS.md`](FINDINGS.md) | The eBART study |
| [`AB_TEST.md`](AB_TEST.md) | The agent A/B test |
| [`STATION_CLOSURES.md`](STATION_CLOSURES.md) | The station closures analysis |
| [`DESIGN.md`](DESIGN.md) | The design system (v1.1.5) |
