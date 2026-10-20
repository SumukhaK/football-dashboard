#!/usr/bin/env bash
#
# Shared deploy helpers: transport readback, candidate verification and tag
# retirement. Sourced by deploy.sh and rollback.sh; not run on its own.
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

# --- reads ------------------------------------------------------------------

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

current_revision() {
  gcloud run services describe "${SERVICE_NAME}" \
    --project "${GCP_PROJECT_ID}" --region "${REGION}" \
    --format="value(status.latestCreatedRevisionName)"
}

revision_field() {
  gcloud run revisions describe "${1}" \
    --project "${GCP_PROJECT_ID}" --region "${REGION}" \
    --format="${2}"
}

revision_ready() {
  local state
  state="$(revision_field "${1}" "value(status.conditions[?type=='Ready'].status)")"
  if [ "${state}" != "True" ]; then
    fail "revision ${1} is not ready (Ready=${state:-unreadable}); no traffic was moved."
  fi
}

revision_auth_mode() {
  revision_field "${1}" "value(spec.containers[0].env[?name=='AUTH_MODE'].value)"
}

revision_secret() {
  # revision_secret REVISION ENV-NAME: the bound secret name, or empty.
  revision_field "${1}" \
    "value(spec.containers[0].env[?name=='${2}'].valueFrom.secretKeyRef.name)"
}

traffic_tags() {
  gcloud run services describe "${SERVICE_NAME}" \
    --project "${GCP_PROJECT_ID}" --region "${REGION}" \
    --format="value(status.traffic[].tag)"
}

# --- transport --------------------------------------------------------------

require_invoker_check() {
  if [ "$(invoker_check_disabled)" = "true" ]; then
    fail "the invoker IAM check is disabled on ${SERVICE_NAME}."
  fi
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
  gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
    --project "${GCP_PROJECT_ID}" --region "${REGION}" \
    --member="allUsers" --role="roles/run.invoker"
  require_invoker_check
  if ! service_members | grep -q "allUsers"; then
    fail "the service-scoped allUsers binding was not applied; transport stays private."
  fi
}

close_transport() {
  if service_members | grep -q "allUsers"; then
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
  if [ -n "$(traffic_tags | tr -d '[:space:]')" ]; then
    fail "a traffic tag is still reachable after the deploy."
  fi
}
