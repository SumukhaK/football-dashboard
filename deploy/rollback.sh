#!/usr/bin/env bash
#
# Roll the console back to a named, already-existing revision.
#
# The revision is the argument. "latest" is refused: the point of a rollback is
# to name the image whose behaviour was already reviewed. If that image predates
# owner sign-in, public transport is closed and verified private *before* traffic
# moves, so a pre-auth revision is never exposed. Tags are retired afterwards,
# because a tag reaches a revision at 0% traffic.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${script_dir}/.."

GCP_PROJECT_ID=""
REGION=""
SERVICE_NAME="football-dashboard"
# shellcheck source=/dev/null
source "${script_dir}/.env.deploy"
# shellcheck source=deploy/lib.sh
source "${script_dir}/lib.sh"

: "${GCP_PROJECT_ID:?set GCP_PROJECT_ID in deploy/.env.deploy}"
: "${REGION:?set REGION in deploy/.env.deploy}"

REVISION="${1:-}"
case "${REVISION}" in
  "")
    fail "usage: deploy/rollback.sh <revision>; never 'latest'"
    ;;
  latest | LATEST | latest-*)
    fail "refusing to roll back to '${REVISION}': name the revision to restore"
    ;;
  *[!a-z0-9-]*)
    fail "'${REVISION}' is not a Cloud Run revision name"
    ;;
esac

# Reading the target first also proves it exists: a failed read aborts here,
# before any traffic or policy change.
MODE="$(revision_auth_mode "${REVISION}")"
require_invoker_check

if [ "${MODE}" != "google" ]; then
  # The target predates owner sign-in. Close the public edge first and verify
  # it, then restore traffic privately.
  echo "Revision ${REVISION} has no AUTH_MODE=google; closing public transport first."
  close_transport
fi

gcloud run services update-traffic "${SERVICE_NAME}" \
  --project "${GCP_PROJECT_ID}" \
  --region "${REGION}" \
  --to-revisions="${REVISION}=100"

if [ "${MODE}" != "google" ]; then
  require_private
fi

retire_tags

echo
echo "Rolled back to ${REVISION} (AUTH_MODE=${MODE:-absent})."
if [ "${MODE}" != "google" ]; then
  echo "Transport is private: reach it with 'gcloud run services proxy'."
else
  echo "The restore point is auth-enabled; transport was left as it was."
fi
