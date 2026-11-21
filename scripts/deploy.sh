#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-house-tully-310623}"
REGION="${GCP_REGION:-us-central1}"
IMAGE_TAG="${IMAGE_TAG:-$(date -u +%Y%m%d-%H%M%S)}"
IMAGE="${CONTAINER_IMAGE:-${REGION}-docker.pkg.dev/${PROJECT_ID}/nvd-health/nvd-health-platform:${IMAGE_TAG}}"
BUCKET="${GCS_RAW_BUCKET:-nvd-health-raw-data}"

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
    --location="${BQ_LOCATION:-US}" \
    --uniform-bucket-level-access \
    --project="${PROJECT_ID}"
fi
gcloud storage buckets update "gs://${BUCKET}" \
  --cors-file=infra/gcs-cors.json \
  --lifecycle-file=infra/gcs-lifecycle.json \
  --project="${PROJECT_ID}"

echo "==> 4. Applying Terraform infrastructure (with gcloud fallback if Cloud Shell IPv6 fails)"
pushd infra/terraform >/dev/null
TERRAFORM_OK=true
if ! terraform init -upgrade; then
  TERRAFORM_OK=false
fi
if [ "${TERRAFORM_OK}" = "true" ] && ! terraform state show google_storage_bucket.raw_data >/dev/null 2>&1; then
  if gcloud storage buckets describe "gs://${BUCKET}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    terraform import -var="container_image=${IMAGE}" -var="project_id=${PROJECT_ID}" -var="region=${REGION}" -var="gcs_raw_bucket=${BUCKET}" google_storage_bucket.raw_data "${BUCKET}" || true
  fi
fi
if [ "${TERRAFORM_OK}" = "true" ] && ! terraform state show google_artifact_registry_repository.repo >/dev/null 2>&1; then
  if gcloud artifacts repositories describe nvd-health --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    terraform import -var="container_image=${IMAGE}" -var="project_id=${PROJECT_ID}" -var="region=${REGION}" -var="gcs_raw_bucket=${BUCKET}" google_artifact_registry_repository.repo "projects/${PROJECT_ID}/locations/${REGION}/repositories/nvd-health" || true
  fi
fi
if [ "${TERRAFORM_OK}" = "true" ]; then
  if ! terraform apply -var="container_image=${IMAGE}" -var="project_id=${PROJECT_ID}" -var="region=${REGION}" -var="gcs_raw_bucket=${BUCKET}" -auto-approve; then
    TERRAFORM_OK=false
  fi
fi
popd >/dev/null

if [ "${TERRAFORM_OK}" != "true" ]; then
  echo "WARNING: Terraform failed (e.g. Cloud Shell IPv6 issue). Updating Cloud Run directly via gcloud..."
  gcloud run services update nvd-health-web \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --image="${IMAGE}" \
    --update-env-vars="GOOGLE_SHEET_ID=17SgQVoT53xm5299WKZHsIW5PgLInuszCSfeLu50Zsvc"
  gcloud run jobs update nvd-health-etl-job \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --image="${IMAGE}" \
    --update-env-vars="GOOGLE_SHEET_ID=17SgQVoT53xm5299WKZHsIW5PgLInuszCSfeLu50Zsvc"
fi

echo "==> 5. Syncing Dataform workspace files"
PYTHONPATH=backend python3 scripts/sync_dataform.py --compile-only

echo "==> Deployment complete!"
echo "Access the IAM-protected UI locally via:"
echo "  gcloud run services proxy nvd-health-web --region=${REGION} --project=${PROJECT_ID}"
