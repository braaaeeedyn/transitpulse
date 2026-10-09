variable "project_id" {
  description = "GCP project id."
  type        = string
}

variable "region" {
  description = "Region for every resource. us-west1 is inside the GCS/BigQuery free tier."
  type        = string
  default     = "us-west1"
}

variable "billing_account_id" {
  description = "Billing account id (XXXXXX-XXXXXX-XXXXXX), used for the budget alerts."
  type        = string
}

variable "budget_alert_email" {
  description = "Email that receives budget alerts."
  type        = string
}

variable "raw_bucket_name" {
  description = "GCS bucket for raw downloads and Parquet."
  type        = string
}

variable "agent_enabled" {
  description = "Turn on Ask TransitPulse (POST /api/ask) on Cloud Run. Add the Gemini key's secret version first (docs/CLOUD_RUN.md)."
  type        = bool
  default     = false
}

variable "gemini_model" {
  description = "Gemini model the agent uses when agent_enabled (check the current model name before enabling)."
  type        = string
  default     = "gemini-2.5-flash"
}

variable "api_initial_image" {
  description = "Image for the service's first revision only; deploy.yml deploys the real image afterwards."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "github_repository" {
  description = "owner/name of the only GitHub repository allowed to deploy (Workload Identity Federation)."
  type        = string
  default     = "braaaeeedyn/transitpulse"
}
