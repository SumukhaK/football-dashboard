# G4 backend release views and Requests Logs

Implemented in the owner-authorized G3-G5 sequence, 21 October 2026.
[ADR 005](adr/005-release-view-context.md) defines the request scope contract.

Each selected backend page builds a request-local service over ReleaseSource.
Every EventQuery receives the same immutable selection before the existing cache
and source filters, including comparison windows, component lookbacks and data
freshness. Shared application services are never mutated. All remains combined,
including unknown; a missing selected component/freshness stays missing.

Requests rows, panels, full details and timelines carry recorded API release
badges. Detail lookup verifies the request's own release in the selected period
before trace loading. Conflicting HTTP identities or capped identity reads are
unavailable; mismatch has a visible return/Close path. Only the HTTP request's
own trace ID is used; incidental log traces cannot become its waterfall.

Requests has a Logs tab for all retained backend events, including events without
a request. It reuses timeline attribute/cost presentation and HTML escaping.
Severity and event filters run at the source before limits. At most 5,000 matching
events are read, with 100 displayed per page and deterministic content ties.
Continuation fixes UTC boundaries and preserves API/severity/event filters.
This is a bounded retained sample, not a complete log export; late-arriving rows
can change it. A cap or source failure is explicit. No per-row RPC or raw export.

Console/source diagnostics and invite management remain Console-wide/Source-wide.
Provider crash groups/platform records remain explicitly source-wide in this
intermediate commit; G5 supplies attribution or explicit unavailability. Android
app versions remain independent. No deployment, live Google read, IAM or export.

Test-first evidence: all 24 full/partial page-read cases failed before scoping;
the mismatch and Logs-tab checks failed before implementation. Final focused
and CI evidence is recorded with the reviewed PR. Browser acceptance remains
pending under G7 because the controller is disabled; no visual pass is claimed.
