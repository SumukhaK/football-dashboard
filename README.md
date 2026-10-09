# Football Dashboard Console

A read-only web console for observing the Football Intelligence backend's telemetry.

## How to run locally

```bash
uv sync --extra dev
uv run uvicorn app.main:app
```

Visit http://127.0.0.1:8000 to see the health check.

## How it relates to the main repo

This console reads telemetry emitted by the Football Intelligence backend (SumukhaK/football-intelligence-platform). It never writes to Google Cloud - it's strictly read-only observability.

## Building it

Start with [guide/README.md](guide/README.md). Each step in `guide/` is one self-contained prompt for a coding agent, one branch and one pull request.

**Current step**: D1 - Scaffold (this branch)
