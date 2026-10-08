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

What this creates (M0): enabled APIs, $1 and $5 budget alerts, the raw GCS bucket, BigQuery datasets
`raw / staging / marts / ml / ci`, the Artifact Registry repo (keeps last 3 images), and three service accounts
(`sa-pipeline` read/write, `sa-agent` read-only on `marts`+`ml`, `sa-deploy`). Cloud Run and Workload Identity
Federation are added in M7.
