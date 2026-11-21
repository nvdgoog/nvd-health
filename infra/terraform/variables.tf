variable "project_id" {
  type        = string
  default     = "house-tully-310623"
  description = "GCP Project ID."
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "Co-located US region for Cloud Run, Dataform, Artifact Registry, and Vertex AI."
}

variable "bq_location" {
  type        = string
  default     = "US"
  description = "BigQuery multi-region location matching gs://nvd-health-raw-data."
}

variable "gcs_raw_bucket" {
  type        = string
  default     = "nvd-health-raw-data"
  description = "Globally unique multi-region US GCS bucket holding raw health exports."
}

variable "container_image" {
  type        = string
  default     = "us-central1-docker.pkg.dev/house-tully-310623/nvd-health/nvd-health-platform:latest"
  description = "Artifact Registry container image shared by Cloud Run service and Cloud Run Job."
}

variable "gemini_model" {
  type        = string
  default     = "gemini-4-hydrogen"
  description = "Gemini model ID used by the ADK / Vertex AI Agent Engine Health Analyst."
}

variable "agent_engine_resource_name" {
  type        = string
  default     = ""
  description = "Optional Vertex AI Agent Engine resource name (populated after deploy_agent_engine.py)."
}

variable "default_cpap_start_date" {
  type        = string
  default     = "2026-10-13"
  description = "Default CPAP intervention date prior to auto-detection."
}

variable "authorized_invokers" {
  type        = list(string)
  default     = []
  description = "IAM members granted roles/run.invoker for --no-allow-unauthenticated Cloud Run proxy access (e.g. ['user:you@example.com'])."
}

variable "enable_iap_lb" {
  type        = bool
  default     = false
  description = "Optional toggle to provision an External HTTPS Load Balancer + Serverless NEG + IAP."
}

variable "iap_domain" {
  type        = string
  default     = ""
  description = "Domain name for Google-managed SSL cert when enable_iap_lb=true."
}
