resource "google_artifact_registry_repository" "app" {
  repository_id = "transitpulse"
  location      = var.region
  format        = "DOCKER"
  description   = "TransitPulse API + web images."

  # Free tier is 0.5 GB: keep only the 3 most recent images.
  cleanup_policy_dry_run = false
  cleanup_policies {
    id     = "keep-last-3"
    action = "KEEP"
    most_recent_versions {
      keep_count = 3
    }
  }
  cleanup_policies {
    id     = "delete-rest"
    action = "DELETE"
    condition {
      tag_state = "ANY" # every image not kept by keep-last-3 (the API drops `older_than = "0s"`, causing a diff)
    }
  }

  depends_on = [google_project_service.enabled]
}
