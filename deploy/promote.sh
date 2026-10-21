#!/usr/bin/env bash
#
# Serve a candidate that deploy.sh created, once it has been checked privately.
#
#   bash deploy/promote.sh <revision> <image-digest> <verification-record>
#
# Nothing is inferred. The operator names the revision and its immutable
# digest; the revision is read back and compared with deploy/.env.deploy (image,
# readiness, every setting the deploy owns, and the exact secret names and
# numeric versions); and the verification record must name the same revision
# and digest and say what each private check showed. Traffic then moves by
# revision name while the service is private and every tag is retired. The
# public app-auth edge opens only if DASHBOARD_TRANSPORT=app-auth asks for it,
# and only after all of that has held. Traffic never follows "latest".
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# No cd: the verification record path is the operator's, relative to where
# they ran the script.

# shellcheck source=/dev/null
source "${script_dir}/lib.sh"
# shellcheck source=/dev/null
source "${script_dir}/config.sh"

[ $# -eq 3 ] ||
  fail "usage: deploy/promote.sh <revision> <image-digest> <verification-record>"
REVISION="${1}"
DIGEST="${2}"
RECORD="${3}"
require_revision_name "${REVISION}"
require_digest "${DIGEST}"

# The record is checked before any call, so a missing one changes nothing.
require_verification_record "${RECORD}" "${REVISION}" "${DIGEST}"

# Promotion happens while private: a mismatch found below must not leave a
# public service pointing anywhere new.
refuse_if_public "the promotion"
verify_candidate "${REVISION}" "${DIGEST}"

gcloud run services update-traffic "${SERVICE_NAME}" \
  --project "${GCP_PROJECT_ID}" \
  --region "${REGION}" \
  --to-revisions="${REVISION}=100"

# Tags reach revisions at 0% traffic. Retire every one of them before any
# transport change, so no reachable URL points at an older image.
retire_tags
require_private

if [ "${DASHBOARD_TRANSPORT}" = "app-auth" ]; then
  # Explicit opt-in, after the verified revision serves 100%: one
  # service-scoped allUsers binding, with the invoker IAM check left enabled.
  open_transport
  echo
  echo "Transport: app-auth (public edge, application owner sign-in enforced)."
else
  echo
  echo "Transport: private (Cloud Run IAM; no public binding)."
fi

echo
echo "Revision ${REVISION} (${DIGEST}) is serving 100% of traffic."
echo "Open it as the owner with:"
echo "  gcloud run services proxy ${SERVICE_NAME} --project ${GCP_PROJECT_ID} --region ${REGION}"
