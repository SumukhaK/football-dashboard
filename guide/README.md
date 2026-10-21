# Build guide

**Execution status checked 20 October 2026 against main `b47f478` and merged PRs.** D1–D9, including D2b and every D8/D9 slice, are implemented. D9.6's controlled launch is [recorded and merged](D9.6-live-verification.md). Completed guides retain their original specifications as reference; do not execute them again as a pending work queue. A Done marker means the named implementation/evidence exists, not that every historical browser acceptance condition was rerun in this documentation audit.

| Step | File | Execution | Merged evidence |
|---|---|---|---|
| D1 | [D1-scaffold.md](D1-scaffold.md) | **Done** — skeleton, contract, fixtures, CI | [#1](https://github.com/SumukhaK/football-dashboard/pull/1) |
| D2 | [D2-sources.md](D2-sources.md) | **Done** — fixture/GCP sources and cache | [#2](https://github.com/SumukhaK/football-dashboard/pull/2) |
| D2b | [D2b-local-log-source.md](D2b-local-log-source.md) | **Done** — local JSON logs and diagnostics | [#17](https://github.com/SumukhaK/football-dashboard/pull/17) |
| D3 | [D3-overview.md](D3-overview.md) | **Done** — Overview | [#3](https://github.com/SumukhaK/football-dashboard/pull/3) |
| D4 | [D4-errors-and-requests.md](D4-errors-and-requests.md) | **Done** — Errors, Requests, waterfall | [#4](https://github.com/SumukhaK/football-dashboard/pull/4) |
| D5 | [D5-assistant.md](D5-assistant.md) | **Done** — assistant telemetry | [#7](https://github.com/SumukhaK/football-dashboard/pull/7) |
| D6 | [D6-data-and-access.md](D6-data-and-access.md) | **Done** — Data and Access | [#13](https://github.com/SumukhaK/football-dashboard/pull/13) |
| D7 | [D7-deploy.md](D7-deploy.md) | **Done** — staging deployment and safety follow-ups | [#14](https://github.com/SumukhaK/football-dashboard/pull/14), [#29](https://github.com/SumukhaK/football-dashboard/pull/29), [#33](https://github.com/SumukhaK/football-dashboard/pull/33), [#37](https://github.com/SumukhaK/football-dashboard/pull/37) |
| D8 | [D8-redesign.md](D8-redesign.md) | **Done** — all 6 slices | [#12](https://github.com/SumukhaK/football-dashboard/pull/12), [#15](https://github.com/SumukhaK/football-dashboard/pull/15), [#19](https://github.com/SumukhaK/football-dashboard/pull/19), [#27](https://github.com/SumukhaK/football-dashboard/pull/27), [#20](https://github.com/SumukhaK/football-dashboard/pull/20), [#18](https://github.com/SumukhaK/football-dashboard/pull/18) |
| D9 | [D9-owner-login.md](D9-owner-login.md) | **Done** — all 6 slices; exact PR per slice in the guide | [#31](https://github.com/SumukhaK/football-dashboard/pull/31), [#32](https://github.com/SumukhaK/football-dashboard/pull/32), [#34](https://github.com/SumukhaK/football-dashboard/pull/34), [#35](https://github.com/SumukhaK/football-dashboard/pull/35), [#33](https://github.com/SumukhaK/football-dashboard/pull/33), [#37](https://github.com/SumukhaK/football-dashboard/pull/37) |
| D9.6 evidence | [D9.6-live-verification.md](D9.6-live-verification.md) | **Done** — dated live outcomes and limits | [#37](https://github.com/SumukhaK/football-dashboard/pull/37) |

## Other guide files and remaining work

| File | Status |
|---|---|
| [DeepSeek D7 handoff](deepseek-d7-handoff.md) | **Partially complete.** Narrow IAM, redesign deployment and D9 launch done. Actual narrow-role trace read unrecorded; optional owner-impersonation cleanup, panel refactor and live Crashlytics activation remain separate. Historical 19 October instructions are not a new work queue. |
| [Offline-test handoff](offline-test-handoff.md) | **Done** in [#73](https://github.com/SumukhaK/football-dashboard/pull/73): a suite-wide sentinel fails any test that builds a real Google client, and the two leaking crash-nav tests read sample data. |
| [Testing gaps](testing-gaps.md) | **Current work queue.** A–D and F done (A2 read bounds, malformed logs, verified promotion, loopback demo, IST/INR); G1–G6 done; G7 browser acceptance and E1's last reconciliation remain. |
| [A1](A1-google-retry-verification.md) / [A2](A2-google-read-bounds.md) | **Done.** Exhausted-retry handling and finite Google read budgets; A2 holds the page-budget table. |
| [Telemetry contract](telemetry-contract.md) | **Done / active specification.** Version 1.1.0 integrated and enforced in [#11](https://github.com/SumukhaK/football-dashboard/pull/11) and [#28](https://github.com/SumukhaK/football-dashboard/pull/28). |
| [ADR 001](adr/001-owner-google-login.md) | **Accepted; implementation done.** Owner-only Google login and controlled launch. |
| [ADR 002](adr/002-cloud-run-health-path.md) | **Accepted; implementation done.** Hosted `/health`, verified in #37. |

No D9.7 implementation is pending: its duplicate branch was discarded. The honest D9.6 limits remain recorded: hosted-profile storage/bfcache hits were not directly instrumented, local real-clock expiry used 60 seconds rather than observing a full hosted hour, and Google password recovery/client-secret rotation were documented but not performed. None of these observations is silently upgraded by a Done marker.

## Follow-up queue

The [testing gaps tracker](testing-gaps.md) is the current work queue. As of
21 October 2026: A1–A2e, B1–B2, C1–C3 (verified promotion, PR #63), D1–D2
(loopback-only demonstration, PR #68), F1–F2 and G1–G6 are done. Open: G7's
browser acceptance, the rest of E1, the H tasks from the 21 October audit and the operator follow-ups. The
[offline-test handoff](offline-test-handoff.md) is done (#73).

### Release/history

G1-G6 implementation is complete; [G7](G7-history-verification.md) records deterministic
source-to-page history checks and remaining responsive/browser acceptance.
[Controls](G3-release-controls.md), [backend views/Logs](G4-backend-release-views.md),
[attribution/Android](G5-release-attribution.md) and [comparison](G6-release-comparison.md)
describe supported exact API scope, IST display and INR estimates. Query safety
bounds do not prove cloud retention. Do not repeat completed implementation or
silently mark unobserved browser/cloud evidence as done.

## Dependencies on the main repo

- D1 to D6 run on sample data and can start any time.
- D2b lets the console read the backend's local JSON log file, so you can see real data before any cloud setup. It needs the main repo's step M2 for real logs. It stays useful after Google Cloud is set up, for checking backend changes on your own PC.
- Real data needs the backend to emit the contract. That work is the main repo's hosting tracker step 4 (steps M1 to M6 there).
- D8.1 (the shell and themes) can run before D6, so the Data and Access pages are built in the new look. D8.5 needs the Crashlytics crashes page (PR #8).
- D7 needs the Google Cloud project (hosting tracker step 0) and the API on Cloud Run (tracker step 1).

## Access-control prerequisite

D9 implements the application gate. Private IAM/proxy remains the deployment default; explicit app-auth transport requires verified owner login, negative checks and retirement of old traffic tags. Never publish a pre-auth console. The only authorized owner is sumukh.aithal@gmail.com. See the D9.6 evidence for the actual tested deployment and remaining limitations.

## Choosing a tool and model

OpenRouter only gives you access to models. Run these prompts in an open source coding agent that can read files, edit them and run commands, set up with your OpenRouter key: Cline, Roo Code or Kilo Code in VS Code, Aider in a terminal, or OpenHands in a browser. Pick a model that is strong at agentic coding and tool use, with a long context window.

## How to run one step

Apply these instructions only to an assigned pending task; completed stage guides are reference material.

1. Create the step's branch from an up-to-date `main` (the branch name is at the top of each file).
2. Start a fresh agent session and paste the whole step file as the first message. One step per session.
3. Let the agent write the tests first, then the code, then run every command in the file's "Commands that must pass" section.
4. If a command fails, have the agent fix the code. Do not let it skip, delete or weaken a test.
5. Read the diff against the file's "Do not" list, commit the intended files, push and open the pull request. Completed work must not remain only on the local machine.

Each file repeats the repo rules so the agent never needs anything else. If an agent breaks a rule, paste the rule back and ask it to fix the code.
