#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${GCP_PROJECT_ID:-}}"
if [ -z "${PROJECT_ID}" ]; then
  echo "Usage: $0 <GCP_PROJECT_ID> [GCS_RAW_BUCKET]"
  echo "   or: GCP_PROJECT_ID=<your-project-id> $0"
  exit 1
fi

REGION="${GCP_REGION:-us-central1}"
BQ_LOCATION="${BQ_LOCATION:-US}"
BUCKET="${2:-${GCS_RAW_BUCKET:-${PROJECT_ID}-health-raw-data}}"
GOOGLE_SHEET_ID="${GOOGLE_SHEET_ID:-17SgQVoT53xm5299WKZHsIW5PgLInuszCSfeLu50Zsvc}"
TRANSCEND_DRIVE_FOLDER_ID="${TRANSCEND_DRIVE_FOLDER_ID:-1dVV82yiTNJs1nQmUNRZpxMunWBiwWRMs}"
CPAP_START_DATE="${DEFAULT_CPAP_START_DATE:-2026-10-13}"
IMAGE_TAG="${IMAGE_TAG:-$(date -u +%Y%m%d-%H%M%S)}"
IMAGE="${CONTAINER_IMAGE:-${REGION}-docker.pkg.dev/${PROJECT_ID}/nvd-health/nvd-health-platform:${IMAGE_TAG}}"

if [ -n "${AUTHORIZED_INVOKERS:-}" ]; then
  INVOKERS_TF_VAL=$(python3 -c 'import json, os; items=[x.strip() for x in os.environ["AUTHORIZED_INVOKERS"].split(",") if x.strip()]; items=[x if ":" in x else f"user:{x}" for x in items]; print(json.dumps(items))')
else
  ACTIVE_ACCOUNT="$(gcloud config get-value account 2>/dev/null || true)"
  if [ -n "${ACTIVE_ACCOUNT}" ] && [ "${ACTIVE_ACCOUNT}" != "(unset)" ]; then
    INVOKERS_TF_VAL="[\"user:${ACTIVE_ACCOUNT}\"]"
  else
    INVOKERS_TF_VAL="[]"
  fi
fi

echo "==> Target project: ${PROJECT_ID} | Region: ${REGION} | Bucket: gs://${BUCKET}"

echo "==> 1. Enabling baseline APIs & Artifact Registry (if first deploy)"
gcloud services enable \
  run.googleapis.com \
  bigquery.googleapis.com \
  storage.googleapis.com \
  dataform.googleapis.com \
  aiplatform.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com \
  sheets.googleapis.com \
  drive.googleapis.com \
  --project="${PROJECT_ID}"

if ! gcloud artifacts repositories describe nvd-health --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud artifacts repositories create nvd-health \
    --repository-format=docker \
    --location="${REGION}" \
    --project="${PROJECT_ID}"
fi

echo "==> 2. Building & pushing unified container image via Cloud Build: ${IMAGE}"
gcloud builds submit \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --tag="${IMAGE}" \
  .

echo "==> 3. Ensuring gs://${BUCKET} exists and configuring CORS + lifecycle policy"
if ! gcloud storage buckets describe "gs://${BUCKET}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${BUCKET}" \
    --location="${BQ_LOCATION}" \
    --uniform-bucket-level-access \
    --project="${PROJECT_ID}"
fi
gcloud storage buckets update "gs://${BUCKET}" \
  --cors-file=infra/gcs-cors.json \
  --lifecycle-file=infra/gcs-lifecycle.json \
  --project="${PROJECT_ID}"

TF_VARS=(
  -var="project_id=${PROJECT_ID}"
  -var="region=${REGION}"
  -var="bq_location=${BQ_LOCATION}"
  -var="gcs_raw_bucket=${BUCKET}"
  -var="container_image=${IMAGE}"
  -var="google_sheet_id=${GOOGLE_SHEET_ID}"
  -var="transcend_drive_folder_id=${TRANSCEND_DRIVE_FOLDER_ID}"
  -var="default_cpap_start_date=${CPAP_START_DATE}"
  -var="authorized_invokers=${INVOKERS_TF_VAL}"
)

echo "==> 4. Applying Terraform infrastructure (with gcloud fallback if Cloud Shell IPv6 fails on updates)"
pushd infra/terraform >/dev/null
TERRAFORM_OK=true
if ! terraform init -upgrade; then
  TERRAFORM_OK=false
fi
if [ "${TERRAFORM_OK}" = "true" ] && ! terraform state show google_storage_bucket.raw_data >/dev/null 2>&1; then
  if gcloud storage buckets describe "gs://${BUCKET}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    terraform import "${TF_VARS[@]}" google_storage_bucket.raw_data "${BUCKET}" || true
  fi
fi
if [ "${TERRAFORM_OK}" = "true" ] && ! terraform state show google_artifact_registry_repository.repo >/dev/null 2>&1; then
  if gcloud artifacts repositories describe nvd-health --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    terraform import "${TF_VARS[@]}" google_artifact_registry_repository.repo "projects/${PROJECT_ID}/locations/${REGION}/repositories/nvd-health" || true
  fi
fi
if [ "${TERRAFORM_OK}" = "true" ]; then
  if ! terraform apply "${TF_VARS[@]}" -auto-approve; then
    TERRAFORM_OK=false
  fi
fi
popd >/dev/null

if [ "${TERRAFORM_OK}" != "true" ]; then
  if gcloud run services describe nvd-health-web --region="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "WARNING: Terraform failed (e.g. Cloud Shell IPv6 issue). Updating existing Cloud Run services directly via gcloud..."
    gcloud run services update nvd-health-web \
      --project="${PROJECT_ID}" \
      --region="${REGION}" \
      --image="${IMAGE}" \
      --update-env-vars="GOOGLE_SHEET_ID=${GOOGLE_SHEET_ID},TRANSCEND_DRIVE_FOLDER_ID=${TRANSCEND_DRIVE_FOLDER_ID}"
    gcloud run jobs update nvd-health-etl-job \
      --project="${PROJECT_ID}" \
      --region="${REGION}" \
      --image="${IMAGE}" \
      --update-env-vars="GOOGLE_SHEET_ID=${GOOGLE_SHEET_ID},TRANSCEND_DRIVE_FOLDER_ID=${TRANSCEND_DRIVE_FOLDER_ID}"
  else
    echo "ERROR: Initial Terraform provisioning failed before nvd-health-web existed. Resolve the Terraform error above (e.g. run outside IPv6-restricted shell or retry) and rerun $0."
    exit 1
  fi
fi

echo "==> 5. Syncing Dataform workspace files"
export GCP_PROJECT_ID="${PROJECT_ID}"
export GCP_REGION="${REGION}"
export BQ_LOCATION="${BQ_LOCATION}"
export GCS_RAW_BUCKET="${BUCKET}"
export GOOGLE_SHEET_ID="${GOOGLE_SHEET_ID}"
export DEFAULT_CPAP_START_DATE="${CPAP_START_DATE}"
export DATAFORM_SERVICE_ACCOUNT="nvd-health-etl-sa@${PROJECT_ID}.iam.gserviceaccount.com"
PYTHONPATH=backend python3 scripts/sync_dataform.py --compile-only

echo "==> Deployment complete!"
echo "Access the IAM-protected UI locally via:"
echo "  gcloud run services proxy nvd-health-web --region=${REGION} --project=${PROJECT_ID}"
