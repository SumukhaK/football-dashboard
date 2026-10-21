# G3 release picker and historical window

Implemented in PR #53, 21 October 2026; integrated with the A2 bounded-read fixes.
[ADR 005](adr/005-release-view-context.md) records the URL/time contract.

Native release forms retain exact labels, all/unknown selection and absent URL
choices. Discovery failure/incompleteness are distinct from a complete result
with no observations. Strict SemVer precedence sorts real semantic versions;
prefixes/other labels keep exact identity and stable lexical ordering.

Quick windows stay 1h/6h/24h/7d. Custom inputs are explicitly IST; selection
redirects convert them once to UTC start/end URL parameters. The defaults are
31 days per range and 365 days back, configurable in .env.example. These are
safety bounds, not verified provider retention. Invalid, future, reversed,
naive, duplicate and ambiguous scope is rejected before source reads. Native
selection targets are allowlisted and discard pagination/open-panel cursors.

All rendered internal GET links, full/partial views, refresh, filter forms,
pagination, panel Close and navigation carry scope explicitly. Historical
windows are passed into page builders. Auth/writes/static/external trace URLs
are excluded. Existing no-store and HTMX-history protections stay intact.
Controls use native labelled forms, wrapping theme tokens and visible focus;
HTMX window changes hide stale results while loading.

G3 does not claim G4's backend release scoping or G5's provider attribution.
Intermediate pages explicitly label combined backend values and source-wide
provider results. Android versions remain independent of API release identity.

Verification: the initial 33 focused checks passed after implementation. Added
regressions cover actual historical reads, navigation/refresh context, official
SemVer prerelease/build order, hostile labels and validation before reads.
CI at `6741c20` passed 1,395 tests (98.63% coverage), Ruff, Black, strict mypy
and the image/security checks. The final mixed UTC/IST regression passed with
all 36 release-control router cases. Native forms now reject competing time
representations instead of silently overwriting one. Final-head CI is required
before merge. Self-review covered caller URLs, auth exclusions, validation and
source failure rendering.

Browser acceptance remains pending under G7: the controller still reports local
browser use disabled after the owner enabled it. No mobile/theme/history UI
pass is claimed by this automated evidence. No live Google reads,
deployment, credentials, IAM, retention or paid export changes were made.
