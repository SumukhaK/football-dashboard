# ADR 003: preserve recorded API release identity

## Status

Accepted — 21 October 2026; implements the owner's G1 requirement.

## Context

Contract 1.1.0 already carries `api_version`, but TelemetryEvent discards it.
The API release differs from a Cloud Run revision, telemetry contract version,
dashboard version and Android version. Later source filters/cache keys need
one immutable selection type with unambiguous all/exact/unknown semantics.

## Decision

- Retain `TelemetryEvent.api_version`, defaulting to None for existing direct
  constructors. Read the raw contract field; never infer it from other fields.
- A usable recorded label is a printable, nonblank string of 1–64 characters.
  Preserve its exact case, spacing, prefix and version spelling. Do not parse
  or normalize it as semantic versioning. Sorting is a later UI concern.
- Null, empty/blank, non-string, non-printable and overlong values are unknown.
  The literal lowercase `unknown` is reserved for unknown. Other spelling/case
  remains exact identity. A missing required field still fails contract
  validation; unknown handling does not repair invalid contract records.
- Use a frozen dataclass `ReleaseSelection(kind, value)` with kinds all,
  unknown and exact. Only exact carries a usable label. Omitted query input
  means all; `api_version=unknown` means unknown; other valid input means exact.
  Reject invalid explicit input. `all` is a valid exact label, distinct from
  the all-selection state. All includes unknown.
- Store raw identity, not HTML/query escaping. Apply escaping at each output
  boundary. Later Logging predicates must preserve case before row limits;
  ordinary Logging string equality is case-insensitive.

## Consequences

Contract 1.1.0 and old constructors stay compatible; no raw data is rewritten.
Selections can be embedded in frozen EventQuery cache keys without string
sentinel collisions. Unsupported labels remain visible as unknown rather than
invented versions. G1 does not enable filtering or an on-screen selector.
