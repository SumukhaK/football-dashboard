# ADR 002 — Use /health for hosted liveness

**Status:** Accepted, 20 October 2026.

**Implementation: Done** — [PR #37](https://github.com/SumukhaK/football-dashboard/pull/37); `/health` verified in the actual Cloud Run deployment, as recorded in [D9.6](../D9.6-live-verification.md).

## Context

D9.6's private Cloud Run candidate returned Google's HTML 404 for `/healthz`,
without the application's security headers. `/login` reached the application.
[Cloud Run's reserved-path documentation](https://docs.cloud.google.com/run/docs/known-issues#reserved-url-paths)
recommends avoiding paths ending in `z`. Existing local callers use `/healthz`.

## Decision

Add `/health` as the hosted liveness path and retain `/healthz` as a compatibility
alias. Both use the existing handler and return only `{"status":"ok"}` without
reading telemetry. Add only the exact `/health` path to the guard's public
GET/HEAD exceptions; writes and similarly named paths remain protected.

## Consequences

Hosted checks use `/health`. Existing local checks continue to work. Both paths
receive the same no-store and security headers; neither reveals source,
configuration or contract details. Verify `/health` against the deployed image;
an offline test cannot prove that Cloud Run forwards a path.
