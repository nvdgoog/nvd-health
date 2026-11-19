output "web_service_url" {
  value = google_cloud_run_v2_service.web.uri
}

output "etl_job_name" {
  value = google_cloud_run_v2_job.etl_job.name
}

output "dataform_repository" {
  value = google_dataform_repository.health_repo.id
}

output "web_service_account" {
  value = google_service_account.web_sa.email
}

output "etl_service_account" {
  value = google_service_account.etl_sa.email
}

output "agent_service_account" {
  value = google_service_account.agent_sa.email
}

output "proxy_command" {
  value = "gcloud run services proxy ${google_cloud_run_v2_service.web.name} --region=${var.region} --project=${var.project_id}"
}
