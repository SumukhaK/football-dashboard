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


require_private() {
  # Cloud Run is public two independent ways: an allUsers binding, or the invoker
  # IAM check switched off. --no-allow-unauthenticated only covers the first, so
  # check both before saying the deploy succeeded. Each read is its own command,
  # so a read that fails aborts instead of passing for an empty policy.
  local members
  members="$(gcloud run services get-iam-policy "${SERVICE_NAME}" \
    --project "${GCP_PROJECT_ID}" --region "${REGION}" \
    --format="value(bindings.members)")"
  if grep -q "allUsers" <<<"${members}"; then
    echo "ERROR: ${SERVICE_NAME} is bound to allUsers, so it is public." >&2
    exit 1
  fi

  local invoker_disabled
  invoker_disabled="$(gcloud run services describe "${SERVICE_NAME}" \
    --project "${GCP_PROJECT_ID}" --region "${REGION}" \
    --format="value(metadata.annotations['run.googleapis.com/invoker-iam-disabled'])")"
  if [ "${invoker_disabled}" = "true" ]; then
    echo "ERROR: the invoker IAM check is disabled on ${SERVICE_NAME}." >&2
    exit 1
  fi
}


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

# Update the four settings this script owns rather than replacing the whole
# environment: --set-env-vars would drop anything added by hand, such as the
# settings the crashes page needs, on every later deploy.
gcloud run deploy "${SERVICE_NAME}" \
  --project "${GCP_PROJECT_ID}" \
  --region "${REGION}" \
  --image "${IMAGE}@${DIGEST}" \
  --no-allow-unauthenticated \
  --invoker-iam-check \
  --service-account "${READER}" \
  --min-instances 0 \
  --max-instances 1 \
  --cpu 1 \
  --memory 512Mi \
  --concurrency 20 \
  --timeout 60 \
  --update-env-vars "SOURCE=gcp,GCP_PROJECT_ID=${GCP_PROJECT_ID},API_SERVICE_NAME=${API_SERVICE_NAME},CACHE_TTL_SECONDS=60"

# A rollback pins traffic to an older revision, and a later deploy keeps that pin,
# so route to the revision just deployed instead of leaving the old one serving.
gcloud run services update-traffic "${SERVICE_NAME}" \
  --project "${GCP_PROJECT_ID}" \
  --region "${REGION}" \
  --to-latest

require_private

echo
echo "Open it as the owner with:"
echo "  gcloud run services proxy ${SERVICE_NAME} --project ${GCP_PROJECT_ID} --region ${REGION}"
