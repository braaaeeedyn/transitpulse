output "raw_bucket" {
  value = google_storage_bucket.raw.url
}

output "service_accounts" {
  value = { for k, sa in google_service_account.sa : k => sa.email }
}

output "artifact_registry" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.repository_id}"
}

output "api_url" {
  value = google_cloud_run_v2_service.api.uri
}

# the two repository variables deploy.yml reads (docs/CLOUD_RUN.md)
output "github_wif_provider" {
  value = google_iam_workload_identity_pool_provider.github.name
}

output "github_deploy_service_account" {
  value = google_service_account.sa["deploy"].email
}
