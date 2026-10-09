# Bootstrap: cloudresourcemanager + serviceusage must already be on before Terraform can manage any other API
# (enabled once by hand, see infra/README.md). Listed here too so Terraform keeps them on.
locals {
  services = [
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
    "bigquery.googleapis.com",
    "storage.googleapis.com",
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "billingbudgets.googleapis.com",
    "monitoring.googleapis.com",    # the budget alerts' email channel
    "secretmanager.googleapis.com", # the agent's Gemini key on Cloud Run (M7)
  ]
}

resource "google_project_service" "enabled" {
  for_each           = toset(local.services)
  service            = each.value
  disable_on_destroy = false
}

data "google_project" "this" {
  project_id = var.project_id
}

# --- Cost guardrails: alerts at $1 and $5 (TRANSITPULSE_PLAN.md §8) ---------------------------------
resource "google_monitoring_notification_channel" "budget_email" {
  display_name = "TransitPulse budget alerts"
  type         = "email"
  labels       = { email_address = var.budget_alert_email }

  depends_on = [google_project_service.enabled]
}

resource "google_billing_budget" "guardrail" {
  for_each        = { one = 1, five = 5 }
  billing_account = var.billing_account_id
  display_name    = "transitpulse-${each.key}-usd"

  budget_filter {
    # the Budgets API stores the project *number*; using the ID here causes a permanent diff
    projects = ["projects/${data.google_project.this.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(each.value)
    }
  }

  threshold_rules {
    threshold_percent = 1.0
  }

  all_updates_rule {
    monitoring_notification_channels = [google_monitoring_notification_channel.budget_email.id]
    disable_default_iam_recipients   = false
  }

  depends_on = [google_project_service.enabled]
}
