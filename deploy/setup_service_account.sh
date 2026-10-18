#!/usr/bin/env bash
#
# Put the console's read-only identity in place: create the reader account, define
# the narrow Trace role it needs, bind exactly the read roles, and take away the
# broad Trace role an earlier version of this script granted.
#
# Safe to run twice: every step checks first, and re-applying a binding is a no-op.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
role_file="${script_dir}/trace-reader-role.yaml"

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

# The Trace role is defined by permission, from the committed definition, because
# no predefined role gives read-only Trace access without mutation permissions.
if gcloud iam roles describe footballDashboardTraceReader \
  --project "${GCP_PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam roles update footballDashboardTraceReader \
    --project "${GCP_PROJECT_ID}" --file "${role_file}" >/dev/null
else
  gcloud iam roles create footballDashboardTraceReader \
    --project "${GCP_PROJECT_ID}" --file "${role_file}"
fi

# Exactly these, all read-only. Never roles/viewer, editor or a writer.
gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member "${MEMBER}" \
  --role=roles/logging.viewer \
  --condition=None >/dev/null

gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member "${MEMBER}" \
  --role=roles/errorreporting.viewer \
  --condition=None >/dev/null

gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member "${MEMBER}" \
  --role="projects/${GCP_PROJECT_ID}/roles/footballDashboardTraceReader" \
  --condition=None >/dev/null

# Migration: the broad Trace role was granted before the custom role existed, and
# binding the custom role does not take it away. The narrow role is already bound
# above, so removing this one cannot interrupt the console.
if gcloud projects get-iam-policy "${GCP_PROJECT_ID}" \
  --flatten="bindings[].members" \
  --filter="bindings.role=roles/cloudtrace.user AND bindings.members=${MEMBER}" \
  --format="value(bindings.role)" | grep -q .; then
  gcloud projects remove-iam-policy-binding "${GCP_PROJECT_ID}" \
    --member "${MEMBER}" \
    --role=roles/cloudtrace.user \
    --condition=None >/dev/null
  echo "Removed the broad role roles/cloudtrace.user from ${ACCOUNT_EMAIL}."
fi

echo "Granted logging.viewer, errorreporting.viewer and the custom Trace reader role"
echo "(projects/${GCP_PROJECT_ID}/roles/footballDashboardTraceReader) to"
echo "${ACCOUNT_EMAIL} in ${GCP_PROJECT_ID} (${REGION})."
