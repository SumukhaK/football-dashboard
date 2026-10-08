# Football Dashboard

A read-only observability console for the [Football Intelligence Platform](https://github.com/SumukhaK/football-intelligence-platform) backend. It shows the backend's requests, logs, traces, retries, fallbacks, errors and crashes on six pages: Overview, Errors, Requests, Assistant, Data and Access.

Status: planning. The application code does not exist yet. The `guide/` folder holds the step-by-step build prompts.

## How it fits together

- The backend (main repo) writes structured JSON logs and OpenTelemetry traces that follow `guide/telemetry-contract.md`.
- Google Cloud stores them (Cloud Logging, Cloud Trace, Error Reporting) and sends alerts (Cloud Monitoring). Alerts work even when this console is not running.
- This console only reads that data. It runs privately on Cloud Run with a read-only service account and scales to zero.
- For local development it runs against recorded sample data, with no cloud account needed.

## Stack

Python 3.12, FastAPI, Jinja2, HTMX, Apache ECharts, uv.

## Building it

Start with [guide/README.md](guide/README.md). Each step in `guide/` is one self-contained prompt for a coding agent, one branch and one pull request.
