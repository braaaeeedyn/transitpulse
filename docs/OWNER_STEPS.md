# Owner steps

Everything left in TransitPulse that needs your accounts, a GUI tool, a device or a decision, in the order the steps
unblock each other. Each step says what to run or click, what you should see, and how to check it. All the work that
needed none of those is done and sits uncommitted in the working tree (built from commit `f441638`).

Commands run from the repo root in Git Bash (or any POSIX shell) unless a step says otherwise.

---

## 0. Review the working tree

```sh
git status
git diff --stat f441638
```

What changed since `f441638`, in short:
- **M5 A/B test:** retrieved example queries in the agent's SQL prompt (`api/agent/`), the eval arms, `eval/ab.py`,
  `docs/AB_TEST.md`, two committed eval summaries. Arm B won, so `agent_examples_k` now defaults to 5.
- **eBART post-hoc estimate** (not pre-registered): `analysis/causal/trend_adjusted.*`, a section in `docs/FINDINGS.md`.
- **BI build guide:** `bi/README.md` with a check week.
- **Website:** Ask history and Copy SQL, map → forecast, the busiest station in the map's text alternative, a
  dashboard slot, Open Graph tags + `web/img/og.png`, `web/styleguide.html`, axe and Lighthouse checks, gzip in the API.
- **`make up`:** `docker-compose.yml` (API + site + Ollama).
- **Docs:** README (diagram, screenshots), `CURRENT_STATE.md`, `DEVLOG.md`, this file.

Nothing under `pipeline/`, `dbt/`, `ml/`, `deploy/`, `infra/` or `.github/workflows/deploy.yml` changed, and neither
did `pyproject.toml` or `uv.lock`.

Run the local checks once more if you like (about 3 minutes, plus the Docker ones):

```sh
uv run ruff check . && uv run ruff format --check .
uv run --group dbt --group ml --group pipeline --group agent pytest -m "not spark and not gcp and not localdata and not docker"
node --test tests/web/ && npx playwright test
uv run --group dbt --group ml --group agent pytest -m localdata tests/local    # needs data/transitpulse.duckdb
uv run --group agent python -m eval.ab --check && uv run --group ml python -m analysis.causal.trend_adjusted --check
docker build -t transitpulse-api:loop . && uv run pytest -m docker tests/deploy tests/compose
uv run python tasks.py lighthouse --runs 3 --assert                             # local only, not in CI
```

**Expect:** everything passes (167 pytest, 37 node, 57 Playwright, 13 localdata, 6 + 3 Docker; Lighthouse about
98 / 100 / 100).

## 1. Commit and push to `main`

Leave `.claude/` out (it is local tool configuration). Your rule is no co-author line (DEVLOG, 2026-10-07); the
commands below add none. The four commits of 2026-10-14 (`ab55544`..`f441638`) carry one by mistake.
A suggested grouping (each `git add` takes the paths of one area):

```sh
git add api/agent api/settings.py eval/ab.py eval/examples.py eval/run_eval.py eval/results/summary-ollama-*.json tests/test_ab.py docs/AB_TEST.md
git commit -m "M5 A/B test: 5 retrieved example queries in the SQL prompt win (27% -> 50%, McNemar p = 0.004)"

git add analysis/causal/trend_adjusted.py analysis/causal/trend_adjusted.json tests/test_causal.py docs/FINDINGS.md
git commit -m "eBART: post-hoc trend-adjusted estimate (not pre-registered; the verdict is unchanged)"

git add bi tests/local/test_bi_week.py
git commit -m "BI build guide for Looker Studio and Power BI, with a check week"

git add web tests/web package.json package-lock.json api/main.py tests/test_ask_api.py
git commit -m "Site: Ask history and Copy SQL, map to forecast, dashboard slot, Open Graph, style guide, axe + Lighthouse, gzip"

git add docker-compose.yml tasks.py Makefile tests/test_compose.py tests/compose
git commit -m "make up: the site, API and Ask agent on an Ollama container"

git add README.md docs tests/test_docs_deliverables.py
git commit -m "Docs: README diagram and screenshots, owner steps, current state, devlog"

git status          # only .claude/ should be left
git push origin main
```

**Expect:** `git push` succeeds. The push **auto-deploys Cloud Run** (`DEPLOY_ENABLED=true`): `deploy.yml` builds,
smoke-tests, pushes and deploys the image. The live agent stays off (Terraform still says so), so the new default of
5 examples changes nothing visible yet.

## 2. Watch CI and the deploy

```sh
gh run list --repo braaaeeedyn/transitpulse --limit 5
gh run watch --repo braaaeeedyn/transitpulse        # pick the CI run, then the deploy run
curl https://transitpulse-api-etumz4pfva-uw.a.run.app/api/health
curl -s -o /dev/null -w "%{http_code} %header{content-encoding}\n" -H "Accept-Encoding: gzip" https://transitpulse-api-etumz4pfva-uw.a.run.app/api/findings
```

**Expect:** both runs green; `{"ok":true}`; `200 gzip` (the new image compresses JSON). If CI's web job fails on
`npm ci`, the lockfile and `package.json` were committed separately: commit both.

## 3. Re-export the pages

