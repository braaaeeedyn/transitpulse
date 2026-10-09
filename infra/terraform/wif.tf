# M7: GitHub Actions authenticates as sa-deploy through Workload Identity Federation (no JSON key anywhere).
# Only pushes to main of this one repository can get a token; sa-deploy can push images and deploy this service,
# nothing more (no owner/editor, no Terraform).

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
  description               = "OIDC tokens from GitHub Actions (deploy.yml)."

  depends_on = [google_project_service.enabled]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "transitpulse"
  display_name                       = "GitHub transitpulse"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # Tokens from any other repository or branch (forks, pull requests, feature branches) are rejected outright.
  attribute_condition = "assertion.repository == \"${var.github_repository}\" && assertion.ref == \"refs/heads/main\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "deploy_wif" {
  service_account_id = google_service_account.sa["deploy"].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

# push images to the one Artifact Registry repo
resource "google_artifact_registry_repository_iam_member" "deploy_writer" {
  location   = google_artifact_registry_repository.app.location
  repository = google_artifact_registry_repository.app.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.sa["deploy"].email}"
}

# deploy new revisions of this one service
resource "google_cloud_run_v2_service_iam_member" "deploy_developer" {
  name     = google_cloud_run_v2_service.api.name
  location = google_cloud_run_v2_service.api.location
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.sa["deploy"].email}"
}

# a revision runs as sa-agent, so the deployer must be allowed to act as sa-agent (and only sa-agent)
resource "google_service_account_iam_member" "deploy_acts_as_agent" {
  service_account_id = google_service_account.sa["agent"].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.sa["deploy"].email}"
}
