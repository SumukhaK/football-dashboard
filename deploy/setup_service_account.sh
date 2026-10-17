#!/usr/bin/env bash
#
# Create the console's read-only service account and grant it exactly the three
# read roles it needs. Safe to run twice: it checks before it creates, and
# re-applying an existing binding is a no-op.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GCP_PROJECT_ID=""
REGION=""
# shellcheck source=/dev/null
source "${script_dir}/.env.deploy"

: "${GCP_PROJECT_ID:?set GCP_PROJECT_ID in deploy/.env.deploy}"
: "${REGION:?set REGION in deploy/.env.deploy}"

SERVICE_ACCOUNT="football-dashboard-reader"
ACCOUNT_EMAIL="${SERVICE_ACCOUNT}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
MEMBER="serviceAccount:${ACCOUNT_EMAIL}"

if ! gcloud iam service-accounts describe "${ACCOUNT_EMAIL}" \
  --project "${GCP_PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SERVICE_ACCOUNT}" \
    --project "${GCP_PROJECT_ID}" \
    --display-name "Football dashboard console, read only"
fi

# Exactly these three, all read-only. Never roles/viewer, editor or a writer.
gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member "${MEMBER}" \
  --role=roles/logging.viewer \
  --condition=None >/dev/null

gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member "${MEMBER}" \
  --role=roles/cloudtrace.user \
  --condition=None >/dev/null

gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member "${MEMBER}" \
  --role=roles/errorreporting.viewer \
  --condition=None >/dev/null

echo "Granted logging.viewer, cloudtrace.user and errorreporting.viewer to"
echo "${ACCOUNT_EMAIL} in ${GCP_PROJECT_ID} (${REGION})."
