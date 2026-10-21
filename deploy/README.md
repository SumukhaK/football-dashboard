# Deploy the console to Cloud Run

Cloud Run service in the same Google Cloud project as the API, reading telemetry
with the read-only `football-dashboard-reader` service account. Private IAM
transport is the default; explicit app-auth transport uses the application's
owner-only Google login. It scales to zero; storage/build costs can still apply.
The runtime has no telemetry write roles.

One-time setup, then deploy. Both steps need the owner's Google Cloud account.

## One-time setup

1. Copy the example environment and fill in the real values (never commit it):

   ```bash
   cp deploy/.env.deploy.example deploy/.env.deploy
   ```

   - `GCP_PROJECT_ID`: the project that runs the API.
   - `REGION`: the region the API runs in.
   - `API_SERVICE_NAME`: the Cloud Run service the console reads platform logs
     for. Staging is `football-api-staging`; the production service is planned as
     `football-api`.

2. Enable the existing Errors page's API in the target project:

   ```bash
   gcloud services enable clouderrorreporting.googleapis.com --project <project>
   ```

   This enables the API, not runtime access. A disabled API returns
   `SERVICE_DISABLED` even when the reader already has the correct role.

3. Create the reader account, define the narrow Trace role it needs, and grant it
   read access:

   ```bash
   bash deploy/setup_service_account.sh
   ```

   It creates (or updates) the project custom role
   `projects/<project>/roles/footballDashboardTraceReader`, whose only permission
   is `cloudtrace.traces.get` — the single Cloud Trace call the console makes
   (`get_trace` in `app/sources/gcp/trace_reader.py`). It grants
   `roles/logging.viewer`, `roles/errorreporting.viewer` and that custom role, and
   nothing else. It is safe to run twice.

   The role is defined in `deploy/trace-reader-role.yaml` instead of being chosen
   from the predefined set because no predefined role gives read-only Trace
   access: `roles/cloudtrace.user` also carries Trace task and scope mutations,
   which a reader must never hold. The script also **removes** an existing
   `roles/cloudtrace.user` binding from the reader, because binding the narrow
   role does not take the broad one away. It binds the narrow role first, so the
   removal cannot interrupt the console.

## Deploy

Use `GET /health` for hosted liveness; it returns only `{"status":"ok"}`.
The legacy `/healthz` alias remains available locally, but Cloud Run can intercept
it before the container. The IAM edge still applies in private transport.
See [ADR 002](../guide/adr/002-cloud-run-health-path.md).

```bash
bash deploy/deploy.sh
```

The script creates the Artifact Registry repository once if it is missing and
builds the image with Cloud Build. It captures that build's returned digest,
rather than rereading a `latest` tag another build could replace. Build logs
remain in Cloud Build at the URL printed by the CLI; `--suppress-logs` keeps
streamed logs out of the captured digest. It then deploys by **digest** (not by the
`latest` tag, so a later push cannot change a running revision) as a
**candidate**: `--no-traffic --tag candidate`, still private, with:

- `--no-allow-unauthenticated` and `--invoker-iam-check`, so the service URL is
  not public. Cloud Run has two independent ways to be public — an `allUsers`
  binding and a disabled invoker IAM check — so the script asks for both and
  then reads the service back to confirm neither is in effect before it reports
  success;
- `--service-account football-dashboard-reader@...`;
- `--min-instances 0 --max-instances 1 --cpu 1 --memory 512Mi --concurrency 20
  --timeout 60`;
- `SOURCE=gcp`, `GCP_PROJECT_ID`, `API_SERVICE_NAME` and `CACHE_TTL_SECONDS=60`,
  plus this console's owner sign-in settings (`AUTH_MODE=google`,
  `AUTH_PUBLIC_ORIGIN`, `AUTH_CALLBACK_URL`, `OWNER_EMAIL`, `GOOGLE_CLIENT_ID`,
  `INVITES_ENABLED=false`), updated with `--update-env-vars` rather than
  `--set-env-vars`, so settings the script does not name survive a later deploy;
- the client secret and both signing keys, bound by **numeric secret version**
  with `--update-secrets`, so a deploy is repeatable and a rollback can name
  exactly what it ran with.

`deploy.sh` stops there: it never moves traffic and never opens public access.
Before it builds anything it reads the service, and if the service exists and
is public (an `allUsers` binding, or the invoker check disabled) it refuses and
prints the command that closes the edge. A candidate's tag URL shares the
service's access policy, so on a public service it would be public before
anyone had looked at it; closing the edge is an outage for signed-in users, so
that decision is left to you. A service that does not exist yet has nothing to
expose and is created private.

After the deploy the candidate is read back: it must be `Ready`, run this
build's digest as the reader account, and carry this configuration's settings
and secret names and numeric versions, each still `ENABLED`. The candidate is
named from the completed build's unique ID with `--revision-suffix`; neither a
later service-wide `latestCreatedRevisionName` lookup nor a service result
changed during SDK polling can substitute another revision. Reads use the
Google SDK's `filter(...).extract(...).flatten()` projections; JMESPath-style
array predicates are not supported. Any failed read aborts. The script ends by
printing the candidate's revision and digest, how to reach it privately, and the
promotion command.

