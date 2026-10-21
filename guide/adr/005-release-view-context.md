# ADR 005: release and historical view context

## Status

Accepted — 21 October 2026, owner-authorized G3–G5 sequence.

## Context

Release/time selection must survive full and HTMX navigation, filters and
detail panels. A shared app-state service must never retain one request's scope.
Historical URLs need exact, timezone-aware boundaries rather than rounded hours.

## Decision

Parse one immutable ViewScope per request before source reads. Quick hours stay
1/6/24/168; custom start/end are mutually exclusive, UTC in URLs and half-open.
Native selection forms accept explicitly labelled IST inputs and redirect only
to allowlisted telemetry paths, converting once to canonical UTC. Selection
changes discard pagination/open-panel cursors and preserve other valid filters.
Default guards allow a maximum 31-day custom span and a 365-day lookback; both
are configurable safety bounds, never evidence of a provider's retention.
Future/reversed/naive/ambiguous/duplicate scope inputs fail 422 rather than widen.

Discovery reuses G2's bounded cached protocol, retains absent selected releases,
and distinguishes incomplete results from source failure. SemVer 2.0.0 labels
sort by numeric core/prerelease precedence descending, ignoring build metadata
for precedence with lexical ties. Other exact recorded labels follow in lexical
order; unknown is last. Prefixes are never stripped or identities normalized.

Internal rendered URLs explicitly merge the active scope. Forms carry hidden
scope fields; quick-window controls explicitly replace custom ranges. No scope
is added to auth, writes, external trace links or static resources. Existing
HTMX privacy/history controls remain unchanged; loading hides stale results.

G3 delivers control/window plumbing and visibly labels combined backend data
until G4 binds per-request scoped source composition. G4 must not mutate shared
services or bypass release-bearing EventQuery/cache keys. G5 must separately
attribute provider groups/platform records and independent Android versions.

G5 uses exact retained crash logs when provider release/end-time attribution is
unproven. Revision mapping must read all-release evidence and keep conflicts or
incomplete metadata unattributed. Android uses an independent optional source
protocol and parameterized display-version predicate before caps; its cache keys
and controls never imply backend API correlation. Unsupported queries fail clearly.

## Consequences

No dependency or paid export. Native forms and existing HTMX/CSS remain usable.
An old release URL remains selected even without observations. Missing retained
data cannot be reconstructed. Whole-page deadlines remain A2; provider-specific
attribution and UI comparison remain separate G5/G6 acceptance.

Ordering reference: [SemVer 2.0.0](https://semver.org/spec/v2.0.0.html#spec-item-11).
