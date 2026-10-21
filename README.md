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
| Overview | `/` | Component health, the headline numbers (requests, error rate, p95 latency and app crashes) against the previous window, traffic/latency charts, slowest routes and an all-mode comparison by API release. |
| Requests | `/requests` | The request list and retained Logs tab, filters and request detail with its own API release, revision and span waterfall. |
| Errors | `/errors` | Crashes grouped by exception, handled errors grouped by error code, Cloud Run platform events (out of memory, container exits, instance starts) and degraded components. |
| Assistant | `/assistant` | How the assistant answers: answer paths and latency, tool calls, model calls, fallbacks, and tokens and cost. |
| Data | `/data` | Data freshness per competition, the daily refresh runs and downloads, and component reloads. |
| Access | `/access` | Sign-ins, lockouts and rate limiting. |
| Crashes | `/crashes` | The Android app's crashes, non-fatals and ANRs, read from the Crashlytics export. Off unless configured. |
| Invites | `/invites` | Makes an invite code for the app. Off by default, and the only page that writes anything. |
| Source | `/source` | Which telemetry source the console is reading, what that source can answer, and how the last read of a local log file went. Linked from the sidebar footer, not the main nav. |

Most pages share a time window picker (1 hour, 6 hours, 24 hours, 7 days), the
small numbers link to the filtered request list behind them, and the console
ships with a dark and a light theme. `GET /health` is the hosted health check;
`GET /healthz` remains a local compatibility alias because Cloud Run intercepts
some paths ending in `z` (see [ADR 002](guide/adr/002-cloud-run-health-path.md)). When the
source is a local log file, the sidebar footer adds a line counting the events it
read and links to `/source`.

All displayed dates, clocks and chart labels use India Standard Time (IST).
Telemetry, query windows and pagination cursors retain their canonical UTC values;
relative ages and durations are unchanged.

## API releases and historical periods

Backend pages share an API release selector: all (including unknown), an exact
recorded label, or unknown. Custom dates are entered in IST and carried in UTC
URLs through filters, navigation, refresh and detail return. Quick windows remain
1h/6h/24h/7d. Defaults allow 31 days per range and 365 days back; these settings
are query safety bounds, **not a promise of retained cloud history**.

All-mode Overview compares releases from the same bounded samples as its summary:
counts, pooled rates/latency, backend crashes, reported tokens/cost and observed
IST ranges. Unknown remains visible; partial, missing or failed history stays
explicit. Console version, API release, Cloud Run revision and Android app version
are separate identities. Android has its own version selector; API/mobile
correlation is not implemented. See the [G7 handoff](guide/G7-history-verification.md)
for supported sources, retention limits, offline evidence and pending browser checks.

## INR cost display

Reported provider costs appear as INR estimates on Assistant and in request
timelines and trace hover details. Set both optional environment settings:

```dotenv
inr_per_usd=<positive finite INR per USD>
inr_per_usd_as_of=<YYYY-MM-DD>
```

Replace these placeholders with an operator-chosen rate and its as-of date.
There is no built-in market rate, live exchange-rate request or automatic update.
The displayed note identifies the rate/date and distinguishes the estimate from
an actual cloud billing invoice. For a hosted revision, supply both as runtime
environment variables on the candidate, then verify the displayed note before
promotion; adding them only to `deploy/.env.deploy` does not configure the app.

If either setting is missing, reported costs show “INR conversion unavailable”.
An invalid supplied rate/date fails configuration validation. Unreported costs
stay unreported; zero remains zero. Sub-paisa amounts use four decimal places,
or a “less than 0.0001 INR” label for smaller positive amounts. Stored telemetry,
the `cost_usd` contract and USD aggregation are unchanged.

## Run it locally

```bash
uv sync --extra dev
uv run python -m app.demo
```

