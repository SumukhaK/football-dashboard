# Fixtures

Sample telemetry for the console's `fixture` source: 24 hours of the backend's
log lines ending at `2026-10-08T18:00:00Z`, written in the format and with the
values of `contract/telemetry-events.json` and `guide/telemetry-contract.md`.

## Files

- **events.jsonl**: about 3,200 log lines, one JSON object per line, sorted by
  time. Every line of a request shares its `request_id` and `trace_id`. Lines
  outside requests (startups, refreshes, data freshness) have neither.
- **traces.json**: the traces of the 10 assistant chats in `events.jsonl`,
  with the span names from contract section 4. Retries are `retry` span events.
- **error_groups.json**: the crashes and 5xx errors in `events.jsonl`, grouped
  by exception type (4 groups).
- **platform_events.json**: Cloud Run events: an instance start for each
  revision, then an out-of-memory and a container exit.

## What happens in the sample day

- Revision `football-api-00041-kav` starts with the assistant failed, so its
  two chats get 503 with `component.degraded`.
- The 04:00 refresh fails twice against football-data.co.uk and falls back to
  the previous match data; the 05:00 refresh works and reloads the match data.
- Revision `football-api-00042-wum` starts at 06:00 with every component loaded.
- One chat retries Ollama twice then answers, one gives up after three
  attempts, one hits the tool round limit and answers without tools.
- One account is locked out after five failed sign-ins (03:12).
- One client is rate limited in a burst of 30 requests (11:40).
- The instance runs out of memory at 17:42.

## Regenerating

```bash
uv run python scripts/make_fixtures.py
```

The generator uses seed 7, so the output is byte-identical every run.
`tests/scripts/test_make_fixtures.py` fails if the committed files differ from
a fresh generation, and checks every line against the contract's values.
