from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agent.health_agent import build_adk_agent
from app.config import get_settings


def main() -> int:
    settings = get_settings()
    import vertexai
    from vertexai import agent_engines
    from vertexai.preview.reasoning_engines import AdkApp

    staging_bucket = f"gs://{settings.gcs_raw_bucket}/agent_engine_staging"
    vertexai.init(
        project=settings.gcp_project_id,
        location=settings.gcp_region,
        staging_bucket=staging_bucket,
    )

    adk_agent = build_adk_agent(settings)
    app = AdkApp(agent=adk_agent, enable_tracing=True)

    remote_agent = agent_engines.create(
        agent_engine=app,
        display_name="nvd-health-analyst",
        description="Personal Health Data Analyst (ADK + Gemini + Read-Only BigQuery Gold/Silver/Bronze)",
        requirements=[
            "google-cloud-aiplatform[agent_engines,adk]>=1.74.0",
            "google-adk>=0.3.0",
            "google-cloud-bigquery>=3.27.0",
            "pydantic-settings>=2.6.0",
        ],
        extra_packages=[str(Path(__file__).resolve().parents[1] / "backend" / "app")],
        env_vars={
            "GCP_PROJECT_ID": settings.gcp_project_id,
            "GCP_REGION": settings.gcp_region,
            "BQ_LOCATION": settings.bq_location,
            "BQ_DATASET_BRONZE": settings.bq_dataset_bronze,
            "BQ_DATASET_SILVER": settings.bq_dataset_silver,
            "BQ_DATASET_GOLD": settings.bq_dataset_gold,
            "GEMINI_MODEL": settings.gemini_model,
            "GOOGLE_GENAI_USE_VERTEXAI": "TRUE",
            "GOOGLE_CLOUD_PROJECT": settings.gcp_project_id,
            "GOOGLE_CLOUD_LOCATION": settings.gcp_region,
            "DEFAULT_CPAP_START_DATE": settings.default_cpap_start_date,
        },
    )
    print(f"Deployed Vertex AI Agent Engine resource:\n  {remote_agent.resource_name}")
    print(
        "Set AGENT_ENGINE_RESOURCE_NAME in Cloud Run / terraform.tfvars to enable remote Agent Engine mode."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