Then open <http://127.0.0.1:8000>. Every page carries a **Sample data — local
demonstration** notice. The launcher binds `127.0.0.1` itself (its only options
are `--host`, which must be `127.0.0.1` or `::1`, and `--port`) and tells the
console which address it bound;
the demonstration then refuses any connection whose server or client address is
not loopback, whatever the Host or forwarded headers say. A wildcard or LAN
host is refused, and `auth_mode=fixture uvicorn app.main:app` exits at startup,
because uvicorn cannot tell the console what it bound. The default source is `fixture`, which reads
the sample telemetry in [fixtures/](fixtures/README.md): one day of the
backend's logs, written to the values the contract allows, so every page has
something to show without any Google Cloud setup.

`auth_mode` is the console's own sign-in. Its default is `google`, which needs
the owner's Google client and signing keys below and refuses to start without
them; `fixture` is the explicit loopback demonstration used here, and it refuses
a real source, an enabled invite page or a hosted revision.

## Read real telemetry

The default `fixture` source needs no setup. The other two read live data: `gcp`
reads Google Cloud, and `local` reads the backend's own log file on this machine.

Both run behind the owner sign-in: the sample-data demonstration refuses a real
source, and Google mode refuses to start without its settings. Set up a local
Google profile once:

1. Create a development **Web application** OAuth client whose redirect URI is
   exactly `http://127.0.0.1:8080/auth/callback` (see
   [D9](guide/D9-owner-login.md)).
2. Copy [.env.example](.env.example) to `.env`, keep `auth_mode=google`, and
   uncomment and fill in all six Google settings, with
   `auth_public_origin=http://127.0.0.1:8080`,
   `auth_callback_url=http://127.0.0.1:8080/auth/callback` and two independent
   random signing keys.

Each command below loads that profile with `--env-file .env`; values set on the
command line win over the file. Open <http://127.0.0.1:8080/login> and sign in
as the owner.

### From Google Cloud

```bash
gcloud auth application-default login
source=gcp gcp_project_id=<project> uv run --env-file .env uvicorn app.main:app --host 127.0.0.1 --port 8080
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
mkdir -p ../logs
LOG_FORMAT=json uv run uvicorn backend.app.main:app 2>&1 | tee ../logs/api.jsonl
```

```powershell
# Windows PowerShell
New-Item -ItemType Directory -Path ..\logs -Force | Out-Null
$env:LOG_FORMAT="json"; uv run uvicorn backend.app.main:app 2>&1 | Tee-Object -FilePath ..\logs\api.jsonl -Append
```

In a second terminal, from the dashboard checkout, point the console at that
file. Replace the quoted example with its absolute path:

```bash
# macOS or Linux
source=local local_log_path="/full/path/to/api.jsonl" uv run --env-file .env uvicorn app.main:app --host 127.0.0.1 --port 8080
```

```powershell
# Windows PowerShell
$env:source="local"; $env:local_log_path="C:\full\path\to\api.jsonl"; uv run --env-file .env uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Then sign in at <http://127.0.0.1:8080/login>. The backend keeps port 8000.

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

Settings come from the environment. If you copy
[.env.example](.env.example) to `.env` and edit it, load it explicitly when
starting the console; merely creating the file does not load its settings:

```bash
uv run --env-file .env uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Two sign-in profiles decide how the console is configured. A **fixture** profile
sets `auth_mode=fixture` and leaves the six Google settings unset; that is the
local demonstration, and it starts only through `uv run --env-file .env python
-m app.demo`. A **Google** profile supplies all six —
`google_client_id`, `google_client_secret`, `auth_public_origin`,
`auth_callback_url` and both signing keys — and the console refuses to start if
any of them is missing. The example file keeps those six assignments commented
out on purpose: loading the file makes every line a provided value, so an empty
assignment would be something to validate rather than a setting left unset.

The example file lists the common settings. The ones you are most likely
to touch are `source`, `gcp_project_id`, `api_service_name` (the Cloud Run
service whose platform logs to read, `football-api` by default),
`local_log_path` and `local_log_max_bytes` (both `source=local` only), and
`default_window_hours` (`24` by default).

