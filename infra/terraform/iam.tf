locals {
  service_accounts = {
    pipeline = "Dagster/Spark/dbt: writes raw, staging, marts, ml."
    agent    = "API + agent: read-only on marts and ml."
    deploy   = "GitHub Actions deploys (used via Workload Identity Federation in M7)."
  }
}

resource "google_service_account" "sa" {
  for_each     = local.service_accounts
  account_id   = "sa-${each.key}"
  display_name = "TransitPulse ${each.key}"
  description  = each.value
}

# --- pipeline: write everything except ci, run jobs, read/write the raw bucket -----------------------
resource "google_bigquery_dataset_iam_member" "pipeline_editor" {
  for_each   = toset(["raw", "staging", "marts", "ml"])
  dataset_id = google_bigquery_dataset.ds[each.key].dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.sa["pipeline"].email}"
}

resource "google_project_iam_member" "pipeline_jobs" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.sa["pipeline"].email}"
}

resource "google_storage_bucket_iam_member" "pipeline_raw" {
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.sa["pipeline"].email}"
}

# --- agent: read-only on marts + ml, can run (dry-run) queries; nothing else ----------------------
resource "google_bigquery_dataset_iam_member" "agent_viewer" {
  for_each   = toset(["marts", "ml"])
  dataset_id = google_bigquery_dataset.ds[each.key].dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.sa["agent"].email}"
}

resource "google_project_iam_member" "agent_jobs" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.sa["agent"].email}"
}
