# D8: Redesign and themes

**Execution: Done — all six implementation slices merged.** Status checked 20 October 2026; each slice below links its merged PR. These markers record implementation, not a new full-browser audit of every viewport. Live Crashlytics activation remains optional and is not implied by D8.5 completion.

Six pull requests, one per part below, in order. Each part has its own branch and PR title. Give an agent one part at a time, with this whole file, and say which part to build.

Mockups: https://claude.ai/artifact/XJvnmWZuMbN4f9jpNUbS7g (Overview in dark and light, Requests, Errors, App crashes, Assistant and a phone layout). Every artboard has a Theme tweak. The mockups use sample numbers; the pages show real ones.

## Goal

Every page answers "what needs my attention?" first, in one consistent look that works in a dark and a light theme. The data, the URLs, the HTMX endpoints and the services stay as they are; this step changes how pages are laid out and styled, plus the small service changes listed per part.

Done when: every page uses the new shell and tokens, both themes pass the contrast test, nothing scrolls sideways at 390 px or 1280 px, and every link that works today still works.

## Read first

- `app/templates/base.html`, `app/templates/partials/window_picker.html`, `app/static/charts.js`, `app/static/css/`.
- `app/routers/__init__.py` (`NAVIGATION`).
- The page's own service and template before you restyle it.

## The look

- **Ground and surfaces:** never plain white. The light theme uses a cool grey-blue ground with near-white cards; the dark theme uses a deep navy-slate.
- **Sidebar:** midnight navy in both themes, so the console has one recognisable colour whichever theme is on.
- **Accent:** periwinkle for links, selection, the current page and the p95 line. Status colours appear only where something is wrong; "healthy" is a small green dot, never a green fill.
- **Type:** IBM Plex Sans for the interface, IBM Plex Mono for routes, IDs, revisions and stack frames. Tabular numbers in every table and number card.
- **Cards:** 1 px border, 12 px radius, no heavy shadows. Numbers right-aligned in tables.

### Tokens

Put these in `app/static/css/tokens.css`, exactly as written. Templates and CSS use only the variable names, never a hex value.

```css
:root, [data-theme="dark"] {
  --nav-bg:#0B111C; --nav-fg:#C3CBDA; --nav-strong:#F1F4F9; --nav-muted:#8792A8;
  --nav-active-bg:#26305A; --nav-active-fg:#DDE2FF; --nav-border:#1C2438;
  --logo-bg:#8B9BFF; --logo-fg:#0B111C;
  --bg:#0E131D; --surface:#151C29; --surface-2:#1A2232; --line:#1F2838; --border:#263044;
  --control:#33405A; --ink:#E8ECF4; --ink-2:#C5CDDB; --muted:#A0AABD; --faint:#7F8AA0;
  --on-ink:#0E131D;
  --accent:#8B9BFF; --accent-strong:#B3BDFF; --accent-bg:#222B4D; --accent-border:#4A57A0;
  --accent-2:#5B6BE0;
  --fail:#FF8A80; --fail-bg:#3A1D24; --fail-soft:#2A1A20;
  --warn:#F7C46C; --warn-bg:#3A2C14; --ok:#5FE0A0; --ok-bg:#163527;
  --purple:#B9A8FF; --purple-bg:#2A2350;
  --chart-ok:#3A4560; --chart-4xx:#F5A524; --chart-5xx:#F2554A; --chart-p50:#6F7B92;
  --dot-ok:#34D399; --dot-warn:#F5A524; --dot-fail:#F2554A; --dot-anr:#9B85FF;
}
[data-theme="light"] {
  --nav-bg:#151C30;
  --bg:#E6EAF2; --surface:#F6F8FB; --surface-2:#EDF0F6; --line:#E1E6EE; --border:#D3DAE5;
  --control:#BFC8D6; --ink:#121A2B; --ink-2:#2E3A50; --muted:#46536A; --faint:#5B677D;
  --on-ink:#F6F8FB;
  --accent:#3B4FD9; --accent-strong:#2A3AB0; --accent-bg:#DFE4FC; --accent-border:#A4B0F5;
  --accent-2:#8E9BF2;
  --fail:#B42318; --fail-bg:#FADAD6; --fail-soft:#FBE9E7;
  --warn:#93370D; --warn-bg:#FAE6B4; --ok:#067647; --ok-bg:#CDEFD9;
  --purple:#5925DC; --purple-bg:#E2DEFC;
  --chart-ok:#B9C1CF; --chart-4xx:#F79009; --chart-5xx:#D92D20; --chart-p50:#98A2B3;
  --dot-ok:#12B76A; --dot-warn:#DC6803; --dot-fail:#D92D20; --dot-anr:#7A5AF8;
}
```

