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

# --- operator arguments -----------------------------------------------------

require_revision_name() {
  # The revision is the contract: "latest" is a guess, not a reviewed image.
  case "${1}" in
    "")
      fail "name the revision; never 'latest'"
      ;;
    latest | LATEST | latest-*)
      fail "refusing '${1}': name the revision to serve"
      ;;
    *[!a-z0-9-]*)
      fail "'${1}' is not a Cloud Run revision name"
      ;;
  esac
}

require_digest() {
  # An immutable image digest, as deploy.sh prints it: sha256:<hex>.
  local hex="${1#sha256:}"
  if [ "${hex}" = "${1}" ] || [ -z "${hex}" ] || [[ "${hex}" == *[!0-9a-f]* ]]; then
    fail "'${1:-empty}' is not an image digest; pass the sha256:... deploy.sh printed"
  fi
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

revision_env() {
  # revision_env REVISION ENV-NAME: the plain value, or empty.
  revision_field "${1}" "value(spec.containers[0].env.filter(name=${2}).extract(value).flatten())"
}

revision_auth_mode() {
  revision_env "${1}" "AUTH_MODE"
}

revision_secret() {
  # revision_secret REVISION ENV-NAME: the bound secret name, or empty.
  revision_field "${1}" \
    "value(spec.containers[0].env.filter(name=${2}).extract(valueFrom.secretKeyRef.name).flatten())"
}

revision_secret_version() {
  # revision_secret_version REVISION ENV-NAME: the bound version, or empty.
  revision_field "${1}" \
    "value(spec.containers[0].env.filter(name=${2}).extract(valueFrom.secretKeyRef.key).flatten())"
}

revision_image() {
  revision_field "${1}" "value(spec.containers[0].image)"
}

service_exists() {
  # A list rather than a describe: a failed read aborts the caller, and only
  # an empty answer means the service has not been created yet.
  local found
  found="$(gcloud run services list \
    --project "${GCP_PROJECT_ID}" --region "${REGION}" \
    --filter="metadata.name=${SERVICE_NAME}" --format="value(metadata.name)")"
  [ -n "${found//[[:space:]]/}" ]
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

refuse_if_public() {
  # refuse_if_public WHAT: stop before WHAT when the service is reachable
  # without Cloud Run IAM. Closing the edge here would take the live console
  # offline, which is the operator's decision, so the fix is printed instead.
  local members
  members="$(service_members)"
  if grep -q "allUsers" <<<"${members}"; then
    fail "${SERVICE_NAME} is public (allUsers is bound), so ${1} would be reachable without Cloud Run IAM.
Close the public edge first; browsers lose access until a verified revision is promoted:
  gcloud run services remove-iam-policy-binding ${SERVICE_NAME} --project ${GCP_PROJECT_ID} --region ${REGION} --member=allUsers --role=roles/run.invoker
Then run this script again."
  fi
  require_invoker_check
}

# --- candidate verification -------------------------------------------------

verify_candidate() {
  # verify_candidate REVISION DIGEST: the revision runs the reviewed image, is
  # Ready, and carries exactly the settings and secret versions configured in
  # deploy/.env.deploy. AUTH_MODE=google and a nonempty secret name are not
  # enough: a wrong owner, origin or key version would still pass those.
  local revision="${1}" digest="${2}" image pair name expected actual
  local -a pairs
  image="$(revision_image "${revision}")"
  if [ "${image}" != "${IMAGE}@${digest}" ]; then
    fail "revision ${revision} runs '${image:-unreadable}', not ${IMAGE}@${digest}"
  fi
  revision_ready "${revision}"
  IFS=',' read -ra pairs <<<"${RUNTIME_ENV}"
  for pair in "${pairs[@]}"; do
    name="${pair%%=*}"
    expected="${pair#*=}"
    actual="$(revision_env "${revision}" "${name}")"
    if [ "${actual}" != "${expected}" ]; then
      fail "revision ${revision} has ${name}='${actual}', not '${expected}' from deploy/.env.deploy"
    fi
  done
  IFS=',' read -ra pairs <<<"${RUNTIME_SECRETS}"
  for pair in "${pairs[@]}"; do
    name="${pair%%=*}"
    expected="${pair#*=}"
    # Two reads, two assignments: a failure in either aborts on its own.
    actual="$(revision_secret "${revision}" "${name}")"
    actual="${actual}:$(revision_secret_version "${revision}" "${name}")"
    if [ "${actual}" != "${expected}" ]; then
      fail "revision ${revision} binds ${name} to '${actual}', not '${expected}'.
If it pins retired key versions, redeploy current code with deploy/deploy.sh; old versions are never re-enabled."
    fi
  done
}

# What each private check showed has to be written down per check; "true" is
# not evidence. See deploy/verification.example.
VERIFICATION_CHECKS="signed_out_denied partial_session_denied owner_allowed non_owner_denied privacy_checks"

record_value() {
  # record_value FILE KEY: the text after KEY= on its first line, or empty.
  local line
  line="$(grep -m1 "^${2}=" "${1}" || true)"
  line="${line%$'\r'}"
  printf '%s' "${line#*=}"
}

require_verification_record() {
  # require_verification_record FILE REVISION DIGEST
  local record="${1}" check value
  [ -f "${record}" ] ||
    fail "verification record '${record:-empty}' not found; copy deploy/verification.example after the private checks"
  [ "$(record_value "${record}" revision)" = "${2}" ] ||
    fail "the verification record is not for revision ${2}"
  [ "$(record_value "${record}" digest)" = "${3}" ] ||
    fail "the verification record is not for image ${3}"
  for check in ${VERIFICATION_CHECKS}; do
    value="$(record_value "${record}" "${check}")"
    value="${value#"${value%%[![:space:]]*}"}"
    case "${value,,}" in
      "" | true | yes | y | ok | done | pass | passed | 1 | x)
        fail "verification record: write what ${check} showed (result, account, time), not '${value:-empty}'"
        ;;
    esac
  done
}
