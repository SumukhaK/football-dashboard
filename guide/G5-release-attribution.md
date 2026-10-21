# G5 errors, platform attribution and independent Android versions

Implemented in the owner-authorized G3-G5 sequence, 21 October 2026.
[ADR 005](adr/005-release-view-context.md) defines the release/time boundary.

## Backend error counts

Selected releases, all custom historical periods and local/fixture views group
matching retained app.crash records after source-side release/time predicates.
They never reuse a combined Error Reporting group as selected counts. Groups
say they came from retained logs. A row cap, incomplete catalogue, truncated
local byte tail or skipped invalid telemetry makes exact groups unavailable,
not zero. Logs already deleted or never emitted cannot be reconstructed.

The installed ErrorsReader uses rolling QueryTimeRange periods without a custom
end. No verified evidence equates ServiceContextFilter.version with API release.
Therefore no version filter is invented. Only current/all GCP views keep provider
rolling groups, explicitly labelled Source-wide and not exact historical counts.
A handled application error is not promoted into a retained app.crash group.

## Platform records

Revision mapping reads all-release retained telemetry in the same period, bounded
to 5,000 events and checked against discovery/read completeness. Exactly one
known API label for a revision permits attribution. Multiple revisions may map
to one release. Unknown labels, conflicts, missing mappings and incomplete or
failed metadata remain Unattributed; names and deployment times are never guesses.

All mode retains every platform event. A known selection shows matching mapped
events plus clearly labelled source-wide Unattributed records; unknown selection
shows the unattributed records. Each unknown row explains the evidence limit.
Attribution failure does not discard an independently available platform record.
Source-side platform failures remain unavailable, not an empty healthy result.

## Android app versions

Android has its own native version picker in issue lists and details. The API
picker is retained for navigation and does not filter Android exports. Exact
Android display-version predicates run before row limits and service grouping;
unknown means null/empty/reserved unknown export display version. Values are
bound as BigQuery parameters, with unchanged UTC predicates, selected columns,
read deadlines and maximum_bytes_billed. No paid export is activated.

An optional VersionedCrashSource protocol keeps existing all-version adapters
compatible. Unsupported selected queries explicitly fail instead of reading all.
Fixture, BigQuery and cached adapters implement list/issue variants. Cache keys
include Android version, issue when present, period and limit; errors are not cached.
Discovery reads at most 5,000 independent Android events, reports incompleteness
or failure, and retains absent selected labels. No complete release catalogue is
inferred from a capped page. Counts/details at the cap are partial; an unseen
issue under the cap is unavailable rather than declared absent. Navigation,
type chips, panels/Close, full details and custom ranges preserve Android scope.
An unknown full issue returns a 404 page with selection and Back; HTMX unknown
panels still swap a visible Close path instead of stranding the previous panel.

**Pending coordinated task:** API-attributed Android crashes need separately
approved mobile instrumentation, export/contract fields and mixed API/mobile
version validation. No such correlation is currently recorded or fabricated.
Actual export activation and retention verification are separate operator
work; browser acceptance passed under G7 (PR #76). No cloud reads, deployment, credentials, IAM or
paid resources were changed by this implementation.

## Verification

The initial error/platform/Android checks failed before implementation. Three
picker/navigation checks and two detail-cap checks also failed before their fixes.
The expanded source/service/router suite passed 103 tests. Ruff and strict mypy
passed; final full CI and review passed as recorded below. Browser
controller remains disabled, so no mobile/theme/history visual pass is claimed.

Code review at `ca2c3de` passed. [CI 39618419176](https://github.com/SumukhaK/football-dashboard/actions/runs/39618419176)
passed 1,497 tests at 98.54% coverage, Ruff, Black, strict mypy (222 files),
image build and ShellCheck. Deliberately allowing a conflicting revision mapping
failed the regression; restoring the conservative rule passed all eight mapping
checks. Review covered source/cache boundaries, own identities, output escaping,
unknown/capped/error navigation and unchanged provider/bytes bounds.

Final reviewed head `08c0421` passed [CI 39618845939](https://github.com/SumukhaK/football-dashboard/actions/runs/39618845939):
**1,498 tests, 98.58% coverage**, Ruff, Black, strict mypy (222 files), image build,
ShellCheck and secret checks. The final adapter test confirms unsupported selected
queries never fall back to all Android versions. [PR #60](https://github.com/SumukhaK/football-dashboard/pull/60)
merged using the owner-authorized administrator override as `2c13a1b`.
Implementation is complete; browser/live acceptance and API/mobile correlation
remain pending as explicitly described above.
