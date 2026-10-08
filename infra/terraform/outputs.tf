output "raw_bucket" {
  value = google_storage_bucket.raw.url
}

output "service_accounts" {
  value = { for k, sa in google_service_account.sa : k => sa.email }
}

output "artifact_registry" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.repository_id}"
}
