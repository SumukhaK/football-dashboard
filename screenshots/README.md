# Dashboard screenshots

Screenshots of every page of the Football Dashboard console, for a walkthrough of
someone who has never seen it.

Every image was taken from the `fixture` source — the sample day of telemetry that
ships with the repo — at 1440 px wide, with the page scrolled to the top and the
full page captured. The first nine use the dark theme; the last is the light-theme
overview. The console follows the operating system's colour preference by default,
and the toggle in the sidebar footer remembers a choice per browser. Anyone can
reproduce these locally with no Google Cloud account:

```bash
uv sync --extra dev
auth_mode=fixture uv run uvicorn app.main:app
```

The fixture source is the default. `auth_mode=fixture` is the loopback-only
demonstration profile; Google mode is the default for a hosted deployment and
refuses to start without the Google settings.

## What the console is for

The Football Intelligence backend answers questions about football matches and
serves a few Android app calls. This console is a **read-only window onto that
backend's telemetry**: what it serves, how fast, what fails, and how the assistant
arrived at its answers. It reads what the backend already sends to Google Cloud,
and apart from the opt-in invite page it writes nothing.

The sidebar is the way around, and it mirrors who runs what:

| Sidebar section | Pages | Covers |
| --- | --- | --- |
| Backend | Overview, Errors, Requests, Assistant | the HTTP API and the assistant behind it |
| Android app | App crashes | the app's crashes, non-fatals and ANRs |
| Platform | Data, Access | the daily data refresh, and who signs in |

A page that is switched off in configuration is left out of the sidebar
altogether, so the console never shows a link that leads to nothing. Invites, for
example, only appears when that feature is enabled.

## The frame around every page

Four things behave the same way everywhere, so they are worth knowing up front:

- **The time window.** `1h 6h 24h 7d` picks the period every number on the page is
  calculated over. Pages that look at infrastructure rather than live traffic
  default to 7 days; the rest default to 24 hours.
- **Numbers you can click.** Cards and rows are usually links into the filtered
  Requests list, so a surprise on a summary page is one click from the raw rows.
- **Times are IST.** Every displayed date, clock and chart label uses India
  Standard Time. Telemetry, query windows and pagination cursors retain their
  canonical UTC values, and a window's end is exclusive — a request at the
  boundary belongs to the next window, never to both.
- **Wide tables scroll sideways inside their own box** rather than pushing the
  whole page sideways. A clipped right-hand column in a screenshot below is that
  behaviour, not a missing column.

The footer holds the theme toggle and the version. Invite pages are the one write
path and are not part of this read-only walkthrough.

---

## 1. Overview — is anything wrong right now?

![Overview page](01-overview.png)

The page to open first. **Needs attention** lists only the components that are
not healthy, what its last read said and when — a healthy console says so in one
line and stays quiet. The four cards underneath are the headline numbers
(requests, error rate, p95 latency, and server crashes) each compared against the
window immediately before, so you can tell "busy" from "getting worse".

Below that, requests by status and latency over the window, then the slowest
routes. The sparklines are the same shape you meet on the other pages: one bar per
time bucket, so a spike has a time of day rather than just a total.

## 2. Requests — what the backend actually served

![Requests page](02-requests.png)

One row per request: when, the route, the status and how long it took. Failed
requests carry their error code and message on the row rather than hiding in a
log.

The box at the top filters the list by route, status, event, component, or a raw
request ID — which is what the small numbers elsewhere link into. Open a row for
the side panel, or paste an ID to go straight to the request's own page.

## 3. Request detail — what happened inside one request

![Request detail page](03-request-detail.png)

The facts on the request (route, status, duration, revision, error code, user),
then its **trace** if it has one.

The timeline lists the events the backend emitted while handling it, with the
fields each event carried. The waterfall at the bottom puts those same spans on a
time axis, which is how you see that a 3.3-second answer was 3.2 seconds of one
model call rather than slow retrieval.

## 4. Errors — what failed

![Errors page](04-errors.png)

Four questions, top to bottom:

- **Server crashes** — unhandled server exceptions, grouped by exception type,
  with how often each happened, when it was first and last seen, and which routes
  hit it.
- **Handled errors** — errors the backend caught and turned into a status code
  (401s, 422s and so on), grouped by error code and route, with a per-interval
  sparkline behind each row, so a burst is visible as a burst.
- **Platform events** — what Cloud Run did to the service: out-of-memory kills and
  container exits, and instances starting. An out-of-memory row is the one to
  look for first when latency spikes.
- **Degraded components** — a component that is reachable but not working
  properly, and how many times it said so.

## 5. Assistant — how the assistant answered

![Assistant page](05-assistant.png)

The console shows how the assistant answered, never what was asked or answered.
**How questions were answered** splits the answers by path — the router answered
directly, the model answered, or the model used tools — with latency for each
path, so a slow path is obvious next to a fast one.

**Model calls** and **Tools** show the underlying calls and whether any of them
failed or timed out, including links to the requests where they did. **Slowest
answers** and **Fallbacks** show the individual slow ones and where the assistant
had to fall back to a different strategy. **Tokens** covers prompt and completion
sizes and cost — and says plainly when the model provider does not report a
figure, rather than showing a zero.

## 6. App crashes — the Android app

![App crashes page](06-crashes.png)

Read from the Crashlytics export. In Google mode the page appears only when that
export is configured; the fixture source ships sample crashes. The filter chips
count fatal, non-fatal and not-responding events, and the list groups them into
the distinct problems, each with its event and user counts and the app versions
it appeared in. A crash that only affects one app version is usually a client bug
with a known fix.

## 7. Data — is the data fresh?

![Data page](07-data.png)

Behind every prediction is a daily refresh of football data. **Freshness** is the
answer to "can I trust last night's numbers": one row per competition, showing how
far behind it is and whether the last read worked. **Refresh runs** is the daily
job itself, with duration, dataset, any error, and any fallback it used.
**Downloads** counts the upstream site's failures and retries, and **Component
reloads** lists the individual pieces loaded inside a measured run.

## 8. Access — who signs in

![Access page](08-access.png)

Sign-in outcomes over the window, then failed sign-ins per interval. **Lockouts
and blocks** shows the accounts and clients that were stopped, and **Rate
limiting** shows which client was rejected and which route it was hammering —
usually enough to tell an attack from a broken app build retrying in a loop.
Invite redemptions and consent decisions follow.

## 9. Source — where the numbers come from

![Source page](09-source.png)

Open `/source` directly, or from the sidebar footer when the console is reading a
local log file. It names the telemetry source the console is reading, and,
honestly, what that source can and cannot answer — Cloud Trace, Error Reporting
and platform events are three separate reads, and a source may support some and
not others. When the source is a local log file it also reports how the last read
of that file went. This is the page to check before believing a blank section is
good news.

## 10. The light theme

![Overview page in the light theme](10-overview-light.png)

Same page, same data, light theme. The choice is remembered per browser, and
every chart follows it.

---

## Taking these again

The images were produced by running the console against the fixture source at
1440 px wide, with the page scrolled to the top and the full page captured. The
dark images use a dark colour preference and the last image a light one; the
theme follows the system preference until the sidebar toggle is used. Lists
longer than about 2000 px (the Requests table, for one) are cut off in the image;
the page continues past the bottom of the picture.

The set was retaken on 21 October 2026 against the current console, including the
redesigned Errors and App crashes pages and the IST display. `guide/D8-redesign.md`
describes the redesign slices; retake the affected images if a page changes
again.
