# NVD Personal Health Data Engineering, Analytics & AI Platform

Full-stack personal health medallion platform on Google Cloud Platform (`house-tully-310623`, multi-region `US` for GCS/BigQuery, `us-central1` for Cloud Run, Dataform, and Vertex AI).

## Architecture Overview

- **Storage (`gs://nvd-health-raw-data`)**: Raw Google Health Takeout `.zip` archives, unzipped folders (`Health Fitness Data_GoogleData/`, `Physical Activity_GoogleData/`, `Stress Score/`), ReactHealth CPAP PDFs, and future drops under `uploads/transcend_micro/` and `uploads/zenplanner/`.
- **Web & API (`nvd-health-web` on Cloud Run `--no-allow-unauthenticated`)**: Unified FastAPI backend + React/Vite/Tailwind SPA. Generates Direct-to-GCS Resumable V4 Signed URLs via IAM `signBlob` (bypassing Cloud Run's 32 MiB body limit), streams ETL/Dataform progress via SSE, serves Gold/Silver/Bronze analytics & ReportLab Sleep Doctor PDFs, and hosts the AI Health Analyst.
- **ETL Worker (`nvd-health-etl-job` on Cloud Run Jobs)**: Streams >400 MB Takeout `.zip` archives, parses 2,700+ strict RFC-4180 CSVs and multi-page ReactHealth PDFs, deduplicates via `bronze_ingestion_ledger`, executes batched BigQuery `MERGE` into `nvd_health_bronze`, auto-detects `cpap_start_date`, and triggers Dataform programmatically.
- **Dataform Medallion (`nvd_health_silver` & `nvd_health_gold`)**:
  - `nvd_health_silver.daily_health_summary` (`America/Los_Angeles` 1 row/day, wake-up alignment for sleep/CPAP, literal UTC date preservation for `00:00:00Z` daily files, Pacific shift for intraday streams, `-1` sentinel cleanup).
  - `nvd_health_gold.v_daily_health_performance`, `v_cpap_before_after_summary`, `v_sleep_doctor_weekly_summary` (with 7D, 30D, and sliding Best-30 compliance windows).
- **AI Health Analyst**: Google ADK + Vertex AI (`gemini-4-hydrogen`, configurable via `GEMINI_MODEL`) deployable to Vertex AI Agent Engine (`scripts/deploy_agent_engine.py`) with local ADK Runner fallback and read-only BigQuery SQL guardrails.

## Deployment (`house-tully-310623`)

1. Configure `infra/terraform/terraform.tfvars` from `infra/terraform/terraform.tfvars.example`:
   ```bash
   cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
   ```
2. Run the reproducible Cloud Build + GCS CORS + Terraform + Dataform workspace sync script:
   ```bash
   chmod +x scripts/deploy.sh
   ./scripts/deploy.sh
   ```
3. (Optional) Deploy the ADK agent to Vertex AI Agent Engine and bind `agent_engine_resource_name` in `terraform.tfvars`:
   ```bash
   PYTHONPATH=backend python3 scripts/deploy_agent_engine.py
   ```
4. Access the IAM-protected web application locally via Cloud Run proxy (no custom login screen):
   ```bash
   gcloud run services proxy nvd-health-web --region=us-central1 --project=house-tully-310623
   ```
5. Open `http://localhost:8080`, switch to **Data Engineering & Admin**, and click **Run ETL on Existing GCS Prefix** to run the initial historical load on `gs://nvd-health-raw-data/`.

## Local Development

```bash
# Backend + in-process ETL mode (requires ADC: gcloud auth application-default login)
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
PYTHONPATH=backend LOCAL_INPROCESS_ETL=true .venv/bin/uvicorn app.main:app --reload --port 8080 --app-dir backend

# Frontend dev server (proxies /api -> localhost:8080)
cd frontend && npm install && npm run dev
```

## Running Tests

```bash
PYTHONPATH=backend python3 -m unittest discover -s tests -v
```
