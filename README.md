# Football Dashboard Console

A read-only web console for observing the Football Intelligence backend's telemetry.

## How to run locally

```bash
uv sync --extra dev
uv run uvicorn app.main:app
```

Visit http://127.0.0.1:8000 to see the health check.

## How it relates to the main repo

This console reads telemetry emitted by the Football Intelligence backend (SumukhaK/football-intelligence-platform). It never writes to Google Cloud - it's read-only observability, with one opt-in exception: the invite page below writes one Firestore document per invite.

## Invites

An optional page at `/invites` makes invite codes for the app, the same way the backend's `manage_accounts invite` does. Enter an email and it shows an `XXXX-XXXX` code once, with a copy button and the expiry (7 days). It writes one document to the `{prefix}invites` Firestore collection (`staging_invites` by default), keyed by the lower-case email; a new invite for the same email replaces the old one. Only a SHA-256 of the code is stored.

It is off by default. It is meant for running locally as the project owner, after `gcloud auth application-default login`:

```bash
invites_enabled=true gcp_project_id=<project> uv run uvicorn app.main:app
```

Settings: `invites_enabled` (default `false`), `invite_collection_prefix` (default `staging_`), `invite_lifetime_days` (default `7`), and the existing `gcp_project_id`. When it is off the page and its nav link do not exist. The page rejects posts from other sites, is never cached, and never logs the email or the code.

## Crashes

The page at `/crashes` shows the Android app's crashes, non-fatals and ANRs from the Firebase Crashlytics BigQuery export: totals by type, then one row per issue (events, affected installs, first and last seen, app versions), newest first. Each issue links to `/crashes/{issue_id}` with its recent events (time, app version, device, Android version) and the blamed frame and top stack frames of the latest event. Installation ids are only ever counted, never shown. The window picker defaults to 7 days.

With the `fixture` source the page shows the sample week in `fixtures/crashlytics_events.json`. To read the real export locally, sign in as the project owner and point the console at the Firebase project:

```bash
gcloud auth application-default login
source=gcp gcp_project_id=<api project> CRASHLYTICS_PROJECT_ID=football-intelligent-platform uv run uvicorn app.main:app
```

Settings: `crashlytics_project_id` (default unset), `crashlytics_dataset` (default `firebase_crashlytics`), `crashlytics_table` (default `com_footballintelligence_app_stg_ANDROID`), `crashlytics_location` (default `US`) and `crashlytics_max_bytes_billed` (default 1 GB; BigQuery refuses any query that would bill more). With `source=gcp` and no `crashlytics_project_id`, the page and its nav link do not exist.

Crashlytics exports once a day (batch only, no streaming), so the newest crashes can take a day to appear. Until the first export runs the table does not exist, and the page says "No crash data exported yet" rather than showing an error. Every query is parameterised, filters on `event_timestamp` from the window start and is cached for `cache_ttl_seconds`. The page only reads.

For the D7 deploy, the console's reader service account will need `roles/bigquery.dataViewer` on the `firebase_crashlytics` dataset and `roles/bigquery.jobUser` on the `football-intelligent-platform` project. Nothing here grants them.

## Building it

Start with [guide/README.md](guide/README.md). Each step in `guide/` is one self-contained prompt for a coding agent, one branch and one pull request.

**Current step**: D1 - Scaffold (this branch)
