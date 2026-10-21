# G6 Overview comparison by API release

Implemented in the owner-authorized G6-G7 sequence, 21 October 2026.
[ADR 006](adr/006-release-comparison-samples.md) records shared sample semantics.

All API releases mode adds a native sortable comparison below the existing summary:
requests, server failures/rate, p50/p95, measured-latency sample count, retained
backend crashes, assistant answers/tokens, estimated INR cost and first/last IST
observation. Unknown release remains visible. Combined totals use pooled events,
never averages of release rates or latency percentiles. Redirects/4xx remain in
the request denominator and are not server failures. Missing latency is unmeasured.

The table reuses Overview's bounded current request/counted samples, with one
additional assistant.answer read. Tokens/cost show reported-answer coverage;
missing/invalid values are unreported, real zero is retained, INR conversion and
rate/date disclosure use F2 once. No per-release RPC is added. Catalogue results
are reused once per request for the picker and quiet release labels, even with
cache TTL zero. A quiet comparison row says no observations in compared samples,
not proof of health. First/last observation is not deployment or lifetime coverage.
Caps and source/discovery failures remain explicit; bounded sample counts reconcile
only with the same retained sample, not a promise of complete historical traffic.

Default ordering is exact semantic version newest first, then other labels;
unknown stays last. Request-volume, 5xx-rate and p95 links toggle direction with
stable semantic ties and missing metrics last. Links select the exact recorded
release and preserve quick/custom period across full/partial navigation, sorting
and refresh. Native links, table headings/caption, a keyboard-focusable scroll
region, wrapping release labels and existing theme tokens support accessibility.
Selected-release charts remain scoped and do not perform the extra all-mode read.

The initial seven service/router checks failed before implementation and passed
after. Expanded checks cover pooled arithmetic, null/invalid costs, real zero,
redirects/4xx, caps, query-count stability, sorting, hostile labels, custom/unknown
links, catalogue reuse and failure rendering. The affected suite passed 103 checks
before the final type/fixture cleanup; final CI evidence is recorded with the PR.
Browser controller still reports disabled after the owner enabled it, so no actual
mobile/theme/history visual pass is claimed. No deployment, live Google queries,
IAM, retention, paid exports or mobile/API correlation was changed.
