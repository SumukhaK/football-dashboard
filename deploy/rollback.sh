#!/usr/bin/env bash
#
# Roll the console back to a named, already-existing revision:
#   deploy/rollback.sh <revision>                  restore it privately
#   deploy/rollback.sh <revision> <sha256:digest>  restore a verified revision
#
# "latest" is refused: a rollback names the image whose behaviour was reviewed.
# Without a digest the target is unverified, whatever its settings say, so the
# public edge is closed and checked private *before* traffic moves, and stays
# closed. With a digest the target goes through the same checks as a
# promotion (its verification record, the reviewed image and the current,
# enabled key versions) and the transport is left as it was. A target pinned
# to retired key versions fails that check: redeploy the good code with the
# current keys instead of re-enabling old ones. Tags are retired afterwards,
# because a tag reaches a revision at 0% traffic.
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
require_location

REVISION="${1:-}"
DIGEST="${2:-}"
require_revision_name "${REVISION}" \
  "deploy/rollback.sh <revision> [sha256:digest]"

# Reading the target first also proves it exists: a failed read aborts here,
# before any traffic or policy change.
MODE="$(revision_auth_mode "${REVISION}")"
require_invoker_check

if [ -n "${DIGEST}" ]; then
  load_deploy_config
  require_digest "${DIGEST}"
  require_verification_record "${REVISION}" "${DIGEST}"
  verify_revision "${REVISION}" "${DIGEST}"
else
  echo "Revision ${REVISION} is unverified (AUTH_MODE=${MODE:-absent}); closing public transport first."
  close_transport
fi

gcloud run services update-traffic "${SERVICE_NAME}" \
  --project "${GCP_PROJECT_ID}" \
  --region "${REGION}" \
  --to-revisions="${REVISION}=100"

if [ -z "${DIGEST}" ]; then
  require_private
fi

retire_tags

echo
if [ -n "${DIGEST}" ]; then
  echo "Rolled back to verified revision ${REVISION} (${DIGEST}); transport was left as it was."
else
  echo "Rolled back to ${REVISION} (AUTH_MODE=${MODE:-absent})."
  echo "Transport is private: reach it with 'gcloud run services proxy'."
  echo "To serve it publicly again, verify it and run:"
  echo "  bash deploy/promote.sh ${REVISION} <sha256:digest>"
fi
