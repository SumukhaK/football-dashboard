# G1–G2 API release foundation

Updated: 21 October 2026. This record does not enable a release picker or claim
that page metrics already honor a selected release. G3–G7 remain separate.

## G1 identity

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

Pending.

## G2b local logs

Pending.

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