Every setting, with its default (`app/config.py` is the source of truth):

| Setting | Default | What it does |
| --- | --- | --- |
| `source` | `fixture` | `fixture`, `local` or `gcp`. |
| `fixture_dir` | `fixtures` | Sample files for the `fixture` source, relative to the repo. |
| `local_log_path`, `local_log_max_bytes` | unset, 50 MB | The backend log file for `source=local`, and how much of its tail is read (1 MB to 1 GB). |
| `gcp_project_id`, `api_service_name` | unset, `football-api` | The API's project (required for `gcp`) and its Cloud Run service. |
| `gcp_page_size` | `1000` | Cloud Logging page size (1 to 1000). |
| `cache_ttl_seconds` | `60` | How long a read is reused (0 to 600; 0 turns the cache off). |
| `default_window_hours`, `data_default_window_hours`, `access_default_window_hours` | `24`, `168`, `24` | Each page's starting window; must be 1, 6, 24 or 168. |
| `history_max_range_days`, `history_max_lookback_days` | `31`, `365` | Safety bounds on a custom period (not a promise of retained history). |
| `tile_lookback_hours`, `freshness_warn_hours`, `freshness_error_hours` | `168`, `36`, `72` | Overview tile lookback and data-freshness thresholds. |
| `platform_patterns` | built in | Cloud Run system-log substrings and the platform event each means. |
| `inr_per_usd`, `inr_per_usd_as_of` | unset | The INR estimate's rate and its date; without both, costs show "INR conversion unavailable". |
| `auth_mode` | `google` | `google`, or `fixture` for the loopback demonstration only. |
| `owner_email` | the owner's address | The one Google account the console serves. |
| `google_client_id`, `google_client_secret`, `auth_public_origin`, `auth_callback_url`, `session_signing_key`, `oauth_signing_key` | unset | The six Google-mode settings; all are required in Google mode. |
| `session_max_age_seconds`, `oauth_transaction_max_age_seconds` | `3600`, `300` | Session and pending sign-in lifetimes (these are also the maximums). |
| `invites_enabled`, `invite_collection_prefix`, `invite_lifetime_days` | `false`, `staging_`, `7` | The optional invite page. |
| `crashlytics_project_id`, `crashlytics_dataset`, `crashlytics_table`, `crashlytics_location`, `crashlytics_max_bytes_billed` | see [Crashes](#crashes) | The optional crashes page on `gcp`. |
| `crash_app_package` | `com.footballintelligence.app` | Which stack frames count as the app's own code. |
| `K_REVISION` | set by Cloud Run | Marks a hosted revision; refuses fixture mode and requires an https origin. |

## Optional pages

Both of these are off until you ask for them.

### Invites

An optional page at `/invites` makes invite codes for the app, the same way the
backend's `manage_accounts invite` does. Enter an email and it shows an
`XXXX-XXXX` code once, with a copy button and the expiry (7 days). It writes one
document to the `{prefix}invites` Firestore collection (`staging_invites` by
default), keyed by the lower-case email; a new invite for the same email
replaces the old one. Only a SHA-256 of the code is stored.

It is meant for running locally as the project owner, with the Google profile
from [Read real telemetry](#read-real-telemetry), after
`gcloud auth application-default login`:

```bash
invites_enabled=true gcp_project_id=<project> uv run --env-file .env uvicorn app.main:app --host 127.0.0.1 --port 8080
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
`fixtures/crashlytics_events.json`. To read the real export locally, use the
Google profile from [Read real telemetry](#read-real-telemetry), sign in to
`gcloud` as the project owner and point the console at the Firebase project:

```bash
gcloud auth application-default login
source=gcp gcp_project_id=<api project> CRASHLYTICS_PROJECT_ID=football-intelligent-platform uv run --env-file .env uvicorn app.main:app --host 127.0.0.1 --port 8080
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
bash deploy/deploy.sh                          # an unserved, private candidate
# check the candidate privately and record what you saw, then:
bash deploy/promote.sh <revision> <sha256:digest>
gcloud run services proxy football-dashboard --project <project> --region <region>
```

`deploy.sh` never serves its candidate or opens public access; `promote.sh` does
that only for a revision whose checks are recorded and whose image, settings
and key versions match the configuration. [deploy/README.md](deploy/README.md)
covers the setup, the deploy, verifying and promoting a candidate, rolling back
and deleting everything.

The reader account is granted `roles/logging.viewer`,
`roles/errorreporting.viewer` and the custom role `footballDashboardTraceReader`,
whose only permission is `cloudtrace.traces.get`, the single Cloud Trace call the
console makes. The role is defined by permission because no predefined role gives
read-only Trace access: `roles/cloudtrace.user` also allows Trace mutations. The
account is never granted a write role, an editor or a project viewer role.

Reading the real Crashlytics export needs two more roles on the Firebase
project: `roles/bigquery.dataViewer` on the `firebase_crashlytics` dataset and
`roles/bigquery.jobUser`. The deploy does not grant them.

## Access control

The console implements owner-only Google sign-in, signed sessions and a
default-deny guard covering pages, HTMX partials, details and writes. Google
mode is the default and refuses startup without the client, canonical origin
and independent signing keys. Only the verified owner account is accepted.

Locally, the sample-data demonstration (`auth_mode=fixture`, started with
`uv run python -m app.demo`) has no sign-in, so it serves only loopback
connections on a loopback bind and labels every page as sample data.

Cloud Run transport remains private by default. Explicit `app-auth` mode opens
the service's HTTP edge only after a guarded revision is verified and old
traffic tags are removed. Hosted invite writes remain disabled. See
[the D9 implementation and operator guide](guide/D9-owner-login.md),
[the live-verification record](guide/D9.6-live-verification.md), and
[guide/adr/001-owner-google-login.md](guide/adr/001-owner-google-login.md)
for the decision and its stateless-session limits.

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

Steps D1–D8, the optional local-log source (D2b), D7's redeploy follow-up and
D9.1–D9.5 are implemented. D9.6 records real deployment and Google sign-in
checks in [the live-verification record](guide/D9.6-live-verification.md).
Code, CI and deployed evidence are tracked separately.

The follow-up queue is [guide/testing-gaps.md](guide/testing-gaps.md). Groups
A (bounded Google reads), B (malformed log entries), C (verified promotion),
D (the loopback-only demonstration), F (IST and INR), G1–G7 (API releases,
comparison and history, with browser acceptance), H1–H4 (the 21 October audit)
and the offline-test fix are done. Still open: E1's guide reconciliation and the
operator follow-ups (live evidence and settings, not missing pages).

## Repository layout

- `app/` - the FastAPI app: routers, page services, telemetry sources, templates and static assets.
- `contract/` - the telemetry contract the app loads at startup.
- `deploy/` - the Cloud Run deploy, promote and rollback scripts and the runbook.
- `Dockerfile` - the container image Cloud Run runs.
- `.github/workflows/` - CI: lint, format, types, tests, image build and ShellCheck.
- `fixtures/` - one day of sample telemetry for the `fixture` source.
- `guide/` - the build guide: the telemetry contract and one prompt per step.
- `scripts/` - the generator that writes `fixtures/`.
- `tests/` - the test suite.

## Owner access

Open the configured hosted `/login`, choose **Continue with Google**, and use
`sumukh.aithal@gmail.com`. Other Google accounts are denied. There is no
dashboard password. Sessions expire after one hour; signing-key rotation signs
out existing sessions. Use **Sign out** to clear this browser's session.

For local sample data, use the explicit loopback fixture profile above. Real
local Google testing requires a separate Web client and exact loopback callback;
see [D9](guide/D9-owner-login.md). Keep unverified deployments behind IAM/proxy.
