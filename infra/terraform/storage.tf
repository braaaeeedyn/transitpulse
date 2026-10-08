resource "google_storage_bucket" "raw" {
  name                        = var.raw_bucket_name
  location                    = upper(var.region)
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  # Raw downloads are re-fetchable; drop non-current versions quickly to stay inside 5 GB-month.
  versioning {
    enabled = false
  }

  lifecycle_rule {
    condition {
      age            = 7
      matches_prefix = ["tmp/"]
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.enabled]
}
