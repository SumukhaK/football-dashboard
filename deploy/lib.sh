#!/usr/bin/env bash
#
# Shared deploy helpers: operator configuration, transport readback and tag
# retirement. Sourced by deploy.sh, promote.sh and rollback.sh; not run on its
# own. Each script sources this file first, then sets the defaults, then reads
# deploy/.env.deploy, so the operator's file always wins over a default.
#
# Every read is its own command so a failed read aborts the caller instead of
# passing for an empty policy. Nothing here writes a secret value: the scripts
# bind numeric secret versions, and only names and numbers are ever printed.

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

# --- required operator configuration ----------------------------------------

require_value() {
  # require_value NAME "value" [pattern-description]
  if [ -z "${2}" ]; then
    fail "set ${1} in deploy/.env.deploy (see deploy/.env.deploy.example)"
  fi
  case "${2}" in
    *" "* | *","*)
      fail "${1} must not contain spaces or commas: they would break a gcloud list"
      ;;
  esac
}

require_version() {
  # A secret version is a number, never "latest": a deploy must be repeatable.
  case "${2}" in
    "" | *[!0-9]*)
      fail "${1} must be a numeric secret version, not '${2:-empty}'"
      ;;
  esac
}

set_deploy_defaults() {
  # Cleared first so a value exported in the operator's shell never stands in
  # for one missing from deploy/.env.deploy.
  # shellcheck disable=SC2034 # read by the scripts that source this file
  {
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
  }
}

require_location() {
  : "${GCP_PROJECT_ID:?set GCP_PROJECT_ID in deploy/.env.deploy}"
  : "${REGION:?set REGION in deploy/.env.deploy}"
}

load_deploy_config() {
  # Everything a revision is built from and later checked against. A value
  # that is missing or malformed stops the script before any Google call.
  require_location
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
  case "${DASHBOARD_TRANSPORT}" in
    private | app-auth) ;;
    *)
      fail "DASHBOARD_TRANSPORT must be 'private' (default) or 'app-auth', not '${DASHBOARD_TRANSPORT}'"
      ;;
  esac
  # shellcheck disable=SC2034 # read by the scripts that source this file
  {
    AUTH_CALLBACK_URL="${AUTH_PUBLIC_ORIGIN}/auth/callback"
    READER="football-dashboard-reader@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
    IMAGE="${REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${REPOSITORY}/console"
  }
}

require_revision_name() {
  # require_revision_name REVISION USAGE: a named revision, never a guess.
  case "${1}" in
    "")
      fail "usage: ${2}; never 'latest'"
      ;;
    latest | LATEST | latest-*)
      fail "refusing '${1}': name the revision"
      ;;
    *[!a-z0-9-]*)
      fail "'${1}' is not a Cloud Run revision name"
      ;;
  esac
}

require_digest() {
  # The immutable image digest the reviewed revision was built from.
  local hex="${1#sha256:}"
  if [ "${hex}" = "${1}" ] || [ -z "${hex}" ]; then
    fail "the digest must be the image's sha256:<hex> digest, not '${1:-empty}'"
  fi
  case "${hex}" in
    *[!0-9a-f]*) fail "the digest must be the image's sha256:<hex> digest, not '${1}'" ;;
  esac
}

# --- reads ------------------------------------------------------------------

service_names() {
  # Empty when the service does not exist yet; a failed read aborts.
  gcloud run services list \
    --project "${GCP_PROJECT_ID}" --region "${REGION}" \
    --filter="metadata.name=${SERVICE_NAME}" \
    --format="value(metadata.name)"
}

service_members() {
  gcloud run services get-iam-policy "${SERVICE_NAME}" \
    --project "${GCP_PROJECT_ID}" --region "${REGION}" \
    --format="value(bindings.members)"
}

invoker_check_disabled() {
  gcloud run services describe "${SERVICE_NAME}" \
    --project "${GCP_PROJECT_ID}" --region "${REGION}" \
    --format="value(metadata.annotations['run.googleapis.com/invoker-iam-disabled'])"
}

revision_field() {
  gcloud run revisions describe "${1}" \
    --project "${GCP_PROJECT_ID}" --region "${REGION}" \
    --format="${2}"
}

