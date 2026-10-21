# ADR 004: bounded source-wide release discovery

## Status

Accepted — 21 October 2026, the owner's G2c requirement.

## Context

Release predicates must run in Google before the row cap. Logging string
equality folds case, whereas recorded identity does not. A selector also needs
observed releases without claiming that a capped scan is a complete catalogue.
The installed high-level list_entries API has no RPC timeout argument.

## Decision

- Use escaped, anchored case-sensitive Logging regexes for exact candidates.
  Logging also compares array elements, so candidate predicates cannot enforce
  the full scalar-type rule. Unknown candidates use the JSON payload scope;
  strict local matching follows ADR 003 before the final selected-row limit.
  Contract validation keeps missing required fields invalid. Bounded refill
  prevents scalar/array false positives consuming a selected release's page.
- Add an optional ReleaseDiscovery protocol separate from TelemetrySource,
  like LocalLogStats, and a frozen ReleaseCatalogue with versions,
  has_unknown and truncated. Discovery is source-wide within an explicit
  window, independent of the active release selection. No selector is enabled.
- Reuse the existing TTL/LRU cache. EventQuery already includes release in
  its hash; catalogue keys include their window. Failures remain uncached.
- Fixture/local catalogues reuse bounded existing snapshots, at most 5,000
  returned events, retaining local byte-tail and invalid-record incompleteness.
  No extra file scan or external API is introduced for them.
- Google catalogue scans use the installed LoggingServiceV2Client through a
  small adapter. Each explicit call consumes only its already-fetched first
  page: no implicit pager iteration. Cap at 5,000 raw rows and five pages;
  pass retry=None and the remaining five-second scan budget as each RPC timeout.
  Row/page/time limits and skipped invalid records produce truncated metadata.
  Reuse this scan for selected-release event reads; if a bounded candidate scan
  cannot fill a requested page, close its timestamp tie boundary or prove source exhaustion, fail unavailable
  instead of silently reporting no data. Existing all-release event reads keep
  their adapter; budgets across multiple request-ID chunks remain A2.
  Provider failures use the existing source-error mapping, never empty success.
- Service/project/window restrictions and contract validation apply before
  building catalogue labels. SDK diagnostics never include raw records.

## Consequences

No dependency, paid export, broad scan or UI change. Source-only fakes need not
pretend to support discovery. Unsupported discovery fails explicitly.
Catalogue RPC scanning is bounded; client/credential initialization and total
page budgets remain A2. Existing event/Trace/Error Reporting/BigQuery deadline
policies are not changed or described as fixed by G2c.

References: [Logging query semantics](https://docs.cloud.google.com/logging/docs/view/logging-query-language#regular-expressions)
and the pinned SDK signatures inspected offline. Regex matching is case
sensitive; string equality is not.
