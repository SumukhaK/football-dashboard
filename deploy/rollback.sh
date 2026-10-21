#!/usr/bin/env bash
#
# Roll the console back to a named, already-existing revision, privately.
#
# The revision is the argument; "latest" is refused. A restore point has not
# been through promote.sh's checks, and an AUTH_MODE=google setting does not
# prove it runs reviewed code with today's keys, so public transport is closed
# and verified private *before* traffic moves, and stays closed. Serving the
# restored revision publicly again goes through deploy/promote.sh, which refuses
# a revision pinned to retired key versions. Tags are retired afterwards,
# because a tag reaches a revision at 0% traffic.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${script_dir}/.."

GCP_PROJECT_ID=""
REGION=""
SERVICE_NAME="football-dashboard"
# shellcheck source=/dev/null
source "${script_dir}/.env.deploy"
# shellcheck source=/dev/null
source "${script_dir}/lib.sh"

: "${GCP_PROJECT_ID:?set GCP_PROJECT_ID in deploy/.env.deploy}"
: "${REGION:?set REGION in deploy/.env.deploy}"

REVISION="${1:-}"
[ -n "${REVISION}" ] || fail "usage: deploy/rollback.sh <revision>; never 'latest'"
require_revision_name "${REVISION}"

# Reading the target first also proves it exists: a failed read aborts here,
# before any traffic or policy change.
MODE="$(revision_auth_mode "${REVISION}")"
require_invoker_check

echo "Closing public transport before restoring ${REVISION}."
close_transport

gcloud run services update-traffic "${SERVICE_NAME}" \
  --project "${GCP_PROJECT_ID}" \
  --region "${REGION}" \
  --to-revisions="${REVISION}=100"

require_private
retire_tags

echo
echo "Rolled back to ${REVISION} (AUTH_MODE=${MODE:-absent}). Transport is private:"
echo "  gcloud run services proxy ${SERVICE_NAME} --project ${GCP_PROJECT_ID} --region ${REGION}"
echo "To serve it publicly, check it privately and run deploy/promote.sh with its"
echo "digest and a verification record. A revision pinned to retired key versions"
echo "is refused there: redeploy current code with deploy/deploy.sh instead."
