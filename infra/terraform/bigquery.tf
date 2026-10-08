locals {
  datasets = {
    raw     = "Loaded as-is from Parquet. Never edited by hand."
    staging = "dbt staging + intermediate models."
    marts   = "dbt marts: the only dataset the agent and dashboards read."
    ml      = "Forecast run logs and model outputs."
    ci      = "Throwaway dataset for dbt builds in CI on a small sample."
  }
}

resource "google_bigquery_dataset" "ds" {
  for_each      = local.datasets
  dataset_id    = each.key
  description   = each.value
  location      = var.region
  friendly_name = "transitpulse ${each.key}"

  # CI tables expire on their own so they never accumulate storage.
  default_table_expiration_ms = each.key == "ci" ? 3 * 24 * 60 * 60 * 1000 : null

  depends_on = [google_project_service.enabled]
}
