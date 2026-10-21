#!/usr/bin/env bash
#
# Promote one verified candidate: deploy/promote.sh <revision> <sha256:digest>.
#
# The revision and the immutable digest it was built from are both required;
# "latest" is refused. Before any traffic moves, the operator's verification
# record for exactly that revision and digest must exist, and the revision is
# read back and compared with deploy/.env.deploy: image, runtime account,
# settings, secret names and numeric versions. The service must be private
# while traffic moves. Tags are retired and read back, and only then, if
# DASHBOARD_TRANSPORT=app-auth was asked for, is the public edge opened.
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

REVISION="${1:-}"
DIGEST="${2:-}"
require_revision_name "${REVISION}" "deploy/promote.sh <revision> <sha256:digest>"
require_digest "${DIGEST}"

# The operator's record first: it needs no Google call, and without it there is
# nothing to promote.
require_verification_record "${REVISION}" "${DIGEST}"
verify_revision "${REVISION}" "${DIGEST}"
refuse_if_public "promoting ${REVISION}"

# By name, never "latest": the revision is the contract.
gcloud run services update-traffic "${SERVICE_NAME}" \
  --project "${GCP_PROJECT_ID}" \
  --region "${REGION}" \
  --to-revisions="${REVISION}=100"

# Tags reach revisions at 0% traffic. Retire every one of them, and read the
# map back, before any transport change.
retire_tags

if [ "${DASHBOARD_TRANSPORT}" = "app-auth" ]; then
  # Explicit opt-in, after the verified revision serves 100% privately: one
  # service-scoped allUsers binding, with the invoker IAM check left enabled.
  open_transport
  echo
  echo "Transport: app-auth (public edge, application owner sign-in enforced)."
else
  require_private
  echo
  echo "Transport: private (Cloud Run IAM; no public binding)."
fi

echo
echo "Revision ${REVISION} (${DIGEST}) is serving 100% of traffic."
echo "Open it as the owner with:"
echo "  gcloud run services proxy ${SERVICE_NAME} --project ${GCP_PROJECT_ID} --region ${REGION}"
