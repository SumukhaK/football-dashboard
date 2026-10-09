# Fixtures

This directory contains generated test fixtures for the football dashboard console.

## Files

- **events.jsonl** – 24 hours of synthetic telemetry events (log lines) matching the contract schema. Each line represents a log entry from the backend telemetry system.
- **traces.json** – 10 trace records showing distributed tracing spans (HTTP requests, dependencies, retries, falls back). Includes a `retry` span event as required by the contract.
- **error_groups.json** – 4 grouped error categories (out-of-memory, container exit, instance start, platform events).
- **platform_events.json** – Platform-level events (out_of_memory, container_exit, instance_start) tied to revision changes.

## Generation

All fixture files are generated deterministically by `scripts/make_fixtures.py` using a fixed seed (7) to guarantee reproducible outputs across runs.

## Usage

Run the fixture generator to regenerate:

```bash
cd D:\Anthropic\TestProjects\football-dashboard
python scripts/make_fixtures.py
```

This produces identical output every time, ensuring test stability.