# Owner steps

Everything left in TransitPulse that needs your accounts, a GUI tool, a device or a decision. Each step says what to
run or click, what you should see, and how to check it. **Updated 2026-10-18:** everything is committed and pushed;
https://braedynthompson.com/transitpulse/ runs the latest pages (station closures, the what-if map, dark mode);
`/api/closures` answers from BigQuery; Ask is live on Gemini. The VM runs the latest pipeline code. Open now: the dated
jobs in step 3 and the account steps from step 6 on.

Commands run from the repo root in Git Bash (or any POSIX shell) unless a step says otherwise.

---

## 0. Where everything runs

| What | Where |
|---|---|
| Site | https://braedynthompson.com/transitpulse/ (GitHub Pages of the `portfolio` repo, folder `static/transitpulse`) |
| API | https://transitpulse-api-etumz4pfva-uw.a.run.app (Cloud Run `transitpulse-api`, us-west1) |
| Warehouse | BigQuery project `transitpulse-511002` (datasets `raw`, `staging`, `marts`, `ml`) |
| Pipeline | Dagster on the Oracle VM shared with SeismicSoCal: `ubuntu@167.234.214.169` (`seismicsocal.duckdns.org`), key `~/.ssh/oracle_seismic` (it asks for the key's passphrase) |

Log in to the VM (in PowerShell, write the key as `$HOME\.ssh\oracle_seismic`):

```sh
ssh -i ~/.ssh/oracle_seismic ubuntu@167.234.214.169
```

The Dagster UI: `ssh -i ~/.ssh/oracle_seismic -N -L 3000:127.0.0.1:3000 ubuntu@167.234.214.169`, then http://localhost:3000
([`ORACLE_VM.md`](ORACLE_VM.md) §5).

## 1. Update the VM (when pipeline code changes)

The VM runs the code it last pulled. Update it whenever `pipeline/`, `dbt/`, `ml/`, `deploy/`, `pyproject.toml` or
`uv.lock` change on `main` (last done 2026-10-18 at `6671168`: the closures models and the Langfuse removal). Wait
for running Dagster jobs to finish (the restart kills them; the UI's Runs page shows them), then:

```sh
ssh -i ~/.ssh/oracle_seismic ubuntu@167.234.214.169 'sudo bash /opt/transitpulse/deploy/oracle/bootstrap.sh'
```

**Expect:** it ends with both units `active (running)`. **Check:**

```sh
ssh -i ~/.ssh/oracle_seismic ubuntu@167.234.214.169 'sudo -u transitpulse git -C /opt/transitpulse log -1 --format=%h; systemctl is-active transitpulse-dagster-daemon transitpulse-dagster-web'
```

prints the same commit as `git log -1 --format=%h origin/main` here, then `active` twice (git runs as `transitpulse`, which owns
the checkout; as `ubuntu` it stops with "dubious ownership"). The closures tables are already in BigQuery (step 4),
so nothing needs materializing by hand; the next monthly run rebuilds them with the rest.

## 2. After every push: CI and the deploy

`git push origin main` runs CI and `deploy.yml` (build, smoke-test, push and deploy the API image). Watch them at
https://github.com/braaaeeedyn/transitpulse/actions (`gh` isn't installed on this PC), or:

```sh
curl -s "https://api.github.com/repos/braaaeeedyn/transitpulse/actions/runs?per_page=4" | grep -E '"(name|status|conclusion)"'
curl https://transitpulse-api-etumz4pfva-uw.a.run.app/api/health
```

**Expect:** both runs `success`; `{"ok":true}`.

## 3. Re-export the pages (when `web/` changed), and the dated jobs

The site is a copy of `web/` in the portfolio repo, pointed at Cloud Run. After a push that changed `web/`:

```sh
uv run python tasks.py export --api-base https://transitpulse-api-etumz4pfva-uw.a.run.app --to ../portfolio/static/transitpulse
cd ../portfolio
git add static/transitpulse        # only this folder: build.py and pages.py hold your own uncommitted work
git commit -m "TransitPulse: <what changed>"
git push
cd ../transitpulse
```

**Verify** once GitHub Pages has published (a minute or two): https://braedynthompson.com/transitpulse/ loads, the
trains move, "Close the first 10" under the map leaves 40 of 50 stations, and the Station closures band shows 15
cards. Ctrl+F5 skips the browser's cached CSS. The style guide is at `/transitpulse/styleguide.html` (`noindex`).

**After Nov 3, 2026: the closures copy.** The band and `docs/STATION_CLOSURES.md` describe the measure as upcoming.
After the election, edit the context paragraph in `web/index.html` and the status line of the write-up, then
re-export. If the BART board votes on a final list, edit `dbt/transitpulse/seeds/bart_closure_candidates.csv`, the
station lists in the write-up and its tests, and `AT_RISK` in `web/js/map/whatif.js` (a test keeps it equal to the
seed); then rebuild the tables (step 4), push and re-export.

**Around Jan 1, 2027: restart the VM's daemon** so Dagster offers 2027's partitions
([`ORACLE_VM.md`](ORACLE_VM.md) §8):

```sh
ssh -i ~/.ssh/oracle_seismic ubuntu@167.234.214.169 'sudo systemctl restart transitpulse-dagster-daemon'
```

**Before about Jan 6, 2027: upgrade from the free trial** (step 12), or Cloud Run and the API stop.

**Before Jan 10, 2027: new BART timetable.** The map reads `data/schedule.json` from this export, and the
timetable in it ends on **Jan 10, 2027**. After that the map shows "This site's BART timetable ended…" instead of
trains (the VM refreshes GTFS monthly, but only on the VM). Once BART has posted its next schedule (usually a few weeks
before), rebuild the map data from the current feed, commit it, and re-export:

```sh
uv run --group pipeline python -m pipeline.webdata.build     # downloads BART's current GTFS
python -c "import json; print(max(s['end'] for s in json.load(open('web/data/schedule.json'))['services']))"   # must be after 20270110
git add web/data && git commit -m "Map: BART timetable from <date>" && git push
```

then run the export above again.

## 4. Rebuild the closures tables (only when the seed or its marts change)

Built on BigQuery from this PC on 2026-10-18 (`PASS=15`); the VM's monthly run keeps them current once step 1 is done.
Run this only after changing `bart_closure_candidates.csv` or the closures marts. In PowerShell (it needs
`gcloud auth application-default login` once):

```powershell
$env:DBT_TARGET = "dev"; $env:TP_GCP_PROJECT = "transitpulse-511002"
uv run --group dbt dbt build --select bart_closure_candidates+ --project-dir dbt/transitpulse --profiles-dir dbt/transitpulse
```

(In Git Bash: `DBT_TARGET=dev TP_GCP_PROJECT=transitpulse-511002 uv run --group dbt dbt build …`.) **Expect:**
`PASS=15`. **Check:** `curl -s https://transitpulse-api-etumz4pfva-uw.a.run.app/api/closures | head -c 200` starts
with `{"period_year":2025` (the API caches for an hour). If you set up CI's BigQuery identity (step 9),
`dbt build --target ci` is the real BigQuery check of new SQL.

## 5. Decided: `deploy.yml` skips `terraform apply` (Terraform stays manual)

You chose on 2026-10-16 to keep Terraform manual: `deploy.yml` builds, pushes and deploys the image, and you run
`terraform plan` / `apply` locally for the rare infrastructure change, so CI never holds rights to change IAM,
secrets or billing. When an apply is needed is listed in [`infra/README.md`](../infra/README.md) "When to run
`terraform apply`". Nothing to do here.

## 6. The live agent (on since 2026-10-16)

Done except the BigQuery quota (6.1, after step 12's upgrade) and the optional Gemini A/B (6.3). The steps stay
here for reference; the questions at the end are the check after any agent change.

[`CLOUD_RUN.md`](CLOUD_RUN.md) §4, in this order:

1. **BigQuery quota first.** Console → IAM & Admin → Quotas → "BigQuery API" → **Query usage per day per user** →
   30 GiB (30720 MiB). It applies to `sa-pipeline` too, which billed 16.9 GiB on a normal day and 49.8 GiB on the full
   backfill ([`CLOUD_RUN.md`](CLOUD_RUN.md) §4): raise it for the day of a full backfill. **A free-trial account can't
   change quotas** ("free trial does not permit quota increase"): the agent went live on 2026-10-16 without it, held
   by its own caps (1 GB a query, 10 GB a day per instance, at most 2 instances), and the quota is set after step 12's
   upgrade.
2. **The Gemini key** (Google AI Studio), as a new secret version:
   ```sh
   printf '%s' "$GEMINI_KEY" | gcloud secrets versions add transitpulse-gemini-api-key --data-file=- --project transitpulse-511002
   ```
   **Expect:** "Created version [1] of the secret".
3. **Optional: the Gemini A/B.** The M5 A/B ran on llama3.1:8b; production runs Gemini. On this PC, with the local
   warehouse:
   ```sh
   export GOOGLE_API_KEY="$GEMINI_KEY"
   uv run --group agent python -m eval.run_eval --llm gemini --arm A --save-summary
   uv run --group agent python -m eval.run_eval --llm gemini --arm B --save-summary
   uv run --group agent python -m eval.ab --llm gemini:gemini-3.5-flash-lite
   ```
   Each arm is 76 questions at about 2–4 model calls each. Check the current free-tier daily request cap for the
   model in AI Studio first; if one arm doesn't fit in a day, run arm A today and arm B tomorrow. Commit the two
   `eval/results/summary-gemini-*.json` files and add a Gemini section to `docs/AB_TEST.md` (or ask for a loop to
   write it).
4. Set **`agent_enabled = true`** in `infra/terraform/terraform.tfvars`.
5. Plan, then apply:
   ```sh
   terraform -chdir=infra/terraform plan      # expect: 1 to add (secret accessor), 1 to change (the service env)
   terraform -chdir=infra/terraform apply
   ```
6. **On a phone**, tap the train in the bottom-right corner and ask the 10 sample questions below on https://braedynthompson.com/transitpulse/. The expected
   answers come from the local DuckDB, which holds the same BART data as BigQuery for 2018–2025. Wording will differ;
   check the numbers and names. Also ask one off-topic question ("What's the weather tomorrow?"): it should be
   refused with three suggestion chips.

| # | Question (where it comes from) | Expected answer |
|---|---|---|
| 1 | Which stations grew most since 2022? (chip) | Orinda +54.7% (749 → 1,159 entries a day), Milpitas +54.1%, Lafayette +53.4%: average daily entries, the last 12 months of data vs 2022 |
| 2 | Bikes vs. trains last month (typed, not a chip) | Should be answered, not refused (since 2026-10-16 it skips the model's router). Its SQL is the model's own, so check the month: BART data ends Dec 2025 |
| 3 | How close is ridership to 2019? (chip) | 2025 averaged 149,335 entries a day against 324,958 in 2019: about 46% of 2019 |
| 4 | Bikes vs. trains in the latest month? (chip) | BART data ends Dec 2025, so the latest month with both is Dec 2025: Bay Wheels trips at 191% of Dec 2019, BART entries at 43%. Bay Wheels in BigQuery runs to Sep 2026; an answer about a 2026 month should say BART has no data for it |
| 5 | Which stations had the most entries in 2025? (chip) | Embarcadero, 4,787,378 entries |
| 6 | How close is weekday ridership to 2019? (refusal chip) | 43% of 2019 on 2025's service weekdays (the tile's Dec 2025 window: 38%) |
| 7 | What's the 14-day forecast for Embarcadero? (chip) | 14 days, Jan 1–14, 2026: weekdays about 11,000–15,000 entries (Tue Jan 6 ≈ 14,200), weekends about 3,600–5,900. Production reads the VM's run in BigQuery, so values may differ a little from these local ones |
| 8 | What was the average daily BART ridership in 2019? (eval k02) | 324,958 entries a day |
| 9 | Which station has the highest peak-hour share? (chip; eval s09) | Montgomery Street, 22.3% of its weekday entries in its peak hour |
| 10 | Which origin and destination had the most trips in 2019? (eval o04) | Balboa Park → Montgomery Street, 725,547 trips |

Then tap **Show SQL → Copy SQL** on one answer, reload, open the panel again (the train in the corner), and check the answers are still listed.

## 7. Looker Studio

Follow [`bi/README.md`](../bi/README.md) "Looker Studio": connect BigQuery (`transitpulse-511002`, the `marts`
dataset), build the tiles and charts, share it as "anyone with the link", then **File → Embed report → Enable
embedding → Embed URL**. Paste that URL into `web/index.html`:

```html
<meta name="tp-looker-url" content="https://lookerstudio.google.com/embed/reporting/<report-id>/page/<page-id>" />
```

Check it locally (`uv run python tasks.py api`, then the Trends band shows a "Dashboard" card; on a phone width an
"Open dashboard" pill), commit and push, then **repeat step 3** to publish it. Check the dashboard's KPIs against the
check week in `bi/README.md`.

## 8. Power BI

Follow [`bi/README.md`](../bi/README.md) "Power BI Desktop": Get Data → Google BigQuery, the DAX measures, and the
check week 2025-W39 (1,128,303 entries; recovery 0.4385; peak-hour share 0.1169; Embarcadero). Save
`bi/transitpulse.pbix`, export a PDF and two screenshots into `bi/`, commit them, and tick the Power BI line of M2 in
`docs/IMPLEMENTATION_PLAN.md`.

## 9. CI GCP identity: decisions first

CI cannot run `dbt build --target ci` or `terraform plan` yet: both need a GCP identity, and three choices only you
can make come first.

1. **The billing budget in `terraform plan`.** `main.tf` manages a `google_billing_budget`, so a full plan needs
   `roles/billing.viewer` on the billing account. Either grant that to the CI account, or keep the budget out of the
   CI plan (a separate root module or `-target`ed plans).
2. **The dbt `ci` target's cost cap.** It caps queries at 500 MB billed, and a cold build scans all of
   `raw.bart_od` (4.2 GB). Either add a ci-only data window (recommended: Jan 2019 + Jan 2025, like the test
   fixture), or raise the cap (every CI run then bills about 4 GB against the 1 TiB monthly free tier).
3. **Secrets.** CI's plan needs your `terraform.tfvars` values (billing account id, alert email) as GitHub secrets.

**Recommended design** once you've decided:
- Runs on `main` only, through the existing WIF provider (its condition already allows only
  `refs/heads/main` of this repo). Don't add a provider for pull-request refs: the pool's `principalSet` is
  per repository across providers, so PR branches could then impersonate `sa-deploy`.
- A new `sa-ci` service account with: `roles/viewer` and `roles/iam.securityReviewer` on the project;
  `roles/storage.objectUser` on the `transitpulse-511002-tfstate` bucket (state locking); `roles/bigquery.jobUser`
  on the project, `roles/bigquery.dataViewer` on `raw`, `roles/bigquery.dataEditor` on a `ci` dataset; plus
  `roles/billing.viewer` if you chose that in decision 1.
- Then start a follow-up `/build-loop` to write `infra/terraform/ci.tf` and a CI job gated on
  `vars.CI_GCP_ENABLED`. Only running `plan` as that identity proves the role list, so it needs your apply.

## 10. Real-device check

On real devices (not emulators): an **iPhone** (Safari), an **Android** phone (Chrome), a tablet in portrait and
landscape, and a desktop browser at 125% and 200% zoom. On each:

- [ ] The map's trains move (or the out-of-service card shows, at night); zoom − / + work.
- [ ] No sideways scroll anywhere on the page.
- [ ] The nav menu opens, closes with ✕, and its links jump to their sections (phone and tablet).
- [ ] Forecast picker: type "mac", pick MacArthur; tap a station on the map and the explorer switches to it.
- [ ] Findings band: the verdict, both figures and both charts are readable.
- [ ] Ask: one question answers, Copy SQL works, and the answer is still listed after a reload.
- [ ] What-if: "Close the first 10" leaves 40 stations, the trains still move, and "Today's map" brings them back.
- [ ] Dark mode (the moon in the nav): every band is readable, and the departure board and footer stay dark.
- [ ] Desktop at 200% zoom: text reflows, nothing overlaps.

Write any problem in `docs/DESIGN_BACKLOG.md` (design) or as an issue (bug), and tick the real-device line of F7 in
`docs/IMPLEMENTATION_PLAN.md` when all pass.

## 11. Optional: Locust against Cloud Run

```sh
uv run --group load locust -f load/locustfile.py --host https://transitpulse-api-etumz4pfva-uw.a.run.app \
  --headless --users 10 --spawn-rate 2 --run-time 2m --csv cloudrun
```

Caveats:
- Every simulated user asks one question when it starts. With the agent off, `/api/ask` answers 503 and Locust
  counts those as failures: read only the `kpis` and `forecast` rows, or run this after step 6.
- With the agent on, every question costs Gemini tokens and BigQuery bytes, and the agent allows 10 questions per IP
  a minute, so most `ask` requests from one machine will be 429s. Use `--users 1` if you want clean `ask` numbers.
- The service scales to 2 instances at most, so this measures that ceiling, and the first requests include a cold
  start. Put the p50/p95/p99 in the README's load-test section next to the local numbers.

## 12. Month-end bill

At the start of next month: Console → **Billing → Reports**, filter the project `transitpulse-511002`, last month.
**Expect: $0** (everything runs inside free tiers; `CLOUD_RUN.md` "Costs" lists them). Write the month and the amount
into the README's "GCP cost" row under Results.

**Before about Jan 6, 2027: upgrade from the free trial.** The project runs on a GCP free trial (82 days left on
2026-10-16). When a trial ends without an upgrade, Google stops its resources, so Cloud Run, and with it the site's
API and Ask, would go down. Console → Billing → **Upgrade** (to a full account). The free tiers still apply, so the
bill should stay at $0, and the $1/$5 budget alerts still email you. Then set the BigQuery quota from step 6.1.

## 13. Decision: start M6 (QLoRA fine-tune) as its own loop

M6 was deferred, not dropped: none of its toolchain is on this PC yet. If you want it, start a new `/build-loop` for
M6. What it costs:

- **Disk:** about 12–15 GB free at peak (CUDA torch, the Hugging Face cache, a merged fp16 model and the GGUF). The
  disk is at 93% now (36 GB free); the Ollama image from `make up` takes 9.4 GB inside Docker's disk
  (`docker rmi ollama/ollama:0.40.4` frees it there; Docker Desktop doesn't shrink its disk file on its own).
- **Downloads:** about 6–8 GB (CUDA torch, transformers, peft, trl, bitsandbytes, llama.cpp, the
  Qwen2.5-Coder-1.5B-Instruct weights).
- **Time:** 1–2 h of RTX 4060 training, plus building a 1–3K question → SQL training set with execution checks.

The A/B harness is ready for it: arm C plugs into `eval.ab` (see [`AB_TEST.md`](AB_TEST.md), "Arm C").
