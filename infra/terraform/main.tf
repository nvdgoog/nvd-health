data "google_project" "current" {
  project_id = var.project_id
}

# GCS Bucket for raw exports with CORS + cost-optimizing lifecycle rules
resource "google_storage_bucket" "raw_data" {
  name                        = local.effective_raw_bucket
  location                    = var.bq_location
  uniform_bucket_level_access = true
  force_destroy               = false

  cors {
    origin          = ["*"]
    method          = ["GET", "HEAD", "PUT", "POST", "OPTIONS"]
    response_header = ["Content-Type", "Content-Length", "Content-Range", "Location", "x-goog-resumable", "ETag"]
    max_age_seconds = 3600
  }

  # Delete temporary unzipped CSV scratch copies 14 days after upload (SHA-256 ledger tracks Bronze state)
  lifecycle_rule {
    condition {
      age            = 14
      matches_prefix = ["uploads/google_takeout/unzipped/"]
    }
    action {
      type = "Delete"
    }
  }

  # Transition archived raw exports to Coldline after 30 days to minimize storage cost
  lifecycle_rule {
    condition {
      age = 30
      matches_prefix = [
        "uploads/google_takeout/zips/",
        "uploads/google_takeout/folders/",
        "uploads/reacthealth_pdf/",
        "uploads/transcend_micro/",
        "uploads/zenplanner/",
      ]
    }
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
  }

  depends_on = [google_project_service.enabled]
}

locals {
  effective_raw_bucket = var.gcs_raw_bucket != "" ? var.gcs_raw_bucket : "${var.project_id}-health-raw-data"
  effective_container_image = var.container_image != "" ? var.container_image : "${var.region}-docker.pkg.dev/${var.project_id}/nvd-health/nvd-health-platform:latest"
  apis = [
    "run.googleapis.com",
    "bigquery.googleapis.com",
    "storage.googleapis.com",
    "dataform.googleapis.com",
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "iam.googleapis.com",
    "sheets.googleapis.com",
    "drive.googleapis.com",
  ]
  medallion_datasets = {
    bronze = "nvd_health_bronze"
    silver = "nvd_health_silver"
    gold   = "nvd_health_gold"
  }
}

resource "google_project_service" "enabled" {
  for_each           = toset(local.apis)
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# Artifact Registry with automated image retention cleanup
resource "google_artifact_registry_repository" "repo" {
  location               = var.region
  repository_id          = "nvd-health"
  description            = "Container images for NVD Personal Health Platform"
  format                 = "DOCKER"
  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "delete-stale-images"
    action = "DELETE"
    condition {
      tag_state  = "ANY"
      older_than = "604800s" # 7 days
    }
  }

  cleanup_policies {
    id     = "keep-recent-versions"
    action = "KEEP"
    most_recent_versions {
      keep_count = 3
    }
  }

  depends_on = [google_project_service.enabled]
}

# BigQuery Medallion Datasets (multi-region US)
resource "google_bigquery_dataset" "medallion" {
  for_each      = local.medallion_datasets
  dataset_id    = each.value
  friendly_name = "NVD Health ${title(each.key)} Layer"
  location      = var.bq_location
  depends_on    = [google_project_service.enabled]
}

# Least-Privilege Service Accounts
resource "google_service_account" "web_sa" {
  account_id   = "nvd-health-web-sa"
  display_name = "NVD Health Web & API Cloud Run SA"
}

resource "google_service_account" "etl_sa" {
  account_id   = "nvd-health-etl-sa"
  display_name = "NVD Health ETL Cloud Run Job SA"
}

resource "google_service_account" "agent_sa" {
  account_id   = "nvd-health-agent-sa"
  display_name = "NVD Health Vertex AI Agent Engine Read-Only SA"
}

# Storage IAM scoped to gs://${var.gcs_raw_bucket}
resource "google_storage_bucket_iam_member" "web_storage_admin" {
  bucket = google_storage_bucket.raw_data.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.web_sa.email}"
}

resource "google_storage_bucket_iam_member" "etl_storage_admin" {
  bucket = google_storage_bucket.raw_data.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.etl_sa.email}"
}

# Allow web_sa to sign V4 GCS URLs via IAM signBlob without static JSON keys
resource "google_service_account_iam_member" "web_sa_self_token_creator" {
  service_account_id = google_service_account.web_sa.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.web_sa.email}"
}

