#!/usr/bin/env bash
#
# Check a named revision before it may take traffic: what is running, and what
# the operator recorded about it. Sourced by deploy.sh, promote.sh and
# rollback.sh after lib.sh and load_deploy_config; not run on its own.
#
# Nonempty secret names and AUTH_MODE=google alone do not prove that the
# reviewed image and the current keys are running, so every setting this
# project owns is read back and compared with deploy/.env.deploy. Only names
# and version numbers are compared or printed, never a secret value.

# The checks an operator records, by key, before a revision is promoted. Each
# needs a short note of what was seen, not a bare "yes".
VERIFICATION_CHECKS=(
  SIGNED_OUT_DENIED
  PARTIAL_DENIED
  OWNER_ALLOWED
  NON_OWNER_DENIED
  PRIVACY_CHECKED
  VERIFIED_BY
  VERIFIED_AT
)

# --- what is running --------------------------------------------------------

revision_setting() {
  revision_field "${1}" "value(spec.containers[0].env.filter(name=${2}).extract(value).flatten())"
}

revision_secret_version() {
  revision_field "${1}" \
    "value(spec.containers[0].env.filter(name=${2}).extract(valueFrom.secretKeyRef.key).flatten())"
}

secret_version_state() {
  # The state of a secret version (its metadata, never its value).
  gcloud secrets versions describe "${2}" \
    --secret "${1}" --project "${GCP_PROJECT_ID}" \
    --format="value(state)"
}

expect_value() {
  # expect_value REVISION WHAT EXPECTED ACTUAL
  if [ "${4}" != "${3}" ]; then
    fail "revision ${1} does not carry ${2}=${3} (found '${4:-nothing}'); refusing to serve it"
  fi
}

verify_setting() {
  local actual
  actual="$(revision_setting "${1}" "${2}")"
  expect_value "${1}" "${2}" "${3}" "${actual}"
}

verify_secret() {
  # verify_secret REVISION ENV-NAME SECRET-NAME VERSION
  local actual
  actual="$(revision_secret "${1}" "${2}")"
  if [ -z "${actual}" ]; then
    fail "revision ${1} does not bind ${2}; refusing to serve it"
  fi
  expect_value "${1}" "${2} secret" "${3}" "${actual}"
  actual="$(revision_secret_version "${1}" "${2}")"
  if [ "${actual}" != "${4}" ]; then
    fail "revision ${1} binds ${2} to ${3} version ${actual:-nothing}, but deploy/.env.deploy names version ${4}.
An old key version is never re-enabled for it: redeploy that code with the current versions instead."
  fi
  actual="$(secret_version_state "${3}" "${4}")"
  if [ "${actual}" != "ENABLED" ]; then
    fail "secret ${3} version ${4} is ${actual:-unreadable}, not ENABLED; refusing to serve ${1}"
  fi
}

verify_revision() {
  # verify_revision REVISION DIGEST: the revision runs the reviewed image with
  # this project's settings and the current, enabled key versions.
  local actual
  revision_ready "${1}"
  actual="$(revision_field "${1}" "value(spec.containers[0].image)")"
  expect_value "${1}" "image" "${IMAGE}@${2}" "${actual}"
  actual="$(revision_field "${1}" "value(spec.serviceAccountName)")"
  expect_value "${1}" "service account" "${READER}" "${actual}"
  verify_setting "${1}" SOURCE gcp
  verify_setting "${1}" GCP_PROJECT_ID "${GCP_PROJECT_ID}"
  verify_setting "${1}" API_SERVICE_NAME "${API_SERVICE_NAME}"
  verify_setting "${1}" AUTH_MODE google
  verify_setting "${1}" AUTH_PUBLIC_ORIGIN "${AUTH_PUBLIC_ORIGIN}"
  verify_setting "${1}" AUTH_CALLBACK_URL "${AUTH_CALLBACK_URL}"
  verify_setting "${1}" OWNER_EMAIL "${OWNER_EMAIL}"
  verify_setting "${1}" GOOGLE_CLIENT_ID "${GOOGLE_CLIENT_ID}"
  verify_setting "${1}" INVITES_ENABLED false
  verify_secret "${1}" GOOGLE_CLIENT_SECRET \
    "${GOOGLE_CLIENT_SECRET_NAME}" "${GOOGLE_CLIENT_SECRET_VERSION}"
  verify_secret "${1}" SESSION_SIGNING_KEY \
    "${SESSION_SIGNING_KEY_NAME}" "${SESSION_SIGNING_KEY_VERSION}"
  verify_secret "${1}" OAUTH_SIGNING_KEY \
    "${OAUTH_SIGNING_KEY_NAME}" "${OAUTH_SIGNING_KEY_VERSION}"
}

# --- what the operator recorded ---------------------------------------------

record_value() {
  # The last KEY=value line in the record. The record is read as data and is
  # never sourced, so nothing in it can run.
  sed -n "s/^${2}=//p" "${1}" | tail -n 1
}

require_verification_record() {
  # require_verification_record REVISION DIGEST
  local record="deploy/verification/${1}.env" check value
  if [ ! -f "${record}" ]; then
    fail "no verification record for ${1} at ${record}.
Run the private checks in deploy/README.md ('Verify a candidate') against this
revision and record what you saw, starting from deploy/verification.example.env."
  fi
  value="$(record_value "${record}" REVISION)"
  [ "${value}" = "${1}" ] ||
    fail "${record} records revision '${value:-nothing}', not ${1}"
  value="$(record_value "${record}" DIGEST)"
  [ "${value}" = "${2}" ] ||
    fail "${record} records digest '${value:-nothing}', not ${2}"
  for check in "${VERIFICATION_CHECKS[@]}"; do
    value="$(record_value "${record}" "${check}")"
    # tr rather than ${value,,}: macOS still ships bash 3.2.
    case "$(tr '[:upper:]' '[:lower:]' <<<"${value}")" in
      "")
        fail "${record} has no ${check}: record what you saw before promoting ${1}"
        ;;
      true | yes | y | ok | pass | passed | done | 1 | verified)
        fail "${record}: ${check}='${value}' is a flag, not evidence; note what you saw"
        ;;
    esac
  done
}
