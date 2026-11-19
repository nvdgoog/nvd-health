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

echo "==> 3. Configuring CORS on gs://${BUCKET} for Direct-to-GCS browser uploads"
gcloud storage buckets update "gs://${BUCKET}" \
  --cors-file=infra/gcs-cors.json \
  --project="${PROJECT_ID}"

echo "==> 4. Applying Terraform infrastructure"
pushd infra/terraform >/dev/null
terraform init -upgrade
if ! terraform state show google_artifact_registry_repository.repo >/dev/null 2>&1; then
  if gcloud artifacts repositories describe nvd-health --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    terraform import -var="container_image=${IMAGE}" google_artifact_registry_repository.repo "projects/${PROJECT_ID}/locations/${REGION}/repositories/nvd-health" || true
  fi
fi
terraform apply -var="container_image=${IMAGE}" -auto-approve
popd >/dev/null

echo "==> 5. Syncing Dataform workspace files"
PYTHONPATH=backend python3 scripts/sync_dataform.py --compile-only

echo "==> Deployment complete!"
echo "Access the IAM-protected UI locally via:"
echo "  gcloud run services proxy nvd-health-web --region=${REGION} --project=${PROJECT_ID}"
