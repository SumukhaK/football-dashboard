# G1–G2 API release foundation

Updated: 21 October 2026. This record does not enable a release picker or claim
that page metrics already honor a selected release. G3–G7 remain separate.

## G1 identity

Merged in [PR #48](https://github.com/SumukhaK/football-dashboard/pull/48),
merge `645ab69`, reviewed head `1893e2d`; all exact-head CI checks passed.

Implemented from main `0d8ff5a`. [ADR 003](adr/003-api-release-identity.md)
defines exact identity, supported labels and the reserved unknown selection.
TelemetryEvent retains `api_version` independently of revision, contract and
Android identities. ReleaseSelection is frozen/hashable with distinct
all/exact/unknown states. Existing constructors and contract 1.1.0 remain
compatible; required missing fields are still rejected.

Evidence: 33 new failures before implementation, 34 identity checks and 78
identity/model/contract checks passed afterward. Full local suite: **1,260
passed, 98.95% coverage**. Ruff, Black and strict mypy passed. Removing identity
retention in memory failed all eight exact-label cases. The frozen-mutation
test's dynamic assignment was separately rechecked after its typing fix.

Source check in the platform repository: `backend.app.main.create_app()` passes
`settings.api_version` into logging; JsonFormatter emits it unchanged. Config
currently defaults to `2.6.0`. The inspected tracked release/container workflows
do not inject a tag-derived backend API_VERSION. Operator prerequisite: set the
actual backend release explicitly when deploying and verify emitted metadata;
an Android or dashboard release is not that value. No platform files, deployed
configuration or historical records were changed by this task.

## G2a shared query and fixture filtering

Merged in [PR #49](https://github.com/SumukhaK/football-dashboard/pull/49),
merge `752e648`; all exact-head CI checks passed. Full local suite: **1,272
passed, 98.95% coverage**.

EventQuery now carries a frozen ReleaseSelection, defaulting to all for old
callers. The existing shared matcher applies its exact/unknown predicate
before ordering and limiting. FixtureSource reuses that path with no duplicate
filter. Query hashing includes the typed selection, preserving cache identity.

Evidence: 12 regressions failed before implementation; 34 fixture/filter checks
passed afterward; strict mypy passed across 189 files. Cases cover all/exact/
unknown, case-sensitive labels, the literal exact label `all`, sparse matches
at limit=1, mixed predicates and same-timestamp cursor ties. G2a does not claim
GCP push-down, catalogue discovery or per-page metrics scoping.

## G2b local logs

LocalLogSource already delegates to the shared matcher delivered by G2a. This
slice adds real temporary-file acceptance rather than duplicating that code.
Thirteen local regressions cover fixture parity, limits/cursor ties, switching
release against an unchanged complete snapshot, size-change append detection,
malformed/missing-field counts and the byte-limited tail. Test writers use
explicit LF so byte accounting is identical on Windows and Linux.

All **71 local/shared checks passed**, with repository Ruff/Black and strict
mypy (190 files) passing. An in-memory omitted-filter mutation fails 12 local
checks. The initial byte-tail test caught Windows newline translation in the
test writer, which was corrected; no production bug or new filter was invented.
The published PR's full CI validates this test-only integration slice.

## G2c Google filtering, cache parity and bounded discovery

Pending. Discovery must report incomplete samples and failures explicitly.
Existing A2 whole-page/read budgets remain pending; no new read may be described
as bounded solely because it has a row cap or cache TTL.

## Verification boundaries

All regressions use local fixtures/fakes. Full local pytest uses a nonexistent
GOOGLE_APPLICATION_CREDENTIALS path, restored afterward, to prevent the known
credential-dependent navigation test from using local ADC. That separate
offline-test defect remains pending. Two existing HTTPX deprecation warnings
remain; no tests were skipped or weakened. No live Google query, IAM write,
secret change, deployment or visual browser acceptance is claimed.