### Verify a candidate

Reach the unserved candidate through its tag while the service is private:

```bash
gcloud run services proxy football-dashboard --tag candidate --project <project> --region <region>
```

Then check, and write down what you saw (not just "yes"):

- `SIGNED_OUT_DENIED`: a signed-out browser gets the sign-in page on full pages;
- `PARTIAL_DENIED`: HTMX partials and detail routes return a denial with no data;
- `OWNER_ALLOWED`: the owner signs in and sees the console;
- `NON_OWNER_DENIED`: a second Google account is refused before any data is read;
- `PRIVACY_CHECKED`: D9's privacy checks, including no code, token, verifier or
  email in logs or rendered errors;
- `VERIFIED_BY` and `VERIFIED_AT`.

Copy `deploy/verification.example.env` to
`deploy/verification/<revision>.env` (gitignored, like `.env.deploy`) and fill in
`REVISION`, `DIGEST` and those keys. The scripts read it as data and never run
it. A record for another revision or digest, a missing check or a bare flag
such as `true` is refused. The record is your evidence; the script cannot check
that it is true, so never fill it in for checks you did not make.

### Promote

```bash
bash deploy/promote.sh <revision> <sha256:digest>
```

Both are required, and `latest` is refused. Before any traffic moves the script
needs the verification record for exactly that revision and digest, reads the
revision back against `deploy/.env.deploy` as above, and requires the service
to be private. It then pins 100% of traffic to the revision **by name**
(`--to-latest` is never used: a rollback leaves a persistent traffic pin, and
"latest" is a guess, not a revision), removes every traffic tag and reads the
map back. Any mismatch or failed read stops it before the public edge.

### Transport: private (default) or app-auth

`DASHBOARD_TRANSPORT` in `deploy/.env.deploy` decides how browsers reach the
console after promotion.

- `private` (the default) keeps the Cloud Run IAM edge. Reach it with the proxy
  below. The application's owner sign-in sits inside that edge.
- `app-auth` is the explicit opt-in that opens the public HTTP edge **because
  the application enforces the owner's Google sign-in**. `promote.sh` applies it
  only after the verified revision owns 100% of traffic and every traffic tag
  has been retired. It adds one **service-scoped** `allUsers`/`roles/run.invoker`
  binding for this dashboard and leaves the invoker IAM check enabled; it never
  touches project IAM and never disables the check. `deploy.sh` never opens it.

Any other value is refused before the image is built. If policy forbids the
public binding, keep `private` and use the proxy.

### Tags

The candidate tag is what makes an unserved revision reachable for the checks
above. After promotion `promote.sh` removes **every** traffic tag and reads the
service back to prove none remains: a tag reaches a revision at 0% traffic, so
a leftover tag is a URL that can bypass the intended boundary.

## Owner sign-in configuration

Fill these in `deploy/.env.deploy` (see `.env.deploy.example`); they are names
and numbers, never secret values:

- `AUTH_PUBLIC_ORIGIN`: the canonical `https://` origin, no path, query or
  fragment. The callback is derived as `<origin>/auth/callback` and must match
  the Web OAuth client registration exactly (including port and trailing
  slash). A mismatch is fixed in the client registration, never with a
  wildcard or a `Host`-derived URL.
- `GOOGLE_CLIENT_ID`: the Web client id, ending
  `.apps.googleusercontent.com`.
- `OWNER_EMAIL`: the one account allowed to sign in.
- `GOOGLE_CLIENT_SECRET_NAME`/`_VERSION`,
  `SESSION_SIGNING_KEY_NAME`/`_VERSION`,
  `OAUTH_SIGNING_KEY_NAME`/`_VERSION`: Secret Manager names and numeric
  versions. Add a new version rather than overwriting one.

The image refuses to start without the Google configuration; there is no
"auth off" switch in a hosted revision. Keep `INVITES_ENABLED=false`.

