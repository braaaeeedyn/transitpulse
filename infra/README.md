# Infrastructure (Terraform, GCP)

One-time manual steps, in order:

1. Create a GCP project and attach a billing account.
2. `gcloud auth application-default login`
3. Create the state bucket (Terraform can't create its own backend). Bucket names are global, so include your project ID, and set the same name in `versions.tf`:
   ```sh
   gcloud storage buckets create gs://YOUR_PROJECT_ID-tfstate --location=us-west1 --uniform-bucket-level-access
   gcloud storage buckets update gs://YOUR_PROJECT_ID-tfstate --versioning
   ```
4. Turn on the two APIs Terraform itself needs before it can manage the rest (a new project has them off):
   ```sh
   gcloud services enable cloudresourcemanager.googleapis.com serviceusage.googleapis.com iam.googleapis.com
   ```
   then wait about a minute for it to take effect.
5. `cp terraform.tfvars.example terraform.tfvars` and fill it in.
6. ```sh
   cd infra/terraform
   terraform init
   terraform plan
   terraform apply
   ```

What this creates:

| File | Resources | State |
|---|---|---|
| `main.tf`, `bigquery.tf`, `storage.tf`, `registry.tf`, `iam.tf` (M0) | enabled APIs, $1 and $5 budget alerts, the raw GCS bucket, BigQuery datasets `raw / staging / marts / ml / ci`, the Artifact Registry repo (keeps the last 3 images), three service accounts (`sa-pipeline` read/write, `sa-agent` read-only on `marts`+`ml`, `sa-deploy`) | applied |
| `cloudrun.tf` (M7) | Cloud Run service `transitpulse-api` (0–2 instances, 512 MiB, runs as `sa-agent`, agent off), public `run.invoker` on that service only, the Gemini key secret (no version) | **code only, not applied** |
| `wif.tf` (M7) | Workload Identity Federation for GitHub Actions (pinned to `braaaeeedyn/transitpulse` on `main`), `sa-deploy`'s three narrow roles | **code only, not applied** |

The M7 files add 10 resources and change none. Applying them, switching on `deploy.yml` and enabling the agent are
covered in [`docs/CLOUD_RUN.md`](../docs/CLOUD_RUN.md). Optional variables (`agent_enabled`, `gemini_model`,
`github_repository`, `api_initial_image`) have safe defaults; see `variables.tf`.

Checks that never touch the backend: `terraform fmt -check`, `terraform validate` (CI runs `init -backend=false`
first), and `uv run pytest tests/test_infra_cloudrun.py` (scaling, IAM, WIF condition, budgets, deploy workflow).
