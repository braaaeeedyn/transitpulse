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
