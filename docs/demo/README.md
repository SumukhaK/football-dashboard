# Walkthrough video

A narrated, subtitled end-to-end tour of the console, for anyone from a first-time
visitor to a reviewer of its architecture. It is a real recording of
`uv run python -m app.demo` on the bundled sample data, followed by short slides on
the telemetry contract, access control, the deploy flow and CI.

- [Play in the browser](https://cdn.jsdelivr.net/gh/SumukhaK/football-dashboard@f027fea6ee73bf0029758049802081f215fa5db6/docs/demo/walkthrough.mp4) (served by the jsDelivr CDN from this
  repository; GitHub itself only offers the file as a download).
- [walkthrough.mp4](walkthrough.mp4): 6 min 22 s, 1280×720, H.264 and AAC, with burned-in
  subtitles and a soft English subtitle track.
- [walkthrough.srt](walkthrough.srt): the same subtitles as a separate file.

## Chapters

| Time | Chapter |
| --- | --- |
| 0:00 | What it is |
| 0:24 | Architecture and the telemetry contract |
| 1:15 | Running the sample-data demo |
| 1:34 | Overview |
| 2:16 | Requests and a request's timeline and trace |
| 2:46 | Errors |
| 3:01 | Assistant |
| 3:32 | Data and jobs |
| 3:43 | Access |
| 3:54 | Android app crashes |
| 4:11 | Source and themes |
| 4:27 | Access control |
| 5:04 | Deploying to Cloud Run |
| 5:36 | Tests and CI |
| 6:09 | Try it |

## How it was made

The pages were driven by a scripted Playwright browser against the local
sample-data demonstration, so every page's data comes from `fixtures/`. The
voice is offline text-to-speech (Kokoro, run locally, so the narration never
left the machine), and ffmpeg combined the recording, narration and subtitles.
Figures quoted in the narration (tests, coverage, contract version) were
measured on the commit the video was recorded from (`59705f3`) and will drift as the code
changes; re-record rather than edit the video when they do.

## Transcript

**0:00 · What it is**

This is the Football Dashboard, a read-only web console for the Football Intelligence backend. It answers the questions you ask when something is live: what is the API serving, how fast, what is failing, and what did the AI assistant do behind each answer. Everything in this video is a real run of the console on its bundled sample data, started with one command on a laptop.

**0:24 · Architecture and the telemetry contract**

First, how it fits together. The backend writes structured logs, traces and errors to Google Cloud, and the Android app's crashes are exported to BigQuery by Firebase Crashlytics. The console only reads them, through one of three sources: sample fixtures, the backend's own log file, or Google Cloud. Both sides agree on a versioned telemetry contract, version 1.1.0, with 16 event types. The console loads that contract at startup and relies only on the events and fields it lists. The contract also forbids personal fields such as emails, passwords and question text; users appear only as salted hashes. The stack is deliberately small: Python, FastAPI, server-rendered templates, htmx for partial updates and ECharts for the charts.

**1:15 · Running the sample-data demo**

To run it, install with uv and start the demo module. The launcher binds the loopback address itself, and the app refuses any connection that is not from this machine, whatever the headers say. Every page is labelled as sample data, so a demonstration can never be mistaken for production.

**1:34 · Overview**

The Overview page starts with what needs attention: here the assistant is degraded and data freshness has failed. Below that are the headline numbers, requests, error rate, p95 latency and server crashes, each compared with the previous window. Every page shares a time window picker, and all clocks are shown in India Standard Time while the data stays in UTC. The API release table compares releases from the same samples as the summary, and keeps unknown releases visible instead of hiding them. Then traffic by status, latency percentiles, and the slowest routes. The assistant chat route stands out, at 86 seconds.

**2:16 · Requests and a request's timeline and trace**

Requests lists every call with its release, route, status and duration, and the small numbers elsewhere link straight into this filtered list. Let's open that slow assistant request. The detail page joins the request's log events into one timeline: the embedding call succeeded, then the chat model hit three connection errors, with two retries, before the request failed with a 503. Underneath, the trace waterfall shows exactly where the 86 seconds went.

**2:46 · Errors**

The Errors page groups server crashes by exception, and handled errors by their error code and route. On the right are Cloud Run platform events, such as running out of memory or a container exiting, next to any degraded components.

**3:01 · Assistant**

The Assistant page explains how answers were produced. It splits them by path, router, model, or model with tools, with latency for each, and shows the abstention rate and how often model calls failed. Then the model calls themselves, each tool the assistant used, the slowest answers, and every fallback it took. Token counts are shown here; costs appear as an estimate in Indian rupees only when an operator configures a rate and its date. There is no live exchange-rate lookup.

**3:32 · Data and jobs**

Data shows how fresh each league's match data is, every daily refresh run with its errors and fallbacks, the downloads behind it, and which components reloaded.

**3:43 · Access**

Access covers sign-in outcomes, lockouts and blocks, rate limiting, and invite and consent events. People only ever appear as pseudonymous references.

**3:54 · Android app crashes**

App crashes reads the Android app's Crashlytics export: fatal crashes, non-fatals and app-not-responding events, with their own version filter. An issue's detail shows its recent devices and the latest stack, with the app's own first frame highlighted.

**4:11 · Source and themes**

The Source page says which telemetry source is being read and what it can answer. A local log file, for example, has no traces, and pages say so rather than showing an empty chart. And the console ships with both a light and a dark theme.

**4:27 · Access control**

Now, security. Sign-in mode defaults to Google, and the console refuses to start without its settings. It uses Google's OpenID Connect code flow with PKCE, accepts exactly one owner account, and issues a signed session that expires after an hour. A default-deny guard covers pages, partial updates, details and writes. The sample-data mode you've been watching is only allowed on loopback, and refuses a real data source, the invite page or a hosted revision. The only page that writes anything, the invite page, is off by default.

**5:04 · Deploying to Cloud Run**

Deployment is to Cloud Run as a private service, under a reader service account with read-only roles, including a custom trace role with a single permission. The deploy script builds an image and creates an unserved, private candidate, pinned by image digest and numeric secret versions. An operator checks that candidate privately and records what they saw. Promotion needs that record, and the exact revision and digest, before any traffic moves. Rollback names a revision too, never latest.

**5:36 · Tests and CI**

Quality is enforced in CI on every pull request: Ruff, Black, strict mypy, and the test suite. On this commit that is 1,665 tests at 98% coverage, against an 80% gate. CI also builds the container image and runs ShellCheck over the deploy scripts. Tests run offline, and a size rule keeps files under 400 lines and functions under 40. Decisions are written down as architecture decision records in the guide folder.

**6:09 · Try it**

That's the Football Dashboard: an honest, read-only view of a live AI system, built to be safe to run and easy to review. Clone it, run the demo, and every page you've seen is on your machine.
