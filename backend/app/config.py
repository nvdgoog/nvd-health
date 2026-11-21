from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
from typing import Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application and ETL worker configuration sourced from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # GCP Project & Regions
    gcp_project_id: str = Field(default="")
    gcp_region: str = Field(default="us-central1")
    bq_location: str = Field(default="US")
    gcs_raw_bucket: str = Field(default="")

    # BigQuery Medallion Datasets
    bq_dataset_bronze: str = Field(default="nvd_health_bronze")
    bq_dataset_silver: str = Field(default="nvd_health_silver")
    bq_dataset_gold: str = Field(default="nvd_health_gold")

    # Cloud Run & Job Execution
    cloud_run_job_name: str = Field(default="nvd-health-etl-job")
    web_service_account_email: Optional[str] = Field(default=None)

    # Dataform Orchestration
    dataform_repository_id: str = Field(default="nvd-health-dataform")
    dataform_workspace_id: str = Field(default="main-workspace")
    dataform_service_account: Optional[str] = Field(default=None)
    dataform_dir: str = Field(
        default=str(Path(__file__).resolve().parents[2] / "dataform")
    )

    # Vertex AI / ADK Agent Engine
    gemini_model: str = Field(default="gemini-4-hydrogen")
    vertex_genai_location: str = Field(default="global")
    agent_engine_resource_name: Optional[str] = Field(default=None)

    # Health Domain Defaults
    local_timezone: str = Field(default="America/Los_Angeles")
    default_cpap_start_date: str = Field(default="2026-10-13")
    google_sheet_id: str = Field(
        default="17SgQVoT53xm5299WKZHsIW5PgLInuszCSfeLu50Zsvc"
    )

    # Frontend Static Bundle Path
    frontend_dist_dir: str = Field(
        default=str(Path(__file__).resolve().parents[2] / "frontend" / "dist")
    )

    @model_validator(mode="after")
    def _derive_project_defaults(self) -> "Settings":
        if not self.gcp_project_id:
            self.gcp_project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
        if not self.gcs_raw_bucket and self.gcp_project_id:
            self.gcs_raw_bucket = f"{self.gcp_project_id}-health-raw-data"
        if not self.dataform_service_account and self.gcp_project_id:
            self.dataform_service_account = (
                f"nvd-health-etl-sa@{self.gcp_project_id}.iam.gserviceaccount.com"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
