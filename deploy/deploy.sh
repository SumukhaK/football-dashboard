#!/usr/bin/env bash
#
# Build the console image with Cloud Build and create an unserved candidate.
#
# This script never serves anything and never opens access. It refuses to run
# while the service is public (a candidate tag would be reachable through the
# public edge), deploys the new revision with no traffic behind a tag, reads it
# back, and prints what to check privately and the separate promotion command.
# Serving the candidate is deploy/promote.sh, after those checks are recorded.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${script_dir}/.."

# shellcheck source=/dev/null
source "${script_dir}/lib.sh"
# shellcheck source=/dev/null
source "${script_dir}/config.sh"

# Prove the edge is private before a candidate or its tag exists. A service
# that has never been created has no edge yet; a failed read aborts here.
if service_exists; then
  refuse_if_public "a candidate tag"
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
CANDIDATE="${SERVICE_NAME}-${BUILD_ID}"

# The candidate goes out with no traffic, behind a tag, on a private service. --update-env-vars and --update-secrets merge rather than replace, so
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

# Read the candidate back now, so a revision that cannot start or was built
# without the owner sign-in is reported here rather than at promotion.
revision_ready "${CANDIDATE}"
candidate_mode="$(revision_auth_mode "${CANDIDATE}")"
if [ "${candidate_mode}" != "google" ]; then
  fail "candidate ${CANDIDATE} does not carry AUTH_MODE=google; it cannot be promoted"
fi
for binding in GOOGLE_CLIENT_SECRET SESSION_SIGNING_KEY OAUTH_SIGNING_KEY; do
  bound_secret="$(revision_secret "${CANDIDATE}" "${binding}")"
  [ -n "${bound_secret}" ] ||
    fail "candidate ${CANDIDATE} does not bind ${binding}; it cannot be promoted"
done

# Creating the candidate must not have changed the edge.
require_private

echo
echo "Candidate ${CANDIDATE} is ready with no traffic; the service is private."
echo "Image: ${IMAGE}@${DIGEST}"
echo "Check it privately through its tag (Cloud Run IAM still applies):"
echo "  gcloud run services proxy ${SERVICE_NAME} --tag ${CANDIDATE_TAG} --project ${GCP_PROJECT_ID} --region ${REGION}"
echo "Record what each check showed in a copy of deploy/verification.example, then serve it with:"
echo "  bash deploy/promote.sh ${CANDIDATE} ${DIGEST} <verification-record>"