The `--nav-*` and `--logo-*` values not repeated under `[data-theme="light"]` stay the same in both themes on purpose.

### Theme switching

- `<html data-theme="…">` holds the theme. A five-line inline script at the top of `<head>` sets it before the first paint: the saved choice from `localStorage` if there is one, otherwise `prefers-color-scheme`. That avoids a flash of the wrong theme.
- A theme button in the sidebar footer (`aria-label="Switch to light theme"` or dark) flips the attribute, saves the choice and dispatches a `themechange` event. Put the logic in `app/static/theme.js`. Wrap every `localStorage` call in `try`/`catch`, since private windows can block it.
- `charts.js` already reads colours from CSS variables. Point it at the `--chart-*` and `--accent` names above and re-render every chart on `themechange`.

### Shared pieces

- **Sidebar (`partials/sidebar.html`):** grouped navigation. `NAVIGATION` becomes a list of sections: Backend (Overview, Errors, Requests, Assistant), Android app (Crashes, once D8.5's page exists), Platform (Data, Access, and Invites when `invites_enabled`). The current page gets `aria-current="page"` and the accent background. The footer holds the theme button and the version and revision. Below 900 px the sidebar collapses into a top bar with a menu button built on `<details>` (no JavaScript).
- **Page header (`partials/page_header.html`):** the page title, a one-line subtitle naming the window ("Last 24 hours compared with the 24 hours before"), the window picker as a segmented control, and on pages that refresh, a button reading "Updated 18:04 UTC".
- **Banners:** the "partial data" and "narrow the filter" banners become a slim bar under the page header, with `role="status"`.
- **Status pill macro (`partials/macros.html`):** `pill(text, tone)` with tones `fail`, `warn`, `ok`, `accent`, `neutral`, `purple`. Every status badge on every page uses it.
- **Display names:** `app/services/labels.py` with `display_name(raw: str) -> str` that turns `prediction_model_v1` into "Prediction model v1" and `model_with_tools` into "Model with tools". Services put display names into view models; templates never format names.
- **Durations:** `format_duration_ms(ms: float | None) -> str` in the same module: under 2,000 ms as "386 ms", from 2,000 ms as "86.1 s", `None` as "no data".

Nav badges (an error count on Errors, status dots on Assistant and Data) are not part of D8. Each would add a telemetry read to every page load, against a Cloud Logging read quota of about 60 calls a minute. Raise it as its own step if wanted.

## D8.1 Shell, tokens and themes

**Execution: Done** — [PR #12](https://github.com/SumukhaK/football-dashboard/pull/12).

Branch: `dash/D8-1-shell` · PR title: `feat(ui): add the sidebar shell and dark and light themes`

- `tokens.css`, `theme.js`, the sidebar, the page header, the pill macro and `labels.py` as above.
- Fonts: IBM Plex Sans (400, 500, 600) and IBM Plex Mono (400, 500) as `woff2` in `app/static/fonts/`, with the SIL Open Font License text next to them. They are static files, not a Python dependency; no CDN.
- Split `app.css` into `tokens.css`, `shell.css` and `components.css`, each under 400 lines. Keep page-specific files (`errors.css`, `requests.css`, `assistant.css`).
- Remove the big page title and the version footer. Every existing page renders inside the shell with its current body, restyled only through the tokens.
- Tests: the sidebar marks the current page for every route; Invites appears only when `invites_enabled`; `display_name` and `format_duration_ms` on edge cases (empty, one word, digits, `None`, 1,999 and 2,000 ms); `tests/static/test_tokens.py` parses `tokens.css` and checks, for both themes, that `--ink`, `--ink-2`, `--muted`, `--faint` and `--accent` reach a contrast of 4.5:1 on `--bg`, `--surface` and `--surface-2`, and each pill's text on its own background. Write the contrast formula (WCAG relative luminance) in the test; no new library.

## D8.2 Overview

**Execution: Done** — [PR #15](https://github.com/SumukhaK/football-dashboard/pull/15).

Branch: `dash/D8-2-overview` · PR title: `feat(ui): redesign the overview page`

- **Needs attention:** one card listing only components whose state is not OK, each with its display name, a pill (Failed or Degraded), one sentence from the tile detail and a link (the degraded-requests link that exists today, or the Data page for `data_freshness`). Healthy components shrink to a row of chips with a green dot ("9 healthy"). When nothing needs attention, the card says "All 11 components healthy" in one line.
- **Headline cards:** four large cards: Requests, Error rate, p95 latency, Server crashes. Each shows its change against the previous window with the comparison named ("vs previous 24h") and a tone from a `good_direction` field in the view model: lower is better for errors, latency and crashes. When the previous window has no data, the label reads "no earlier data" instead of a change. Requests, error rate and p95 latency get a sparkline over the chart intervals: the request and failure counts are counted from the same `http.request` events as the headline, so a 3xx counts as a request in both, and the latency line reuses the p95 series. Rate limited, Retries and Fallbacks become one line of small numbers under the cards.
- **Charts** side by side from 1,000 px wide, stacked below. 2xx in `--chart-ok`, 4xx in `--chart-4xx`, 5xx in `--chart-5xx`; p95 in `--accent`, p50 in `--chart-p50`.
- **Slowest routes:** right-aligned numbers, an inline bar for p95 on a log scale, durations through `format_duration_ms`, and the error rate as a fail pill only when it is at least `ERROR_RATE_HIGHLIGHT = 0.01` (a named constant in `app/domain/overview.py`).
- Tests: the attention list holds only non-OK tiles and keeps their order; the healthy count; the tone for each headline in both directions and the "no earlier data" case; the highlight threshold at exactly 1%.

## D8.3 Requests

**Execution: Done** — [PR #19](https://github.com/SumukhaK/football-dashboard/pull/19).

Branch: `dash/D8-3-requests` · PR title: `feat(ui): redesign the request explorer with a detail panel`

- **Filters:** one search box ("Filter by route, or paste a request ID to open it") plus a chip per active filter (status, event, method, component), each with a remove button, and "Clear all". The query parameters and their validation stay as they are.
- **Rows:** relative time ("9 h ago") with the full UTC time in a `title`, a status pill, method and route on one line with the error code or message under it in `--fail`, and the duration right-aligned. Remove the request ID column. The whole row is a link.
- **Detail panel:** clicking a row loads `GET /partials/requests/{request_id}/panel` into an `aside` next to the list and pushes `?open=<id>` to the URL, so a link to a panel can be shared. The panel shows the status, route, time and duration, a crash or error summary when there is one, the waterfall, the request ID with a Copy button, and "Open full timeline" linking to `/requests/{request_id}`, which stays. Below 900 px the panel covers the list with a Close button.
- Relative time comes from a helper that takes the clock as an argument. Tests use a fixed clock.
- Tests: chips render for each active filter and their remove links drop only that filter; `?open=` renders the panel on a full page load; the panel partial returns 404 JSON for an unknown ID; relative time at 59 s, 1 min, 59 min, 1 h, 23 h and 2 days.

## D8.4 Errors

**Execution: Done** — [PR #27](https://github.com/SumukhaK/football-dashboard/pull/27).

Branch: `dash/D8-4-errors` · PR title: `feat(ui): show errors as an issue list`

- **Server crashes** (renamed from "Crash groups", so it is never confused with the app crashes in D8.5): one row per group with the short exception name in bold, the message, the route and first-seen time in small text, a sparkline of counts per interval, the count and "last seen 9 h ago". The service adds per-interval counts to each group.
- **Handled errors grouped by error code:** one row per code with the status pill, the display name, the number of routes ("10 routes", or the route itself when there is only one), a sparkline and the total. The per-route rows sit inside a `<details>` under it. Grouping happens in the service.
- **Platform events** move to a right-hand column as a timeline, out-of-memory and container exits in `--fail`, instance starts in `--faint`. **Degraded components** sit under it.
- Tests: grouping by code sums counts and counts distinct routes; a code with one route shows that route; per-interval counts for a crash group across the window edges.

## D8.5 App crashes

**Execution: Done** — [PR #20](https://github.com/SumukhaK/football-dashboard/pull/20); the underlying page landed in [PR #8](https://github.com/SumukhaK/football-dashboard/pull/8). Hosted Crashlytics/BigQuery activation is still separate operator work.

Branch: `dash/D8-5-crashes` · PR title: `feat(ui): redesign the app crashes page`

Needs PR #8 (the Crashlytics crashes page) merged first.

- The page title becomes "App crashes" under the Android app section of the sidebar, with the subtitle "Android app, from Crashlytics, last 7 days".
- Type chips replace the "Events by type" table: All, Fatal, Non-fatal, Not responding, each with its count, filtering through a `type` query parameter. Display labels come from the service: `FATAL` is Fatal, `NON_FATAL` is Non-fatal, `ANR` is Not responding. Pills: fail, warn, purple.
- Issue rows: type pill, the exception's short class name in bold (`SerializationException`), the message, then the package, app versions and last seen in small text, with events and users (installs) right-aligned.
- The detail opens in a side panel like D8.3, and `/crashes/{issue_id}` stays as the full page. The stack lists each frame as method on one line and package, file and line under it. The first frame in the app's own code is highlighted and labelled "first app frame". Library frames are muted. The app package prefix is a setting, `crash_app_package` in `app/config.py`, defaulting to `com.footballintelligence.app`. Recent events show time, device and Android version.
- Tests: type filter and counts; short name and package split for a nested class and for a name with no package; first app frame found, and none found when no frame matches the prefix.

## D8.6 Assistant

**Execution: Done** — [PR #18](https://github.com/SumukhaK/football-dashboard/pull/18).

Branch: `dash/D8-6-assistant` · PR title: `feat(ui): redesign the assistant page`

- **Headline cards:** Answers (with the most common abstention reason under the count), Abstention rate, Model-call failures (the worst dependency's failure rate, naming it), and Gave up (the count, linking to the request when there is one, or to the filtered request list when there are several).
- **How questions were answered:** one card replacing the donut, the abstention table and the latency table. A single stacked bar for the path split, then one table: path display name, answers, share, p50 and p95 through `format_duration_ms`, with a p95 over `SLOW_ANSWER_MS = 30000` in `--fail`.
- **Model calls:** one block per dependency, with a bar split into ok, timeout, HTTP error and connection error, then attempts, retries and the gave-up link on one line. A dependency with no failures says "No failures".
- **Tools:** display names, the last error under the tool name only when there is one, and the error rate as a fail pill only when above zero.
- **Slowest answers:** rows of path, a duration bar and the duration, each linking to the request. **Fallbacks** read "Fresh match data → previous match data", with cause and count. **Tokens:** p50 large with p95 and total under it; when cost is unreported, a quiet one-line note.
- Remove the donut renderer from `charts.js` if nothing else uses it.
- Tests: the worst dependency is picked by failure rate then name; the slow threshold at exactly 30,000 ms; the gave-up link for zero, one and several requests.

## Data and Access (D6)

If D6 is merged before D8.1, D8.1 restyles those pages through the tokens like the others. If D6 is built after D8.1, build it in the new shell from the start, using the pill macro, the page header, display names and the issue-row and card patterns above.

## Browser checks for every part

Run the fixture source and open each changed page in Chromium at 390 px and 1280 px, in both themes. Record in the PR description that nothing scrolls sideways, every link and button on the page was clicked, the theme button switches without a reload and charts redraw in the new colours, and the console shows no errors.

## Do not

- Do not change URLs, query parameters or HTMX partial paths that exist today; add new ones only where a part names them.
- Do not add Tailwind, a component library or a CSS framework. Plain CSS with the tokens.
- Do not put hex colours anywhere except `tokens.css`.
- Do not add reads to the sidebar or the page header.
- Do not show question or answer text on the assistant page.

## Repo rules (apply to every file you write)

- Python 3.12, managed with `uv`. Formatting with Black (line length 88), linting with Ruff, types with mypy in strict mode.
- Type annotations on every function signature. No `Any` unless a third-party API forces it, with a comment saying why.
- Every public module, class and function has a one-line docstring.
- No file over 400 lines. No function over 40 lines. Split before you reach either.
- One concern per function. If a function name needs "and", split it.
- No wildcard imports, no mutable default arguments, no global mutable state. Configuration comes only from `app/config.py` (pydantic-settings), never from `os.environ` directly.
- Layering: `app/domain` imports nothing from the app; `app/sources` imports `app/domain`; `app/services` imports `app/domain` and the `TelemetrySource` protocol; `app/routers` import services only. Routers stay thin: no calculations in routes or templates.
- Comments explain why, not what. No commented-out code. No `TODO` without a linked GitHub issue.
- No placeholder code, no fake data paths in production code, no "coming soon" pages. Build the real thing or leave it out.
- The console is read-only. It never writes, deletes or changes anything in Google Cloud.
- Never print or store secrets. `.env` is gitignored; `.env.example` is committed.
- Tests live in `tests/`, mirroring `app/`. Tests are deterministic: no real clock (inject one), no network, no random without a fixed seed.
- Coverage of at least 80% (`fail_under = 80`).
- Commits use Conventional Commits: `type(scope): description`, lowercase, imperative, no full stop. Types: feat, fix, chore, docs, test, refactor. Scopes: app, sources, ui, ci, deploy, docs, contract.
- Do not add a dependency that this step does not list. The only new files from outside are the IBM Plex fonts in D8.1. If you think anything else is needed, stop and say why.

## Commands that must pass before you finish

```bash
uv sync --extra dev
uv run ruff check .
uv run black --check .
uv run mypy app tests
uv run pytest --cov=app --cov-report=term-missing
```

If any command fails, fix the code. Never delete, skip or weaken a test to make it pass.