Before the first deploy, create/upload the three secrets privately using
[D9's operator setup](../guide/D9-owner-login.md#7-oauth-client-and-secret-setup-operator-runbook).
Use the same names and numeric versions as your ignored `.env.deploy`; the
guide's names are examples. Creating a secret does not grant the runtime account
access. Once authorized to provision cloud access, grant access on each of these
three secrets only, after creating the reader account:

```bash
source deploy/.env.deploy
READER="football-dashboard-reader@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
for secret in "$GOOGLE_CLIENT_SECRET_NAME" "$SESSION_SIGNING_KEY_NAME" "$OAUTH_SIGNING_KEY_NAME"; do
  gcloud secrets add-iam-policy-binding "$secret" --project "$GCP_PROJECT_ID" \
    --member="serviceAccount:$READER" --role=roles/secretmanager.secretAccessor
done
```

This changes the three secret policies, not project IAM, and does not print or
download secret values. Verify their numeric versions are enabled before deploy.

### Recovery and rotation

- **Google account**: changing the Google password, revoking consent or
  clearing cookies does not revoke an already-copied console cookie. Rotate the
  session key (signs everyone out), remove old reachable revisions and, if
  needed, restore private transport first.
- **Session key**: new version, set it in `.env.deploy`, deploy a candidate
  pinned to it, verify an old cookie is refused, record it, promote (which
  retires old tags), then disable the old version.
- **OAuth key**: same procedure; pending logins are cancelled. Never keep a
  compromised verification key as a fallback.
- **Google client secret**: rotate it in Google Auth Platform, upload the new
  version privately, bind a new revision, test a fresh login, then retire the
  old client secret. This affects new code exchanges, not existing sessions. Do
  not generate an OAuth client secret with the random application-key recipe.
- **Owner account**: account recovery is a Google flow. It does not rotate
  console keys; do both if the account was compromised.

## Open it

```bash
gcloud run services proxy football-dashboard --project <project> --region <region>
```

`gcloud run services proxy` runs a local proxy in front of the private service and
adds your identity, so an ordinary browser can open it at
<http://localhost:8080>. Use this for private transport and denial/readiness
checks. It does not make the configured canonical HTTPS callback reachable by
Google or move the browser's host-scoped session cookies to localhost. The full
hosted Google sign-in flow therefore remains a separate D9.6 launch check;
complete it at `AUTH_PUBLIC_ORIGIN` only after public transport is explicitly
authorized. Follow D9's separate local Web-client setup for local OAuth testing.

## Roll back

Roll back to a revision **by name**, never to `latest`:

```bash
gcloud run revisions list --service football-dashboard --project <project> --region <region>
bash deploy/rollback.sh football-dashboard-00007-abc
```

Without a digest the target is treated as unverified, whatever its settings
say: an `AUTH_MODE=google` setting is not a review. The script reads the target
(refusing an unreadable one), closes public transport and verifies the service
is private, and only then moves traffic. The restore stays private and tags are
retired afterwards. To serve it publicly again, verify and record it as above
and run `deploy/promote.sh` with its digest.

To restore a known good revision without closing the edge, name its digest:

```bash
bash deploy/rollback.sh football-dashboard-00007-abc sha256:<digest>
```

That target goes through the same checks as a promotion: its verification
record, the reviewed image, and the secret versions and settings currently in
`deploy/.env.deploy`, each still enabled. The transport is then left as it was.
A revision pinned to older key versions fails this check. Do not re-enable old
keys to restore it (that can revive stolen cookies): redeploy that commit with
`deploy.sh`, so it runs with the current versions, and promote the new
candidate.

A pinned traffic split is persistent, and later promotions replace it by name.

## Evidence checklist for a launch

Record, without credential values:

- commit, image digest, revision, date and the `DASHBOARD_TRANSPORT` used;
- origin and callback, and that they match the Web client registration;
- the numeric secret versions bound, and the per-secret read permission;
- policy readback: service-scoped bindings, invoker IAM check enabled;
- traffic/tag map before and after, with no old tagged URL reachable;
- owner sign-in accepted, and a separate signed-out and non-owner browser
  denied before any data is read;
- expiry, logout, back/forward and HTMX behaviour;
- a generic failure, not a public fallback, during a provider outage, and that
  its rendered error and captured log line carry no provider description,
  authorization code, verifier or token — never log provider request or
  response bodies while investigating. The adapter suppresses the provider
  exception in the ordinary traceback; if the log or trace pipeline captures
  exception internals (an APM integration), check that separately.

A successful image build, a merged guide or a 200 response is not evidence of
deployed owner login.

## Delete everything

```bash
gcloud run services delete football-dashboard --project <project> --region <region>
gcloud artifacts repositories delete football-dashboard \
  --project <project> --location <region>
gcloud iam service-accounts delete \
  football-dashboard-reader@<project>.iam.gserviceaccount.com --project <project>
gcloud iam roles delete footballDashboardTraceReader --project <project>
```

A deleted custom role stays soft-deleted for seven days before its id can be
reused; `gcloud iam roles undelete` brings it back.

The Cloud Build staging bucket (`gs://<project>_cloudbuild`) can be deleted too if
nothing else uses it.

## Cost

Every page view makes a few read API calls (Cloud Logging, Cloud Trace, Error
Reporting), and loading an uncached page costs a fraction of a cent in read
operations only. Minimum instances is 0, so an idle service bills nothing for
compute, but scaling to zero does **not** guarantee a zero bill: Artifact Registry
storage, Cloud Build minutes and other project resources can still incur charges.
Check the current Google Cloud pricing pages for your region and measure your own
usage; do not rely on this note. The project carries the main repository's budget
alert; this console adds no new paid service.

The crashes page needs BigQuery access on the Firebase project, which this deploy
does not grant and does not enable — see the repository README.
