# Runbook: the website + API on Cloud Run

How to put the site and API on Cloud Run with the code in this repo. **None of this has been run yet.** The service,
Workload Identity Federation and the deploy workflow exist only as code until you do the steps below. Nothing deploys
by itself: `deploy.yml` is off until you set the `DEPLOY_ENABLED` repository variable.

| Piece | File |
|---|---|
| Image (multi-stage, non-root uid 10001, `api/` + `web/` + the locked runtime venv) | [`Dockerfile`](../Dockerfile), [`.dockerignore`](../.dockerignore) |
| Service, public invoker, Gemini secret | [`infra/terraform/cloudrun.tf`](../infra/terraform/cloudrun.tf) |
| GitHub → GCP keyless auth, deployer rights | [`infra/terraform/wif.tf`](../infra/terraform/wif.tf) |
| Build → push → deploy on `main` (gated) | [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) |
| Image checks in CI and locally | `container` job in [`ci.yml`](../.github/workflows/ci.yml), [`tests/deploy/test_container.py`](../tests/deploy/test_container.py) |
| Static checks on the Terraform and workflow | [`tests/test_infra_cloudrun.py`](../tests/test_infra_cloudrun.py) |

## What gets created

- **Cloud Run service `transitpulse-api`** (us-west1):
  - 0–2 instances, 1 vCPU, 512 MiB, up to 80 concurrent requests per instance, 60 s request timeout
  - `cpu_idle = true`: CPU is billed only while a request is being handled
  - runs as **`sa-agent`**, which can only read `marts` and `ml` and run query jobs
  - env: `TP_WAREHOUSE=bigquery`, `TP_GCP_PROJECT`, `TP_TRUST_PROXY=true` (rate limiting uses the IP that
    Cloud Run's front end appends to `X-Forwarded-For`), `TP_AGENT_ENABLED=false`
- **`roles/run.invoker` for `allUsers` on this one service.** That makes the site public. Nothing else in the project
  is granted to `allUsers`.
- **Secret `transitpulse-gemini-api-key`, with no version.** You add the key yourself, so it never lands in Terraform
  state. The service reads it only when `agent_enabled = true`.
- **Workload Identity Federation:** pool `github`, provider `transitpulse`. Only tokens with
  `assertion.repository == "braaaeeedyn/transitpulse" && assertion.ref == "refs/heads/main"` are accepted, so forks,
  pull requests and other branches get nothing.
- **What `sa-deploy` is allowed to do, and nothing more (no owner/editor):**
  - `artifactregistry.writer` on the `transitpulse` repo
  - `run.developer` on this service
  - `iam.serviceAccountUser` on `sa-agent` only
- The `secretmanager.googleapis.com` API.

**Decision: CI never runs Terraform.** `terraform apply` from Actions would need owner-level rights for `sa-deploy`.
So Terraform stays a manual step (below), and `deploy.yml` changes only the image. This differs from
IMPLEMENTATION_PLAN M7 ("build → push → `terraform apply` → deploy").

## Before you start

- The M0 infrastructure is applied ([`infra/README.md`](../infra/README.md)), and `terraform plan` shows no changes
  before you pull this code.
- `gcloud auth login` and `gcloud auth application-default login` as the project owner.
- Docker, if you want to try the image locally first:
  ```sh
  docker build -t transitpulse-api:loop .
  uv run pytest -m docker tests/deploy      # non-root, site + headers, 503 without a warehouse, agent refusal
  ```
- **Org policy:** a project inside an organisation may block `allUsers` (`constraints/iam.allowedPolicyMemberDomains`,
  "Domain restricted sharing"). Check it with
  `gcloud resource-manager org-policies describe iam.allowedPolicyMemberDomains --project transitpulse-511002 --effective`.
  A personal project with no organisation has no such policy.

## 1. Plan and apply (you, locally)

```sh
cd infra/terraform
terraform init              # already initialised: no -upgrade (stay on google ~> 6.0)
terraform plan -out cloudrun.tfplan
```

**Read the plan.** It should show **10 to add, 0 to change, 0 to destroy**:
- `google_project_service.enabled["secretmanager.googleapis.com"]`
- `google_secret_manager_secret.gemini_api_key`
- `google_cloud_run_v2_service.api`
- `google_cloud_run_v2_service_iam_member.public_invoker` and `.deploy_developer`
- `google_iam_workload_identity_pool.github`
- `google_iam_workload_identity_pool_provider.github`
- `google_service_account_iam_member.deploy_wif` and `.deploy_acts_as_agent`
- `google_artifact_registry_repository_iam_member.deploy_writer`

Anything that changes or destroys an existing resource (datasets, bucket, budgets, service accounts) means something
is wrong. **Stop and don't apply.**

```sh
terraform apply cloudrun.tfplan
terraform output             # api_url, github_wif_provider, github_deploy_service_account
```

The service starts on Google's placeholder image (`us-docker.pkg.dev/cloudrun/container/hello`). `api_url` then shows
the "It's running!" page. Terraform ignores the image from then on (`lifecycle.ignore_changes`), so a later
`terraform apply` never rolls back what CI deployed.

## 2. First real image (by hand, optional but recommended)

Do this once by hand so you see the real site before switching CI on:

```sh
REGION=us-west1; PROJECT=transitpulse-511002
IMAGE=$REGION-docker.pkg.dev/$PROJECT/transitpulse/api:manual-$(git rev-parse --short HEAD)
gcloud auth configure-docker $REGION-docker.pkg.dev
docker build -t $IMAGE . && docker push $IMAGE
gcloud run deploy transitpulse-api --project $PROJECT --region $REGION --image $IMAGE
curl -s "$(terraform -chdir=infra/terraform output -raw api_url)/healthz"     # {"ok":true}
```

Open the URL on a phone and a desktop. The map, KPI tiles, trends and forecast should load from BigQuery. The Ask card
says the analyst isn't connected, because the agent is off.

## 3. Switch on deploys from GitHub

In GitHub → Settings → Secrets and variables → Actions → **Variables** (not secrets; none of these is sensitive):

| Variable | Value |
|---|---|
| `GCP_PROJECT` | `transitpulse-511002` |
| `GCP_WIF_PROVIDER` | `terraform output -raw github_wif_provider` (`projects/<number>/locations/global/workloadIdentityPools/github/providers/transitpulse`) |
| `GCP_DEPLOY_SA` | `terraform output -raw github_deploy_service_account` |
| `DEPLOY_ENABLED` | `true` (last; this is the switch) |

Each push to `main` (or a manual *Run workflow*) then runs `deploy.yml`:
1. builds the image, tagged with the commit SHA
2. runs the container smoke tests on it (`uv run pytest -m docker tests/deploy`, `TP_TEST_IMAGE` = that image)
3. gets a token through WIF (no JSON key) and pushes the image
4. runs `gcloud run deploy --image` and curls `/healthz` and `/`

`deploy.yml` does **not** wait for `ci.yml`: both start on the same push, so a commit whose unit tests fail can
still deploy. Only the container smoke tests gate the push. Check the CI run before (or soon after) pushing to
`main`.

Artifact Registry's cleanup policy keeps the newest 3 images.

To pause deploys, set `DEPLOY_ENABLED` to anything else. The job is then skipped and nothing else changes.

If a deploy fails on a permission error for operations or the service, check with
`gcloud run services get-iam-policy transitpulse-api --region us-west1` that `sa-deploy` has `roles/run.developer`.
If the error is about acting as `sa-agent`, check
`gcloud iam service-accounts get-iam-policy sa-agent@transitpulse-511002.iam.gserviceaccount.com`.

## 4. Turning on Ask TransitPulse (the agent)

The agent costs money per question once it is public: BigQuery bytes and Gemini tokens. Do these steps in order.

1. **Set a BigQuery per-user daily quota first.** Console → IAM & Admin → Quotas → filter "BigQuery API" →
   **"Query usage per day per user"**. Set it to **20 GiB**.
   - It applies to every principal, including `sa-agent` and `sa-pipeline`. Before setting it, check the pipeline's
     peak day in BigQuery → Administration → Monitoring (or `INFORMATION_SCHEMA.JOBS_BY_USER`). If the pipeline
     needs more, raise the quota and keep it under the 1 TiB/month free tier ÷ 30 ≈ 33 GiB/day.
   - Why this matters: the agent's own guards are 1 GB per query (dry run first), 10 questions per IP per minute, and
     a 10 GB daily byte budget. That budget is **per process and in memory**, so it resets whenever an instance
     starts (scale to zero, a new revision, a second instance). The console quota is the only hard daily cap.
2. **Add the Gemini key as a secret version.** Use a key from Google AI Studio. Check the model name in
   `var.gemini_model` (default `gemini-2.5-flash`) against the current model list.
   ```sh
   printf '%s' "$GEMINI_KEY" | gcloud secrets versions add transitpulse-gemini-api-key --data-file=- --project transitpulse-511002
   ```
3. Set `agent_enabled = true` in `terraform.tfvars`, run `terraform plan`, and apply. Expect **1 to add** (the
   secret accessor for `sa-agent`) and **1 to change** (the service: `TP_AGENT_ENABLED=true`, `TP_AGENT_LLM=gemini`,
   `TP_GEMINI_MODEL`, `GOOGLE_API_KEY` from the secret). The running image is kept.
4. Ask a question on the site, then try an off-topic one to see the refusal.

To turn the agent off, set `agent_enabled = false` and apply. The site's Ask card then says the analyst isn't
connected. The secret version can stay; disabled or not, it costs nothing at this size.

## Rollback

```sh
gcloud run revisions list --service transitpulse-api --region us-west1
gcloud run services update-traffic transitpulse-api --region us-west1 --to-revisions <REVISION>=100
```

The next `deploy.yml` run sends traffic to the new revision again. To stop it from doing that, set `DEPLOY_ENABLED`
to `false` first. Settings managed by Terraform (env, scaling, service account) are rolled back by reverting the `.tf`
change and applying it.

## Costs (checked against the plan's limits)

Free-tier figures are Google's published monthly free usage. Re-check them on the pricing pages before you apply:
[Cloud Run](https://cloud.google.com/run/pricing), [Artifact Registry](https://cloud.google.com/artifact-registry/pricing),
[BigQuery](https://cloud.google.com/bigquery/pricing), [Secret Manager](https://cloud.google.com/secret-manager/pricing),
[free tier summary](https://cloud.google.com/free/docs/free-cloud-features), [Gemini API](https://ai.google.dev/pricing).

| Item | Free tier (per month) | This setup | Expected |
|---|---|---|---|
| **Cloud Run (request-based billing)** | 180,000 vCPU-s, 360,000 GiB-s, 2 M requests | Billed only while a request runs (`cpu_idle`). 1 vCPU, 0.5 GiB, so 1 busy second = 1 vCPU-s + 0.5 GiB-s. Max 2 instances. | Portfolio traffic (≈ 10k requests × ≤ 0.2 s) ≈ 2,000 vCPU-s: **$0**. The free vCPU-s cover ~50 hours of one instance busy non-stop. |
| Cloud Run worst case | — | 2 instances busy 24/7 ≈ 5.2 M vCPU-s | ≈ $120/month. This is what the **$1 and $5 budget alerts** are for; the $1 alert fires after about 11 busy hours beyond the free tier. |
| Outbound data | 1 GiB/month to North America | Page ≈ 0.4 MB uncompressed on the first visit. Fonts are cached a year, map data a day. | ~2,500 first visits/month free; beyond that cents per GB. |
| **Artifact Registry** | 0.5 GB storage | Image **≈ 119 MB compressed** (measured: `docker save \| gzip`, 119,177,467 bytes); 3 kept = ~357 MB. Unchanged layers (Python base, venv) are shared between versions, so it is usually less. | **$0** |
| **BigQuery** | 1 TiB queried, 10 GB stored | Site queries are capped at 100 MB each and cached for 1 h per instance. Agent: ≤ 1 GB per question + the per-user daily quota above. | **$0** with the agent off; bounded by the quota with it on |
| Secret Manager | 6 active versions, 10k accesses | 1 version, read when an instance starts | **$0** |
| WIF, IAM, budgets | free | — | $0 |
| Gemini API | AI Studio free tier (rate-limited) | only with `agent_enabled` | $0 on the free tier; paid if the key's project has billing (check the pricing page) |

The budgets stay at **$1 and $5** (`main.tf`, guarded by `tests/test_infra_cloudrun.py::test_budgets_unchanged_at_1_and_5`).

## Teardown

Remove the Cloud Run deployment and keep everything else:

```sh
# set DEPLOY_ENABLED=false in GitHub first
terraform destroy \
  -target=google_cloud_run_v2_service_iam_member.public_invoker \
  -target=google_cloud_run_v2_service_iam_member.deploy_developer \
  -target=google_cloud_run_v2_service.api \
  -target=google_service_account_iam_member.deploy_wif \
  -target=google_service_account_iam_member.deploy_acts_as_agent \
  -target=google_artifact_registry_repository_iam_member.deploy_writer \
  -target=google_iam_workload_identity_pool_provider.github \
  -target=google_iam_workload_identity_pool.github \
  -target=google_secret_manager_secret.gemini_api_key
```

Then delete the `.tf` files, or the next apply recreates them. A deleted workload identity pool stays soft-deleted
for 30 days and its ID can't be reused. To apply again within that window, run
`gcloud iam workload-identity-pools undelete github --location global` first. Images in Artifact Registry stay until
you delete them (`gcloud artifacts docker images delete`).

## Maintenance notes

- **The site's timetable is inside the image.** `web/data/schedule.json` ends on 2027-01-10. After a
  `tasks.py web-data` rebuild from a newer GTFS feed, commit it so that `deploy.yml` ships the new image. Until then,
  after Jan 10, 2027 the map says the timetable has ended.
- The Oracle VM keeps running the pipeline. Cloud Run only reads `marts` and `ml`. After New Year, restart the VM's
  Dagster units so the `years` partitions include the new year ([`ORACLE_VM.md`](ORACLE_VM.md)).
- After the first deploy, check in the Cloud Run request logs that the right-most `X-Forwarded-For` entry (the one
  read with `TP_TRUST_PROXY=true`) is the real client IP. If every request shows the same address (a Google
  front-end or load balancer IP), the per-IP rate limit becomes one global limit for all visitors.
- Local load-test numbers (`load/run_local.py`) are this PC's, not Cloud Run's. After the first deploy, measure the
  cold start: the time to the first `/healthz` after 15+ idle minutes.
