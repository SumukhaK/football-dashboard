# ADR 006: compare API releases using shared bounded samples

## Status

Accepted, 21 October 2026, owner-authorized G6-G7 sequence.

## Context

Separate per-release scans could disagree with the combined Overview and multiply
provider reads. Rates and percentiles cannot be combined by averaging release rows.
Missing token/cost data must stay unreported, and API release is independent of
Android app version, Cloud Run revision and console version.

## Decision

All-mode Overview reuses the current request and counted-event samples and adds
one bounded assistant.answer read. A pure builder partitions those same samples
by exact recorded API release, retains unknown and includes pooled combined totals.
It reuses the existing failure/rate/nearest-rank percentile, token and INR helpers.
Reported-field coverage is explicit. Missing/unusable costs and tokens are not zero.
First/last observed covers only these compared samples, never deployment or lifetime.
Caps apply to each existing event-category query and partial numbers are labelled.
Discovery labels may have no compared samples; these remain visible as unobserved.

The catalogue is resolved once per HTTP request and reused by the picker and table,
even with TTL zero. There are no per-release provider scans. The worst all-mode
Overview budget becomes seven Logging reads plus one catalogue scan (54 seconds
under A2's conservative bounds); selected mode keeps its original six Logging reads.
Native table links select the exact row release and carry canonical period context.
Sort controls use stable semantic ties, missing metrics/unknown release last, with
identical native/full and HTMX URLs. Existing charts and privacy rules are reused.

## Consequences

No new dependency, provider export, database or deployment. Combined and per-release
samples reconcile, but partial samples cannot establish complete historical totals.
Browser acceptance, real retention and any longer-lived archive remain G7/operator
verification; no unobserved history is invented.
