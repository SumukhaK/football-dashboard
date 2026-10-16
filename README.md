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

## Building it

Start with [guide/README.md](guide/README.md). Each step in `guide/` is one self-contained prompt for a coding agent, one branch and one pull request.

**Current step**: D1 - Scaffold (this branch)
