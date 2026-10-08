# Telemetry contract

Version: 1.0.0

This is the agreement between the backend (which writes telemetry) and the ops console (which reads it). The backend may only emit events listed here, with the fields listed here. The console may only rely on what is listed here. Any change bumps the version: a new optional field or a new event is a minor bump; a renamed or removed field is a major bump.

The machine-readable copy is `telemetry-events.json` (at the end of this file). Both repos test against it.

## 1. Log line format

Every log line the backend writes is one JSON object on one line, written to stdout. Cloud Run sends stdout to Cloud Logging, which reads the special keys below.

### Fields on every line

| Field | Type | Rule |
|---|---|---|
| `timestamp` | string | RFC 3339 in UTC with milliseconds, for example `2026-10-08T18:32:27.123Z` |
| `severity` | string | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` (Cloud Logging reads this key) |
| `message` | string | Short human sentence. Never contains user content |
| `logger` | string | Python logger name, for example `backend.app.main` |
| `event` | string or null | A name from the event catalogue, or null for a plain log line |
| `request_id` | string or null | The request's ID (section 2), null outside a request |
| `logging.googleapis.com/trace` | string or null | `projects/<GCP_PROJECT_ID>/traces/<trace_id>` when a span is active and the project ID is set; otherwise null |
| `logging.googleapis.com/spanId` | string or null | 16 hex characters of the active span, or null |
| `trace_id` | string or null | 32 hex characters of the active trace, or null (for the local stack) |
| `service` | string | `football-api` |
| `revision` | string or null | Value of the `K_REVISION` environment variable that Cloud Run sets; null locally |
| `api_version` | string | Settings `api_version`, for example `2.0.0` |
| `contract_version` | string | `1.0.0` |
| `attributes` | object | The event's fields from the catalogue (section 3). Empty object for a plain log line |

### Fields on error lines only

| Field | Type | Rule |
|---|---|---|
| `exception_type` | string | Fully qualified class name, for example `builtins.KeyError` |
| `stack_trace` | string | Python traceback text. Present only on `app.crash`. Error Reporting groups lines whose `message` starts with the traceback, so for `app.crash` the `message` is the full traceback |

### Privacy rules (tested)

- Never log: question or answer text, email addresses, passwords, password hashes, session tokens, invite codes, request bodies, query strings, `Authorization` headers.
- A user is identified only by `user_ref`: the first 16 hex characters of HMAC-SHA256 of the account ID, keyed with the `TELEMETRY_SALT` setting.
- A client address is identified only by `client_ref`: the same HMAC over the client IP.
- Question length in characters is allowed.

## 2. Request IDs

- Header name: `X-Request-ID`.
- If the incoming request has the header and its value matches `^[A-Za-z0-9._-]{8,64}$`, use it. Otherwise create a new one: 32 lowercase hex characters (`uuid4().hex`).
- Every response, including 429 and 500 responses, carries the same `X-Request-ID` header.
- Every log line written while handling the request carries it in `request_id`.

## 3. Event catalogue

`route` is always the route template (for example `/v2/teams/{team}/outlook`), never the raw path, so IDs and team names do not leak and routes group cleanly. Unmatched paths use `"<unmatched>"`.

Durations are integers in milliseconds, named `duration_ms`.

| Event | Severity | When it fires | Attributes (all required unless marked optional) |
|---|---|---|---|
| `http.request` | INFO, WARNING for 4xx, ERROR for 5xx | Once per request, after the response is sent | `method`, `route`, `status` (int), `duration_ms`, `error_code` (string or null: the response's `error` value for 4xx and 5xx), `user_ref` (optional) |
| `app.error` | WARNING for 4xx, ERROR for 5xx | A typed exception handler builds an error response | `route`, `status` (int), `error_code` (the `error` string sent to the client), `exception_type` |
| `app.crash` | ERROR | The catch-all handler returns 500 | `route`, `exception_type` |
| `component.load` | INFO when ok, WARNING when degraded or failed | Each startup load in `main.py`, and each reload after a refresh | `component` (one of the component names below), `status` (`ok`, `degraded`, `failed`), `duration_ms`, `reason` (string or null) |
| `component.degraded` | WARNING | A request needs a component that is not loaded and gets a 503 | `component`, `route` |
| `ratelimit.rejected` | WARNING | The rate limiter returns 429 | `route`, `client_ref`, `retry_after_s` (int) |
| `auth.event` | INFO, WARNING for `failed`, `locked_out`, `blocked` | An account action finishes | `action` (`sign_in`, `sign_out`, `redeem_invite`, `consent`), `outcome` (`ok`, `failed`, `locked_out`, `blocked`, `consent_required`, `invalid_invite`, `weak_password`, `not_signed_in`), `user_ref` (optional, only when the account is known) |
| `refresh.run` | INFO when ok, WARNING when failed | Each daily refresh attempt finishes | `status` (`ok`, `failed`), `duration_ms`, `dataset` (file name or null), `error` (string or null) |
| `data.freshness` | INFO | After match data loads, and after each refresh | `competition`, `matches_through` (ISO date or null), `age_hours` (number or null) |
| `assistant.answer` | INFO | Each chat answer is returned | `path` (`router`, `model`, `model_with_tools`), `question_chars` (int), `retrieved_count` (int), `top_score` (number or null), `confidence` (number), `tool_rounds` (int), `model`, `prompt_tokens` (int or null), `completion_tokens` (int or null), `cost_usd` (number or null), `duration_ms` |
| `assistant.tool` | INFO when ok, WARNING when error | Each tool call finishes | `tool` (tool name), `status` (`ok`, `error`), `duration_ms`, `error` (string or null: the ToolError message) |
| `assistant.abstain` | INFO | The answer says the assistant does not know | `reason` (`no_retrieval`, `low_score`, `model_declined`) |
| `dependency.call` | INFO when ok, WARNING when failed | Each attempt of an outbound call | `dependency` (`ollama_chat`, `ollama_embed`, `football_data`, `openfootball`, `workers_ai`), `operation`, `status` (`ok`, `timeout`, `http_error`, `connection_error`, `error`), `http_status` (int or null), `attempt` (int, starts at 1), `duration_ms` |
| `retry` | WARNING | A failed attempt will be retried | `dependency`, `operation`, `attempt` (the attempt that failed), `max_attempts`, `wait_ms`, `cause` |
| `fallback` | WARNING | A degraded path is used instead of the normal one | `from_path`, `to_path`, `cause` |
| `guardrail.event` | INFO | Reserved for hosting step 3b (safety, cache, budget) | `kind`, `outcome` |

### Component names

`prediction_model`, `prediction_model_v1`, `explanation`, `assistant`, `season_history`, `season_outlook`, `fixtures`, `match_history`, `goals_model`.

### Known fallbacks (`from_path` → `to_path`)

| `from_path` | `to_path` | Where |
|---|---|---|
| `fresh_match_data` | `previous_match_data` | Daily refresh failed; old data kept |
| `fresh_fixtures` | `previous_fixtures` | Fixtures refresh failed; old fixtures kept |
| `server_features` | `supplied_features_only` | Match history did not load; predictions use request features only |
| `tool_calling` | `answer_without_tools` | The tool loop reached its round limit and the model was asked to answer without tools |

## 4. Traces

- One root span per HTTP request (FastAPI instrumentation). Its name is `<METHOD> <route template>`.
- Child spans, named exactly:
  - `assistant.route` (the season router check)
  - `assistant.retrieve` (embedding plus vector search), with child `assistant.embed`
  - `assistant.generate` (each model call), attribute `round` (int)
  - `assistant.tool.<tool name>` (each tool call)
  - `refresh.download`, `refresh.reload`
  - `dependency.<dependency>` (each outbound call attempt), attribute `attempt`
- A retry is recorded as a span event named `retry` on the dependency span, with `attempt`, `wait_ms` and `cause`.
- Span attributes follow the same privacy rules as logs.
- Exporter: OTLP over HTTP to `OTEL_EXPORTER_OTLP_ENDPOINT` locally; Cloud Trace in the cloud; none in tests.

## 5. Metrics

Metrics are derived from the events, not emitted separately. In the cloud they are log-based metrics defined in M6. Locally the Grafana stack queries the logs.

| Metric | From |
|---|---|
| Request count by route and status | `http.request` |
| Latency p50, p95, p99 by route | `http.request.duration_ms` |
| Error rate | `http.request` with status >= 500 over all |
| Crash count | `app.crash` |
| 429 count | `ratelimit.rejected` |
| Degraded components | latest `component.load` per component |
| Refresh failures | `refresh.run` with status `failed` |
| Data age by league | `data.freshness.age_hours` |
| Assistant answers by path, tokens, cost | `assistant.answer` |
| Tool error rate by tool | `assistant.tool` |
| Retries and fallbacks by dependency and cause | `retry`, `fallback` |
| Failed sign-ins and lockouts | `auth.event` |

## 6. telemetry-events.json

Commit this file as `docs/observability/telemetry-events.json` in the main repo and as `contract/telemetry-events.json` in the console repo.

```json
{
  "contract_version": "1.0.0",
  "common_fields": [
    "timestamp", "severity", "message", "logger", "event", "request_id",
    "logging.googleapis.com/trace", "logging.googleapis.com/spanId",
    "trace_id", "service", "revision", "api_version", "contract_version",
    "attributes"
  ],
  "components": [
    "prediction_model", "prediction_model_v1", "explanation", "assistant",
    "season_history", "season_outlook", "fixtures", "match_history", "goals_model"
  ],
  "events": {
    "http.request": {"required": ["method", "route", "status", "duration_ms", "error_code"], "optional": ["user_ref"]},
    "app.error": {"required": ["route", "status", "error_code", "exception_type"], "optional": []},
    "app.crash": {"required": ["route", "exception_type"], "optional": []},
    "component.load": {"required": ["component", "status", "duration_ms", "reason"], "optional": []},
    "component.degraded": {"required": ["component", "route"], "optional": []},
    "ratelimit.rejected": {"required": ["route", "client_ref", "retry_after_s"], "optional": []},
    "auth.event": {"required": ["action", "outcome"], "optional": ["user_ref"]},
    "refresh.run": {"required": ["status", "duration_ms", "dataset", "error"], "optional": []},
    "data.freshness": {"required": ["competition", "matches_through", "age_hours"], "optional": []},
    "assistant.answer": {"required": ["path", "question_chars", "retrieved_count", "top_score", "confidence", "tool_rounds", "model", "prompt_tokens", "completion_tokens", "cost_usd", "duration_ms"], "optional": []},
    "assistant.tool": {"required": ["tool", "status", "duration_ms", "error"], "optional": []},
    "assistant.abstain": {"required": ["reason"], "optional": []},
    "dependency.call": {"required": ["dependency", "operation", "status", "http_status", "attempt", "duration_ms"], "optional": []},
    "retry": {"required": ["dependency", "operation", "attempt", "max_attempts", "wait_ms", "cause"], "optional": []},
    "fallback": {"required": ["from_path", "to_path", "cause"], "optional": []},
    "guardrail.event": {"required": ["kind", "outcome"], "optional": []}
  },
  "forbidden_attribute_names": [
    "question", "message_text", "answer", "email", "password", "token",
    "session_token", "invite_code", "authorization", "body", "query_string"
  ]
}
```
