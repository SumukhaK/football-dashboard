# Synthetic retained release history

G7 integration input, fixed clock **2026-10-21T12:00:00Z**. No production logs,
identities or credentials. API events use contract 1.1.0 required fields, cloned
from the existing synthetic samples with explicit IDs/times/measurements.

- events.jsonl: one September request; five historical October requests across
  two IST midnights; two assistant answers (one reported cost/token sample, one
  null), one crash and a fixed-clock component anchor outside the history window.
- platform_events.json: two revisions mapped to API 2.6.0 and one unmapped revision.
- crashlytics_events.json: independent Android 2.6.2/2.5.1 historical events and a
  fixed-clock anchor so sample shifting is zero in the deterministic tests.
- traces.json and error_groups.json: intentionally empty; release-scoped crash
  grouping is derived from the retained app.crash record rather than fake groups.

History window is UTC 01 Oct 18:28 through 02 Oct 18:35, end exclusive (IST
01 Oct 23:58 through 03 Oct 00:05). All five requests include one 503, a 302 and
404; p50 is 30 ms and p95 is 1000 ms. Unknown API release is explicit. Two API
2.6.0 revisions are independent from Android 2.6.2 display version.

The test helper settings use a **synthetic** 80 INR/USD rate/date and real signed
owner test cookies. Native fixture-only preview instructions and pending browser
acceptance are in [G7](../../../guide/G7-history-verification.md). These fixture
files do not establish live release history, cloud retention or production cost.
