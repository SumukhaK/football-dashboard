#!/usr/bin/env bash
#
# Build the console image with Cloud Build and deploy it to Cloud Run as an
# unserved candidate. This script never moves traffic and never opens public
# access: promotion is deploy/promote.sh, run separately after the candidate
# has been checked privately and the checks are recorded.
#
# The service must already be private (or not exist yet), because the
# candidate's tag URL shares the service's access policy: a public service
# would expose the candidate before anyone has looked at it.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${script_dir}/.."

# shellcheck source=/dev/null
source "${script_dir}/lib.sh"
# shellcheck source=/dev/null
source "${script_dir}/verification.sh"
set_deploy_defaults
# shellcheck source=/dev/null
source "${script_dir}/.env.deploy"
load_deploy_config

RUNTIME_ENV="SOURCE=gcp,GCP_PROJECT_ID=${GCP_PROJECT_ID},API_SERVICE_NAME=${API_SERVICE_NAME},CACHE_TTL_SECONDS=60"
RUNTIME_ENV="${RUNTIME_ENV},AUTH_MODE=google,AUTH_PUBLIC_ORIGIN=${AUTH_PUBLIC_ORIGIN}"
RUNTIME_ENV="${RUNTIME_ENV},AUTH_CALLBACK_URL=${AUTH_CALLBACK_URL},OWNER_EMAIL=${OWNER_EMAIL}"
RUNTIME_ENV="${RUNTIME_ENV},GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID},INVITES_ENABLED=false"
RUNTIME_SECRETS="GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET_NAME}:${GOOGLE_CLIENT_SECRET_VERSION}"
RUNTIME_SECRETS="${RUNTIME_SECRETS},SESSION_SIGNING_KEY=${SESSION_SIGNING_KEY_NAME}:${SESSION_SIGNING_KEY_VERSION}"
RUNTIME_SECRETS="${RUNTIME_SECRETS},OAUTH_SIGNING_KEY=${OAUTH_SIGNING_KEY_NAME}:${OAUTH_SIGNING_KEY_VERSION}"

# A candidate behind a tag on a public service would be public. A service that
# does not exist yet has nothing to expose; the deploy below creates it private.
existing="$(service_names)"
if [ -n "${existing}" ]; then
  refuse_if_public "creating a candidate"
fi

# Artifact Registry holds the image; create the repository once.
if ! gcloud artifacts repositories describe "${REPOSITORY}" \
  --project "${GCP_PROJECT_ID}" --location "${REGION}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${REPOSITORY}" \
    --project "${GCP_PROJECT_ID}" \
    --location "${REGION}" \
    --repository-format docker \
    --description "Football dashboard console images"
fi

# Capture this build's digest; another push of latest must not replace it.
BUILD_RESULT="$(gcloud builds submit . \
  --project "${GCP_PROJECT_ID}" \
  --tag "${IMAGE}:latest" \
  --suppress-logs \
  --format='value(id,results.images[0].digest)')"
IFS=$'\t' read -r BUILD_ID DIGEST <<<"${BUILD_RESULT}"
[ -n "${BUILD_ID}" ] && [ -n "${DIGEST}" ] ||
  fail "the completed build returned no build id or image digest"
require_digest "${DIGEST}"
CANDIDATE="${SERVICE_NAME}-${BUILD_ID}"

# The candidate goes out with no traffic, behind a tag, while the service stays
# private. --update-env-vars and --update-secrets merge rather than replace, so
# settings added by hand (such as the crashes page's) survive; the auth settings
# this script owns are updated on every deploy and can never be dropped.
gcloud run deploy "${SERVICE_NAME}" \
  --project "${GCP_PROJECT_ID}" \
  --region "${REGION}" \
  --image "${IMAGE}@${DIGEST}" \
  --revision-suffix "${BUILD_ID}" \
  --no-traffic \
  --tag "${CANDIDATE_TAG}" \
  --no-allow-unauthenticated \
  --invoker-iam-check \
  --service-account "${READER}" \
  --min-instances 0 \
  --max-instances 1 \
  --cpu 1 \
  --memory 512Mi \
  --concurrency 20 \
  --timeout 60 \
  --update-env-vars "${RUNTIME_ENV}" \
  --update-secrets "${RUNTIME_SECRETS}"

# Read the candidate back: a revision that cannot start, or that does not run
# this build with these settings and key versions, is reported now rather than
# at promotion. Then confirm the tag URL is as private as the service.
verify_revision "${CANDIDATE}" "${DIGEST}"
require_private

echo
echo "Candidate ${CANDIDATE} is deployed with no traffic."
echo "  Image digest: ${DIGEST}"
echo "  Transport:    private (Cloud Run IAM; no public binding)"
echo
echo "Check it privately before promoting it (deploy/README.md, 'Verify a candidate'):"
echo "  gcloud run services proxy ${SERVICE_NAME} --tag ${CANDIDATE_TAG} --project ${GCP_PROJECT_ID} --region ${REGION}"
echo "Record what you saw in deploy/verification/${CANDIDATE}.env"
echo "(start from deploy/verification.example.env), then promote it with:"
echo "  bash deploy/promote.sh ${CANDIDATE} ${DIGEST}"