The website code changed, so publish it again (the export copies `web/` and points it at Cloud Run):

```sh
uv run python tasks.py export --api-base https://transitpulse-api-etumz4pfva-uw.a.run.app --to ../portfolio/static/transitpulse
cd ../portfolio
git add static/transitpulse
git commit -m "TransitPulse: Ask history, map to forecast, style guide, Open Graph"
git push
cd ../transitpulse
```

**Verify** once GitHub Pages has published (a minute or two):
- https://braedynthompson.com/transitpulse/ loads; tap a station on the map and the forecast explorer switches to it.
- https://braedynthompson.com/transitpulse/styleguide.html loads (it is `noindex`).
- The Open Graph preview: `curl -s https://braedynthompson.com/transitpulse/ | grep og:image` shows the absolute
  URL, and `curl -sI https://braedynthompson.com/transitpulse/img/og.png` answers `200` with `image/png`. Paste the
  page URL into a link-preview checker (LinkedIn Post Inspector, or a Slack/Discord message to yourself) to see the
  card with the map.

## 4. Oracle VM: update only if pipeline code changed

The rule, every time you pull new code:

```sh
git diff --stat f441638 -- pipeline dbt ml deploy pyproject.toml uv.lock
```

- **Non-empty:** wait for running Dagster jobs to finish (the restart kills them), then
  `ssh <user>@<vm> sudo bash /opt/transitpulse/deploy/oracle/bootstrap.sh` ([`ORACLE_VM.md`](ORACLE_VM.md) §8).
- **Empty:** nothing to do.

This run changed none of those paths (the loop's guard check proved it), so **no VM update is needed now**.

## 5. Decided: `deploy.yml` skips `terraform apply` (Terraform stays manual)

You chose on 2026-10-16 to keep Terraform manual: `deploy.yml` builds, pushes and deploys the image, and you run
`terraform plan` / `apply` locally for the rare infrastructure change, so CI never holds rights to change IAM,
secrets or billing. When an apply is needed is listed in [`infra/README.md`](../infra/README.md) "When to run
`terraform apply`". Nothing to do here.

## 6. Turn on the live agent

[`CLOUD_RUN.md`](CLOUD_RUN.md) §4, in this order:

1. **BigQuery quota first.** Console → IAM & Admin → Quotas → "BigQuery API" → **Query usage per day per user** →
   30 GiB. It applies to `sa-pipeline` too, which billed 16.9 GiB on a normal day and 49.8 GiB on the full backfill
   ([`CLOUD_RUN.md`](CLOUD_RUN.md) §4): raise it for the day of a full backfill.
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
   uv run --group agent python -m eval.ab --llm gemini:gemini-2.5-flash
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
6. **On a phone**, ask the 10 sample questions below on https://braedynthompson.com/transitpulse/. The expected
   answers come from the local DuckDB, which holds the same BART data as BigQuery for 2018–2025. Wording will differ;
   check the numbers and names. Also ask one off-topic question ("What's the weather tomorrow?"): it should be
   refused with three suggestion chips.

| # | Question (where it comes from) | Expected answer |
|---|---|---|
| 1 | Which stations grew most since 2022? (chip) | Orinda +54.7% (749 → 1,159 entries a day), Milpitas +54.1%, Lafayette +53.4%: average daily entries, 2025 vs 2022. Another comparison window may reorder these |
| 2 | Busiest hour on a weekday? (chip) | 5 PM: 5.15 million entries in that hour on 2025's service weekdays, ahead of 8 AM (4.68 million) |
| 3 | How close is ridership to 2019? (chip) | 2025 averaged 149,335 entries a day against 324,958 in 2019: about 46% of 2019 |
| 4 | Bikes vs. trains last month (chip) | BART data ends Dec 2025, so the latest month with both is Dec 2025: Bay Wheels trips at 191% of Dec 2019, BART entries at 43%. Bay Wheels in BigQuery runs to Sep 2026; an answer about a 2026 month should say BART has no data for it |
| 5 | Which stations had the most entries in 2025? (refusal chip) | Embarcadero, 4,787,378 entries |
| 6 | How close is weekday ridership to 2019? (refusal chip) | 43% of 2019 on 2025's service weekdays (the tile's Dec 2025 window: 38%) |
| 7 | What's the 14-day forecast for Embarcadero? (refusal chip) | 14 days, Jan 1–14, 2026: weekdays about 11,000–15,000 entries (Tue Jan 6 ≈ 14,200), weekends about 3,600–5,900. Production reads the VM's run in BigQuery, so values may differ a little from these local ones |
| 8 | What was the average daily BART ridership in 2019? (eval k02) | 324,958 entries a day |
| 9 | Which station has the highest peak-hour share? (eval s09) | Montgomery Street, 22.3% of its weekday entries in its peak hour |
| 10 | Which origin and destination had the most trips in 2019? (eval o04) | Balboa Park → Montgomery Street, 725,547 trips |

Then tap **Show SQL → Copy SQL** on one answer, reload, and check the answers are still listed under the Ask card.

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
- [ ] Ask: before step 6 it says the analyst isn't connected; after step 6 one question answers, Copy SQL works,
      and the answer is still listed after a reload.
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
