locals {
  services = [
    "bigquery.googleapis.com",
    "storage.googleapis.com",
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "billingbudgets.googleapis.com",
  ]
}

resource "google_project_service" "enabled" {
  for_each           = toset(local.services)
  service            = each.value
  disable_on_destroy = false
}

# --- Cost guardrails: alerts at $1 and $5 (TRANSITPULSE_PLAN.md §8) ---------------------------------
resource "google_monitoring_notification_channel" "budget_email" {
  display_name = "TransitPulse budget alerts"
  type         = "email"
  labels       = { email_address = var.budget_alert_email }
}

resource "google_billing_budget" "guardrail" {
  for_each        = { one = 1, five = 5 }
  billing_account = var.billing_account_id
  display_name    = "transitpulse-${each.key}-usd"

  budget_filter {
    projects = ["projects/${var.project_id}"]
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
