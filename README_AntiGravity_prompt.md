# Antigravity Fresh Deployment Prompt

Copy and paste the prompt below into Antigravity (replacing `<YOUR_NEW_PROJECT_ID>` or leaving it out so Antigravity asks you for the target GCP Project ID) to deploy the **NVD Health Platform** from `https://github.com/nvdgoog/nvd-health.git` into a new GCP project:

---

```text
Clone or update the repository https://github.com/nvdgoog/nvd-health.git (main branch) and deploy a fresh instance of the NVD Health Platform to my target GCP project <YOUR_NEW_PROJECT_ID> (if <YOUR_NEW_PROJECT_ID> is not yet provided, ask me for the target GCP Project ID before running deployment commands).

Please follow these steps:
1. Verify gcloud authentication (gcloud auth list and gcloud auth application-default print-access-token), that project <YOUR_NEW_PROJECT_ID> exists with billing enabled, and check that terraform, python3, and a Python virtualenv with backend/requirements.txt are available.
2. Confirm the bucket <YOUR_NEW_PROJECT_ID>-health-raw-data is globally available (or accept an override via GCS_RAW_BUCKET). Do not enable Dataplex or Colab Enterprise.
3. Run ./scripts/deploy.sh <YOUR_NEW_PROJECT_ID> to enable the required APIs, create the GCS bucket with CORS and lifecycle rules, build/push the container image via Cloud Build, provision BigQuery/Cloud Run/Dataform/IAM via Terraform, and verify Dataform compilation.
4. Confirm the Cloud Run web service nvd-health-web (us-central1) and /api/health are healthy, then give me the exact gcloud run services proxy nvd-health-web --region=us-central1 --project=<YOUR_NEW_PROJECT_ID> command so I can open the UI, upload my Google Takeout & ReactHealth CPAP PDFs in Data Engineering & Admin, and run Sync New Reports from Drive (Transcend Micro) and Sync Sheet & Rebuild Silver/Gold.
```
