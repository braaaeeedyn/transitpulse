# M7: the API + static site on Cloud Run (docs/CLOUD_RUN.md). Scales to zero, at most 2 instances, runs as the
# read-only sa-agent. CI (.github/workflows/deploy.yml) deploys new images; Terraform owns everything else.

locals {
  api_service = "transitpulse-api"

  # Ask TransitPulse is off unless var.agent_enabled; only then is the Gemini key bound (the secret's *version* is
  # added by hand, so the key never appears in Terraform state).
  api_env = merge(
    {
      TP_WAREHOUSE     = "bigquery"
      TP_GCP_PROJECT   = var.project_id
      TP_TRUST_PROXY   = "true" # Cloud Run's front end appends the caller's IP to X-Forwarded-For
      TP_AGENT_ENABLED = tostring(var.agent_enabled)
    },
    var.agent_enabled ? { TP_AGENT_LLM = "gemini", TP_GEMINI_MODEL = var.gemini_model } : {},
  )
}

resource "google_secret_manager_secret" "gemini_api_key" {
  secret_id = "transitpulse-gemini-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_iam_member" "agent_gemini_key" {
  count     = var.agent_enabled ? 1 : 0
  secret_id = google_secret_manager_secret.gemini_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.sa["agent"].email}"
}

resource "google_cloud_run_v2_service" "api" {
  name                = local.api_service
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false # `terraform destroy` is the documented teardown

  template {
    service_account                  = google_service_account.sa["agent"].email
    max_instance_request_concurrency = 80
    timeout                          = "60s"

    scaling {
      min_instance_count = 0 # scale to zero: no idle cost
      max_instance_count = 2 # caps the bill and the agent's parallel BigQuery spend
    }

    containers {
      # Placeholder for the first apply only; deploy.yml replaces it (see lifecycle below).
      image = var.api_initial_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle          = true # CPU is billed only while a request is being served
        startup_cpu_boost = false
      }

      dynamic "env" {
        for_each = local.api_env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.agent_enabled ? [google_secret_manager_secret.gemini_api_key.secret_id] : []
        content {
          name = "GOOGLE_API_KEY"
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }

      startup_probe {
        http_get {
          path = "/healthz"
        }
        period_seconds    = 2
        failure_threshold = 15
      }
    }
  }

  lifecycle {
    # CI owns the running image (gcloud run deploy --image); Terraform must not roll it back.
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  depends_on = [
    google_project_service.enabled,
    google_secret_manager_secret_iam_member.agent_gemini_key,
  ]
}

# The site is public: anyone may invoke this one service. Nothing else in the project is granted to allUsers.
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  name     = google_cloud_run_v2_service.api.name
  location = google_cloud_run_v2_service.api.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}
