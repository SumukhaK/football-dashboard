#!/usr/bin/env bash
#
# Build the console image with Cloud Build and deploy it to Cloud Run: private,
# as the read-only reader account, scaling to zero.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${script_dir}/.."

GCP_PROJECT_ID=""
REGION=""
API_SERVICE_NAME="football-api"
SERVICE_NAME="football-dashboard"
REPOSITORY="football-dashboard"
# shellcheck source=/dev/null
source "${script_dir}/.env.deploy"

: "${GCP_PROJECT_ID:?set GCP_PROJECT_ID in deploy/.env.deploy}"
: "${REGION:?set REGION in deploy/.env.deploy}"

READER="football-dashboard-reader@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
IMAGE="${REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${REPOSITORY}/console"

# Artifact Registry holds the image; create the repository once.
if ! gcloud artifacts repositories describe "${REPOSITORY}" \
  --project "${GCP_PROJECT_ID}" --location "${REGION}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${REPOSITORY}" \
    --project "${GCP_PROJECT_ID}" \
    --location "${REGION}" \
    --repository-format docker \
    --description "Football dashboard console images"
fi

# Build with Cloud Build and push the tag.
gcloud builds submit . \
  --project "${GCP_PROJECT_ID}" \
  --tag "${IMAGE}:latest"

# Deploy by digest, so a later push of the tag cannot change this revision.
DIGEST="$(gcloud artifacts docker images describe "${IMAGE}:latest" \
  --project "${GCP_PROJECT_ID}" \
  --format='value(image_summary.digest)')"

gcloud run deploy "${SERVICE_NAME}" \
  --project "${GCP_PROJECT_ID}" \
  --region "${REGION}" \
  --image "${IMAGE}@${DIGEST}" \
  --no-allow-unauthenticated \
  --service-account "${READER}" \
  --min-instances 0 \
  --max-instances 1 \
  --cpu 1 \
  --memory 512Mi \
  --concurrency 20 \
  --timeout 60 \
  --set-env-vars "SOURCE=gcp,GCP_PROJECT_ID=${GCP_PROJECT_ID},API_SERVICE_NAME=${API_SERVICE_NAME},CACHE_TTL_SECONDS=60"

echo
echo "Open it as the owner with:"
echo "  gcloud run services proxy ${SERVICE_NAME} --project ${GCP_PROJECT_ID} --region ${REGION}"
