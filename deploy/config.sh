#!/usr/bin/env bash
# shellcheck disable=SC2034,SC2154
# SC2034: the derived settings are read by the sourcing script, not here.
# SC2154: script_dir is set by the sourcing script before this file.
#
# Operator configuration shared by deploy.sh and promote.sh: the defaults, the
# gitignored deploy/.env.deploy, its validation and the settings derived from
# it. deploy.sh writes these settings onto a candidate; promote.sh compares a
# candidate against the same values, so the two can never drift apart.
#
# Sourced after lib.sh, which provides fail and the require_* checks; not run on
# its own.

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

# NAME=value pairs, comma-separated: the exact form --update-env-vars takes, and
# what verify_candidate reads back one by one.
RUNTIME_ENV="SOURCE=gcp,GCP_PROJECT_ID=${GCP_PROJECT_ID},API_SERVICE_NAME=${API_SERVICE_NAME},CACHE_TTL_SECONDS=60"
RUNTIME_ENV="${RUNTIME_ENV},AUTH_MODE=google,AUTH_PUBLIC_ORIGIN=${AUTH_PUBLIC_ORIGIN}"
RUNTIME_ENV="${RUNTIME_ENV},AUTH_CALLBACK_URL=${AUTH_CALLBACK_URL},OWNER_EMAIL=${OWNER_EMAIL}"
RUNTIME_ENV="${RUNTIME_ENV},GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID},INVITES_ENABLED=false"
# ENV=secret-name:version pairs, the form --update-secrets takes.
RUNTIME_SECRETS="GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET_NAME}:${GOOGLE_CLIENT_SECRET_VERSION}"
RUNTIME_SECRETS="${RUNTIME_SECRETS},SESSION_SIGNING_KEY=${SESSION_SIGNING_KEY_NAME}:${SESSION_SIGNING_KEY_VERSION}"
RUNTIME_SECRETS="${RUNTIME_SECRETS},OAUTH_SIGNING_KEY=${OAUTH_SIGNING_KEY_NAME}:${OAUTH_SIGNING_KEY_VERSION}"