# BigQuery IAM (dataset-scoped dataEditor + project jobUser)
resource "google_bigquery_dataset_iam_member" "web_bq_editor" {
  for_each   = google_bigquery_dataset.medallion
  dataset_id = each.value.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.web_sa.email}"
}

resource "google_bigquery_dataset_iam_member" "etl_bq_editor" {
  for_each   = google_bigquery_dataset.medallion
  dataset_id = each.value.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.etl_sa.email}"
}

resource "google_bigquery_dataset_iam_member" "agent_bq_viewer" {
  for_each   = google_bigquery_dataset.medallion
  dataset_id = each.value.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.agent_sa.email}"
}

resource "google_project_iam_member" "bq_job_user" {
  for_each = {
    web   = google_service_account.web_sa.email
    etl   = google_service_account.etl_sa.email
    agent = google_service_account.agent_sa.email
  }
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${each.value}"
}

# Dataform IAM
resource "google_project_iam_member" "dataform_editor" {
  for_each = {
    web = google_service_account.web_sa.email
    etl = google_service_account.etl_sa.email
  }
  project = var.project_id
  role    = "roles/dataform.editor"
  member  = "serviceAccount:${each.value}"
}

# Grant GCP Dataform service agent BigQuery permissions to execute Silver/Gold builds
resource "google_project_service_identity" "dataform_agent" {
  provider   = google-beta
  project    = var.project_id
  service    = "dataform.googleapis.com"
  depends_on = [google_project_service.enabled]
}

resource "google_project_iam_member" "dataform_agent_bq_jobuser" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_project_service_identity.dataform_agent.email}"
}

resource "google_bigquery_dataset_iam_member" "dataform_agent_bq_editor" {
  for_each   = google_bigquery_dataset.medallion
  dataset_id = each.value.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_project_service_identity.dataform_agent.email}"
}

# Strict act-as IAM bindings allowing Dataform to execute WorkflowInvocations as nvd-health-etl-sa
resource "google_service_account_iam_member" "dataform_agent_token_creator_etl" {
  service_account_id = google_service_account.etl_sa.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_project_service_identity.dataform_agent.email}"
}

resource "google_service_account_iam_member" "dataform_act_as_etl" {
  for_each = toset(concat([
    "serviceAccount:${google_project_service_identity.dataform_agent.email}",
    "serviceAccount:${google_service_account.etl_sa.email}",
    "serviceAccount:${google_service_account.web_sa.email}",
  ], var.authorized_invokers))
  service_account_id = google_service_account.etl_sa.name
  role               = "roles/iam.serviceAccountUser"
  member             = each.value
}

# Vertex AI IAM
resource "google_project_iam_member" "aiplatform_user" {
  for_each = {
    web   = google_service_account.web_sa.email
    agent = google_service_account.agent_sa.email
  }
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${each.value}"
}

# Dataform Repository
resource "google_dataform_repository" "health_repo" {
  provider   = google-beta
  project    = var.project_id
  region     = var.region
  name       = "nvd-health-dataform"
  depends_on = [google_project_service.enabled]
}

# Cloud Run Job (Long-running ETL Worker for >400 MB Takeout Zips & 2700+ CSVs)
resource "google_cloud_run_v2_job" "etl_job" {
  name                = "nvd-health-etl-job"
  location            = var.region
  deletion_protection = false

  template {
    task_count = 1
    template {
      service_account = google_service_account.etl_sa.email
      max_retries     = 0
      timeout         = "14400s"

      containers {
        image   = local.effective_container_image
        command = ["python", "-m", "app.etl.cli"]

        resources {
          limits = {
            cpu    = "4"
            memory = "8Gi"
          }
        }

        env {
          name  = "GCP_PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "GCP_REGION"
          value = var.region
        }
        env {
          name  = "BQ_LOCATION"
          value = var.bq_location
        }
        env {
          name  = "GCS_RAW_BUCKET"
          value = local.effective_raw_bucket
        }
        env {
          name  = "DATAFORM_REPOSITORY_ID"
          value = google_dataform_repository.health_repo.name
        }
        env {
          name  = "DATAFORM_SERVICE_ACCOUNT"
          value = google_service_account.etl_sa.email
        }
        env {
          name  = "DEFAULT_CPAP_START_DATE"
          value = var.default_cpap_start_date
        }
        env {
          name  = "GOOGLE_SHEET_ID"
          value = var.google_sheet_id
        }
        env {
          name  = "TRANSCEND_DRIVE_FOLDER_ID"
          value = var.transcend_drive_folder_id
        }
      }
    }
  }

  depends_on = [google_project_service.enabled]
}