revision_ready() {
  local state
  state="$(revision_field "${1}" "value(status.conditions.filter(type=Ready).extract(status).flatten())")"
  if [ "${state}" != "True" ]; then
    fail "revision ${1} is not ready (Ready=${state:-unreadable}); no traffic was moved."
  fi
}

revision_auth_mode() {
  revision_field "${1}" "value(spec.containers[0].env.filter(name=AUTH_MODE).extract(value).flatten())"
}

revision_secret() {
  # revision_secret REVISION ENV-NAME: the bound secret name, or empty.
  revision_field "${1}" \
    "value(spec.containers[0].env.filter(name=${2}).extract(valueFrom.secretKeyRef.name).flatten())"
}

traffic_tags() {
  gcloud run services describe "${SERVICE_NAME}" \
    --project "${GCP_PROJECT_ID}" --region "${REGION}" \
    --format='value[delimiter="\n"](status.traffic[].tag)'
}

# --- transport --------------------------------------------------------------

require_invoker_check() {
  local disabled
  disabled="$(invoker_check_disabled)"
  if [ "${disabled}" = "true" ]; then
    fail "the invoker IAM check is disabled on ${SERVICE_NAME}."
  fi
}

refuse_if_public() {
  # refuse_if_public ACTION: stop before ACTION while the service is public,
  # because a tagged or newly served revision would be public too. Closing the
  # edge is an outage for public users, so it is the operator's call, not ours.
  local members
  members="$(service_members)"
  if grep -q "allUsers" <<<"${members}"; then
    fail "${SERVICE_NAME} is public (allUsers is bound), so ${1} would expose an unverified revision.
Close the public edge first, then run this again:
  gcloud run services remove-iam-policy-binding ${SERVICE_NAME} --project ${GCP_PROJECT_ID} --region ${REGION} --member=allUsers --role=roles/run.invoker
Signed-in users lose access until a verified revision is promoted with DASHBOARD_TRANSPORT=app-auth."
  fi
  require_invoker_check
}

require_private() {
  local members
  members="$(service_members)"
  if grep -q "allUsers" <<<"${members}"; then
    fail "${SERVICE_NAME} is bound to allUsers, so it is public."
  fi
  require_invoker_check
}

open_transport() {
  # The only public switch this project allows: one service-scoped allUsers
  # binding on this dashboard. The invoker IAM check stays enabled, and no
  # project-level policy is touched.
  local members
  require_invoker_check
  gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
    --project "${GCP_PROJECT_ID}" --region "${REGION}" \
    --member="allUsers" --role="roles/run.invoker"
  require_invoker_check
  members="$(service_members)"
  if ! grep -q "allUsers" <<<"${members}"; then
    fail "the service-scoped allUsers binding was not applied; transport stays private."
  fi
}

close_transport() {
  local members
  members="$(service_members)"
  if grep -q "allUsers" <<<"${members}"; then
    gcloud run services remove-iam-policy-binding "${SERVICE_NAME}" \
      --project "${GCP_PROJECT_ID}" --region "${REGION}" \
      --member="allUsers" --role="roles/run.invoker"
  fi
  require_private
}

# --- tags -------------------------------------------------------------------

retire_tags() {
  # A tag reaches a revision at 0% traffic. After a promotion, every tag is an
  # old URL that may bypass the intended boundary, so all of them are removed
  # and the readback has to come back empty.
  local tags joined tag
  tags="$(traffic_tags)"
  joined=""
  while IFS= read -r tag; do
    tag="${tag//[[:space:]]/}"
    [ -n "${tag}" ] || continue
    joined="${joined:+${joined},}${tag}"
  done <<<"${tags}"
  if [ -z "${joined}" ]; then
    return 0
  fi
  gcloud run services update-traffic "${SERVICE_NAME}" \
    --project "${GCP_PROJECT_ID}" --region "${REGION}" \
    --remove-tags="${joined}"
  tags="$(traffic_tags)"
  if [ -n "${tags//[[:space:]]/}" ]; then
    fail "a traffic tag is still reachable after the deploy."
  fi
}
