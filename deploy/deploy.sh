#!/usr/bin/env bash
#
# Build the console image with Cloud Build and deploy it to Cloud Run.
#
# The default transport is private: Cloud Run IAM (proxy or an identity token)
# is the edge, and the application's owner-only Google sign-in sits inside it.
# `DASHBOARD_TRANSPORT=app-auth` is the explicit, validated opt-in that opens
# the service to the public internet *after* the candidate has been verified,
# because the application then enforces the owner sign-in itself.
#
# A deploy never serves the revision it just built until that revision has been
# read back as Ready and carrying AUTH_MODE=google; promotion names the revision
# explicitly instead of guessing at "latest".
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${script_dir}/.."

GCP_PROJECT_ID=""
REGION=""
API_SERVICE_NAME="football-api"
SERVICE_NAME="football-dashboard"
REPOSITORY="football-dashboard"
DASHBOARD_TRANSPORT="private"
CANDIDATE_TAG="candidate"
GOOGLE_CLIENT_SECRET_NAME="google-client-secret"
SESSION_SIGNING_KEY_NAME="session-signing-key"
OAUTH_SIGNING_KEY_NAME="oauth-signing-key"
# shellcheck source=/dev/null
source "${script_dir}/.env.deploy"
# shellcheck source=/dev/null
source "${script_dir}/lib.sh"

: "${GCP_PROJECT_ID:?set GCP_PROJECT_ID in deploy/.env.deploy}"
: "${REGION:?set REGION in deploy/.env.deploy}"
require_value "AUTH_PUBLIC_ORIGIN" "${AUTH_PUBLIC_ORIGIN:-}"
require_value "GOOGLE_CLIENT_ID" "${GOOGLE_CLIENT_ID:-}"
require_value "OWNER_EMAIL" "${OWNER_EMAIL:-}"
require_version "GOOGLE_CLIENT_SECRET_VERSION" "${GOOGLE_CLIENT_SECRET_VERSION:-}"
require_version "SESSION_SIGNING_KEY_VERSION" "${SESSION_SIGNING_KEY_VERSION:-}"
require_version "OAUTH_SIGNING_KEY_VERSION" "${OAUTH_SIGNING_KEY_VERSION:-}"
require_value "GOOGLE_CLIENT_SECRET_NAME" "${GOOGLE_CLIENT_SECRET_NAME}"
require_value "SESSION_SIGNING_KEY_NAME" "${SESSION_SIGNING_KEY_NAME}"
require_value "OAUTH_SIGNING_KEY_NAME" "${OAUTH_SIGNING_KEY_NAME}"

case "${AUTH_PUBLIC_ORIGIN}" in
  https://*) ;;
  *) fail "AUTH_PUBLIC_ORIGIN must be an https origin, not '${AUTH_PUBLIC_ORIGIN}'" ;;
esac
case "${GOOGLE_CLIENT_ID}" in
  *.apps.googleusercontent.com) ;;
  *) fail "GOOGLE_CLIENT_ID must be a Web OAuth client id" ;;
esac
AUTH_CALLBACK_URL="${AUTH_PUBLIC_ORIGIN}/auth/callback"

case "${DASHBOARD_TRANSPORT}" in
  private | app-auth) ;;
  *)
    fail "DASHBOARD_TRANSPORT must be 'private' (default) or 'app-auth', not '${DASHBOARD_TRANSPORT}'"
    ;;
esac

READER="football-dashboard-reader@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
IMAGE="${REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${REPOSITORY}/console"

RUNTIME_ENV="SOURCE=gcp,GCP_PROJECT_ID=${GCP_PROJECT_ID},API_SERVICE_NAME=${API_SERVICE_NAME},CACHE_TTL_SECONDS=60"
RUNTIME_ENV="${RUNTIME_ENV},AUTH_MODE=google,AUTH_PUBLIC_ORIGIN=${AUTH_PUBLIC_ORIGIN}"
RUNTIME_ENV="${RUNTIME_ENV},AUTH_CALLBACK_URL=${AUTH_CALLBACK_URL},OWNER_EMAIL=${OWNER_EMAIL}"
RUNTIME_ENV="${RUNTIME_ENV},GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID},INVITES_ENABLED=false"
RUNTIME_SECRETS="GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET_NAME}:${GOOGLE_CLIENT_SECRET_VERSION}"
RUNTIME_SECRETS="${RUNTIME_SECRETS},SESSION_SIGNING_KEY=${SESSION_SIGNING_KEY_NAME}:${SESSION_SIGNING_KEY_VERSION}"
RUNTIME_SECRETS="${RUNTIME_SECRETS},OAUTH_SIGNING_KEY=${OAUTH_SIGNING_KEY_NAME}:${OAUTH_SIGNING_KEY_VERSION}"

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

# The candidate goes out with no traffic, behind a tag, while the service stays
# private. --update-env-vars and --update-secrets merge rather than replace, so
# settings added by hand (such as the crashes page's) survive; the auth settings
# this script owns are updated on every deploy and can never be dropped.
gcloud run deploy "${SERVICE_NAME}" \
  --project "${GCP_PROJECT_ID}" \
  --region "${REGION}" \
  --image "${IMAGE}@${DIGEST}" \
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

# Read the candidate back before anything is served: a revision that cannot
# start, or that was built without the owner sign-in, must not take traffic.
CANDIDATE="$(current_revision)"
[ -n "${CANDIDATE}" ] || fail "could not read the revision that was just created"
revision_ready "${CANDIDATE}"
if [ "$(revision_auth_mode "${CANDIDATE}")" != "google" ]; then
  fail "candidate ${CANDIDATE} does not carry AUTH_MODE=google; refusing to serve it"
fi
for binding in GOOGLE_CLIENT_SECRET SESSION_SIGNING_KEY OAUTH_SIGNING_KEY; do
  [ -n "$(revision_secret "${CANDIDATE}" "${binding}")" ] ||
    fail "candidate ${CANDIDATE} does not bind ${binding}; refusing to serve it"
done

# Pin the verified candidate explicitly. A rollback leaves a persistent traffic
# pin, so "latest" is never a safe guess; the revision name is the contract.
gcloud run services update-traffic "${SERVICE_NAME}" \
  --project "${GCP_PROJECT_ID}" \
  --region "${REGION}" \
  --to-revisions="${CANDIDATE}=100"

# Tags reach revisions at 0% traffic. Retire every one of them before any
# transport change, so no reachable URL points at an older image.
retire_tags

if [ "${DASHBOARD_TRANSPORT}" = "app-auth" ]; then
  # Explicit opt-in, after the guarded revision serves 100%: one service-scoped
  # allUsers binding, with the invoker IAM check left enabled.
  open_transport
  echo
  echo "Transport: app-auth (public edge, application owner sign-in enforced)."
else
  require_private
  echo
  echo "Transport: private (Cloud Run IAM; no public binding)."
fi

echo
echo "Revision ${CANDIDATE} is serving 100% of traffic."
echo "Open it as the owner with:"
echo "  gcloud run services proxy ${SERVICE_NAME} --project ${GCP_PROJECT_ID} --region ${REGION}"