# Allow Web SA to trigger Cloud Run Job executions with container env overrides
resource "google_cloud_run_v2_job_iam_member" "web_trigger_etl" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.etl_job.name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.web_sa.email}"
}

# Cloud Run Web Service (--no-allow-unauthenticated / IAM-protected)
resource "google_cloud_run_v2_service" "web" {
  name                = "nvd-health-web"
  location            = var.region
  deletion_protection = false
  ingress             = var.enable_iap_lb ? "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER" : "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.web_sa.email
    timeout         = "600s"

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      image = local.effective_container_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCP_REGION"
        value = var.region
      }
      env {
        name  = "BQ_LOCATION"
        value = var.bq_location
      }
      env {
        name  = "GCS_RAW_BUCKET"
        value = local.effective_raw_bucket
      }
      env {
        name  = "CLOUD_RUN_JOB_NAME"
        value = google_cloud_run_v2_job.etl_job.name
      }
      env {
        name  = "WEB_SERVICE_ACCOUNT_EMAIL"
        value = google_service_account.web_sa.email
      }
      env {
        name  = "DATAFORM_REPOSITORY_ID"
        value = google_dataform_repository.health_repo.name
      }
      env {
        name  = "DATAFORM_SERVICE_ACCOUNT"
        value = google_service_account.etl_sa.email
      }
      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
      }
      env {
        name  = "VERTEX_GENAI_LOCATION"
        value = "global"
      }
      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "TRUE"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = "global"
      }
      env {
        name  = "AGENT_ENGINE_RESOURCE_NAME"
        value = var.agent_engine_resource_name
      }
      env {
        name  = "DEFAULT_CPAP_START_DATE"
        value = var.default_cpap_start_date
      }
      env {
        name  = "GOOGLE_SHEET_ID"
        value = var.google_sheet_id
      }
      env {
        name  = "TRANSCEND_DRIVE_FOLDER_ID"
        value = var.transcend_drive_folder_id
      }
    }
  }

  depends_on = [google_project_service.enabled]
}

# IAM Invokers for gcloud run services proxy (--no-allow-unauthenticated)
resource "google_cloud_run_v2_service_iam_member" "authorized_invokers" {
  for_each = toset(var.authorized_invokers)
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.web.name
  role     = "roles/run.invoker"
  member   = each.value
}

# Optional External HTTPS Load Balancer + Serverless NEG (enable_iap_lb = true)
resource "google_compute_global_address" "lb_ip" {
  count = var.enable_iap_lb ? 1 : 0
  name  = "nvd-health-lb-ip"
}

resource "google_compute_region_network_endpoint_group" "serverless_neg" {
  count                 = var.enable_iap_lb ? 1 : 0
  name                  = "nvd-health-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  cloud_run {
    service = google_cloud_run_v2_service.web.name
  }
}

resource "google_compute_backend_service" "web_backend" {
  count       = var.enable_iap_lb ? 1 : 0
  name        = "nvd-health-backend"
  protocol    = "HTTP"
  timeout_sec = 600
  backend {
    group = google_compute_region_network_endpoint_group.serverless_neg[0].id
  }
}

resource "google_compute_url_map" "web_url_map" {
  count           = var.enable_iap_lb ? 1 : 0
  name            = "nvd-health-url-map"
  default_service = google_compute_backend_service.web_backend[0].id
}

resource "google_compute_managed_ssl_certificate" "web_cert" {
  count = var.enable_iap_lb && var.iap_domain != "" ? 1 : 0
  name  = "nvd-health-cert"
  managed {
    domains = [var.iap_domain]
  }
}

resource "google_compute_target_https_proxy" "web_https_proxy" {
  count            = var.enable_iap_lb && var.iap_domain != "" ? 1 : 0
  name             = "nvd-health-https-proxy"
  url_map          = google_compute_url_map.web_url_map[0].id
  ssl_certificates = [google_compute_managed_ssl_certificate.web_cert[0].id]
}

resource "google_compute_global_forwarding_rule" "web_https_rule" {
  count      = var.enable_iap_lb && var.iap_domain != "" ? 1 : 0
  name       = "nvd-health-https-rule"
  target     = google_compute_target_https_proxy.web_https_proxy[0].id
  port_range = "443"
  ip_address = google_compute_global_address.lb_ip[0].address
}
