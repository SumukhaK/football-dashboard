# Build guide

These are the staged implementation prompts, one pull request each (D8 is six). As of 19 October 2026, D1–D8 and the optional local-log source D2b are merged. D7 has a redeploy follow-up in PR #29; deployed state still needs separate operator verification. D9 is the remaining owner-login plan. Preserve the original stage-specific contracts and recheck current main and open PRs before executing a step.

| Step | File | Builds |
|---|---|---|
| D1 | [D1-scaffold.md](D1-scaffold.md) | Project skeleton, contract loader, domain models, deterministic sample data, CI |
| D2 | [D2-sources.md](D2-sources.md) | The `TelemetrySource` interface: sample data and Google Cloud readers, with a cache |
| D2b | [D2b-local-log-source.md](D2b-local-log-source.md) | Optional: real data from the backend's local JSON log file, with no Google Cloud project |
| D3 | [D3-overview.md](D3-overview.md) | Overview page: component health, traffic, error rate, latency |
| D4 | [D4-errors-and-requests.md](D4-errors-and-requests.md) | Errors and crashes page; request search and the trace waterfall |
| D5 | [D5-assistant.md](D5-assistant.md) | Assistant page: answer paths, tools, retries, fallbacks, tokens and cost |
| D6 | [D6-data-and-access.md](D6-data-and-access.md) | Data freshness and refresh jobs; sign-ins, lockouts and rate limiting |
| D7 | [D7-deploy.md](D7-deploy.md) | Private Cloud Run deploy with a read-only service account |
| D8 | [D8-redesign.md](D8-redesign.md) | Redesign in six parts: sidebar shell with dark and light themes, then each page |
| D9 | [D9-owner-login.md](D9-owner-login.md) | Proposed: Google login restricted server-side to the verified owner; protects every page/partial/write |

[DeepSeek D7 handoff](deepseek-d7-handoff.md) is the consolidated follow-up: verified live IAM findings, current PR evidence, implementation order, acceptance checks and rollback instructions.

[telemetry-contract.md](telemetry-contract.md) is this repo's copied telemetry contract, version 1.1.0. The platform emits contract 1.1.0 (including user_ref); keep the contract, validators and fixtures synchronized in focused integration changes before claiming live-source compatibility. This documentation update does not silently change the executable contract.

## Dependencies on the main repo

- D1 to D6 run on sample data and can start any time.
- D2b lets the console read the backend's local JSON log file, so you can see real data before any cloud setup. It needs the main repo's step M2 for real logs. It stays useful after Google Cloud is set up, for checking backend changes on your own PC.
- Real data needs the backend to emit the contract. That work is the main repo's hosting tracker step 4 (steps M1 to M6 there).
- D8.1 (the shell and themes) can run before D6, so the Data and Access pages are built in the new look. D8.5 needs the Crashlytics crashes page (PR #8).
- D7 needs the Google Cloud project (hosting tracker step 0) and the API on Cloud Run (tracker step 1).

## Access-control prerequisite

D9 is a proposed plan, not implemented login. Keep real-data access private through D7 IAM/proxy until it is complete. D9 explicitly describes how an ordinary browser login changes D7 transport access; do not publish a pre-auth console. The only authorized owner is sumukh.aithal@gmail.com.

## Choosing a tool and model

OpenRouter only gives you access to models. Run these prompts in an open source coding agent that can read files, edit them and run commands, set up with your OpenRouter key: Cline, Roo Code or Kilo Code in VS Code, Aider in a terminal, or OpenHands in a browser. Pick a model that is strong at agentic coding and tool use, with a long context window.

## How to run one step

1. Create the step's branch from an up-to-date `main` (the branch name is at the top of each file).
2. Start a fresh agent session and paste the whole step file as the first message. One step per session.
3. Let the agent write the tests first, then the code, then run every command in the file's "Commands that must pass" section.
4. If a command fails, have the agent fix the code. Do not let it skip, delete or weaken a test.
5. Read the diff against the file's "Do not" list, commit the intended files, push and open the pull request. Completed work must not remain only on the local machine.

Each file repeats the repo rules so the agent never needs anything else. If an agent breaks a rule, paste the rule back and ask it to fix the code.
