# Football Dashboard Console

A read-only web console for watching the Football Intelligence backend: what it
serves, how fast, what fails, and what the assistant does behind each answer.

It shows telemetry the backend already sends to Google Cloud. It only reads,
with one opt-in exception: the invite page writes a single Firestore document
per invite. Nothing else the console does changes any data or state.

You can run it on your own machine without a Google Cloud account, against a day
of sample data or against the backend's own log file. It is Python 3.12 and
FastAPI with server-rendered Jinja templates, htmx for partial page updates and
ECharts for the charts, managed with [uv](https://docs.astral.sh/uv/).

## What it shows

| Page | Path | What it shows |
| --- | --- | --- |
| Overview | `/` | Component health, the headline numbers (requests, error rate, p95 latency and app crashes) against the previous window, traffic and latency charts, and the routes with the worst p95. |
| Requests | `/requests` | The request list, filtered by route, status, event, method or component, and one request's detail page with the waterfall of its spans. |
| Errors | `/errors` | Crashes grouped by exception, handled errors grouped by error code, Cloud Run platform events (out of memory, container exits, instance starts) and degraded components. |
| Assistant | `/assistant` | How the assistant answers: answer paths and latency, tool calls, model calls, fallbacks, and tokens and cost. |
| Data | `/data` | Data freshness per competition, the daily refresh runs and downloads, and component reloads. |
| Access | `/access` | Sign-ins, lockouts and rate limiting. |
| Crashes | `/crashes` | The Android app's crashes, non-fatals and ANRs, read from the Crashlytics export. Off unless configured. |
| Invites | `/invites` | Makes an invite code for the app. Off by default, and the only page that writes anything. |
| Source | `/source` | Which telemetry source the console is reading, what that source can answer, and how the last read of a local log file went. Linked from the sidebar footer, not the main nav. |

Most pages share a time window picker (1 hour, 6 hours, 24 hours, 7 days), the
small numbers link to the filtered request list behind them, and the console
ships with a dark and a light theme. `GET /healthz` is the health check. When the
source is a local log file, the sidebar footer adds a line counting the events it
read and links to `/source`.

## Run it locally

```bash
uv sync --extra dev
uv run uvicorn app.main:app
```

Then open <http://127.0.0.1:8000>. The default source is `fixture`, which reads
the sample telemetry in [fixtures/](fixtures/README.md): one day of the
backend's logs, written to the values the contract allows, so every page has
something to show without any Google Cloud setup.

## Read real telemetry

The default `fixture` source needs no setup. The other two read live data: `gcp`
reads Google Cloud, and `local` reads the backend's own log file on this machine.

### From Google Cloud

```bash
gcloud auth application-default login
source=gcp gcp_project_id=<project> uv run uvicorn app.main:app
```

The readers are built on the first query and use the credentials they find:
your `gcloud` login locally, or the console's read-only service account on Cloud
Run. Reads are cached for `cache_ttl_seconds` (60 seconds by default) and every
query is bounded by the chosen window and a page size.

### From the backend's own log file

Run the backend with `LOG_FORMAT=json` and save what it prints (from the
backend's `ai/` folder):

```bash
# macOS or Linux
LOG_FORMAT=json uv run uvicorn backend.app.main:app 2>&1 | tee ../logs/api.jsonl
```

```powershell
# Windows PowerShell
$env:LOG_FORMAT="json"; uv run uvicorn backend.app.main:app 2>&1 | Tee-Object -FilePath ..\logs\api.jsonl -Append
```

Then point the console at that file:

```bash
source=local local_log_path=<full path to api.jsonl> uv run uvicorn app.main:app
```

`local_log_path` is required when `source` is `local`. Only the last
`local_log_max_bytes` of the file is read (1 MB to 1 GB, 50 MB by default), so a
long-running log never slows a page down, and lines that are not JSON, or do not
match the contract, are counted and shown rather than dropped silently.

A log file cannot answer everything a cloud source can. It has no traces and no
Cloud Run platform logs, and its error groups are grouped from the `app.crash`
lines in the file, which the page says plainly rather than passing them off as
Google Cloud Error Reporting. Pages say what they cannot show instead of
rendering an empty section, and `/source` lists exactly what the current source
can answer.

### Settings

Settings come from the environment or a `.env` file, and
[.env.example](.env.example) documents all of them. The ones you are most likely
to touch are `source`, `gcp_project_id`, `api_service_name` (the Cloud Run
service whose platform logs to read, `football-api` by default),
`local_log_path` and `local_log_max_bytes` (both `source=local` only), and
`default_window_hours` (`24` by default).

## Optional pages

Both of these are off until you ask for them.

### Invites

An optional page at `/invites` makes invite codes for the app, the same way the
backend's `manage_accounts invite` does. Enter an email and it shows an
`XXXX-XXXX` code once, with a copy button and the expiry (7 days). It writes one
document to the `{prefix}invites` Firestore collection (`staging_invites` by
default), keyed by the lower-case email; a new invite for the same email
replaces the old one. Only a SHA-256 of the code is stored.

It is meant for running locally as the project owner, after
`gcloud auth application-default login`:

```bash
invites_enabled=true gcp_project_id=<project> uv run uvicorn app.main:app
```

Settings: `invites_enabled` (default `false`), `invite_collection_prefix`
(default `staging_`), `invite_lifetime_days` (default `7`), and the existing
`gcp_project_id`. When it is off the page and its nav link do not exist. The
page rejects posts from other sites, is never cached, and never logs the email
or the code.

### Crashes

The page at `/crashes` shows the Android app's crashes, non-fatals and ANRs from
the Firebase Crashlytics BigQuery export: totals by type, then one row per issue
(events, affected installs, first and last seen, app versions), newest first.
Each issue links to `/crashes/{issue_id}` with its recent events (time, app
version, device, Android version) and the blamed frame and top stack frames of
the latest event. Installation ids are only ever counted, never shown. The
window picker defaults to 7 days.

With the `fixture` source the page shows the sample week in
`fixtures/crashlytics_events.json`. To read the real export locally, sign in as
the project owner and point the console at the Firebase project:

```bash
gcloud auth application-default login
source=gcp gcp_project_id=<api project> CRASHLYTICS_PROJECT_ID=football-intelligent-platform uv run uvicorn app.main:app
```

Settings: `crashlytics_project_id` (default unset), `crashlytics_dataset`
(default `firebase_crashlytics`), `crashlytics_table` (default
`com_footballintelligence_app_stg_ANDROID`), `crashlytics_location` (default
`US`) and `crashlytics_max_bytes_billed` (default 1 GB; BigQuery refuses any
query that would bill more). With `source=gcp` and no `crashlytics_project_id`,
the page and its nav link do not exist.

Crashlytics exports once a day (batch only, no streaming), so the newest crashes
can take a day to appear. Until the first export runs the table does not exist,
and the page says "No crash data exported yet" rather than showing an error. A
project or dataset that does not exist, or a dataset in a location other than
`crashlytics_location`, is a settings mistake instead: the page shows an error
naming the setting to check. Every query is parameterised, filters on
`event_timestamp` from the window start and is cached for `cache_ttl_seconds`.
The page only reads.

## Quality checks

```bash
uv run pytest          # the test suite; coverage must stay at or above 80%
uv run ruff check .
uv run black --check .
uv run mypy app tests
```

Continuous integration runs those four, builds the container image so a broken
Dockerfile fails the pull request rather than the deploy, and runs ShellCheck
over the deploy scripts.

## Deploy it privately

The console runs on Cloud Run as a private service: nobody reaches it without
Google Cloud authentication, and the service account behind it can only read. It
scales to zero when it is idle, which frees the idle compute; the image registry,
storage and other resources it uses can still cost a little.

```bash
bash deploy/setup_service_account.sh          # once
bash deploy/deploy.sh
gcloud run services proxy football-dashboard --project <project> --region <region>
```

[deploy/README.md](deploy/README.md) covers the setup, the deploy, rolling back
to the previous revision, and deleting everything.

The reader account is granted `roles/logging.viewer`,
`roles/errorreporting.viewer` and the custom role `footballDashboardTraceReader`,
whose only permission is `cloudtrace.traces.get`, the single Cloud Trace call the
console makes. The role is defined by permission because no predefined role gives
read-only Trace access: `roles/cloudtrace.user` also allows Trace mutations. The
account is never granted a write role, an editor or a project viewer role.

Reading the real Crashlytics export needs two more roles on the Firebase
project: `roles/bigquery.dataViewer` on the `firebase_crashlytics` dataset and
`roles/bigquery.jobUser`. The deploy does not grant them.

## Keep it private

The console has no login page yet, so the private Cloud Run boundary is what
keeps it safe. Keep it behind that boundary, or on `127.0.0.1` while developing,
and do not publish it: it reads real production telemetry, and the invite page
can write. Owner-only Google sign-in is planned as step D9. Until that exists
and has been verified, do not expose this console.

## Where the telemetry comes from

This console is the read-only counterpart of the Football Intelligence backend
(SumukhaK/football-intelligence-platform). The backend emits its logs, traces
and errors into Google Cloud, keeps invite codes in Firestore, and the Android
app's crashes are exported to BigQuery by Firebase Crashlytics.

The two sides agree on [guide/telemetry-contract.md](guide/telemetry-contract.md),
version 1.1.0. At startup the console loads the machine-readable copy in
[`contract/`](contract/telemetry-events.json) and relies only on the events and
fields it lists.

## Building it

Start with [guide/README.md](guide/README.md). Each step in `guide/` is one
self-contained prompt for a coding agent, one branch and one pull request.

Steps D1 to D8.2, the optional local-log source (D2b) and the redesigned
assistant page (D8.6) are merged. The requests page (D8.3) and the app crashes
page (D8.5) are in review, the errors page (D8.4) is the last redesign slice
still to build, and owner-only Google sign-in (D9) is a plan rather than
something the console has. The pull requests are the live record of what is
merged.

## Repository layout

- `app/` - the FastAPI app: routers, page services, telemetry sources, templates and static assets.
- `contract/` - the telemetry contract the app loads at startup.
- `deploy/` - the Cloud Run deploy scripts and notes.
- `fixtures/` - one day of sample telemetry for the `fixture` source.
- `guide/` - the build guide: the telemetry contract and one prompt per step.
- `scripts/` - the generator that writes `fixtures/`.
- `tests/` - the test suite.
