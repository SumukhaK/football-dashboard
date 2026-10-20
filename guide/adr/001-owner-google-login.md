# ADR 001: owner-only Google sign-in for the console

- **Status:** accepted; implemented slice by slice (D9.1–D9.3 landed, D9.4 in review, D9.5–D9.6 pending)
- **Date:** 19 October 2026
- **Related:** [guide/D9-owner-login.md](../D9-owner-login.md), [guide/README.md](../README.md)

## Context

The console reads real production telemetry: requests, errors, traces, assistant
usage and cost, and the optional invite page writes to Firestore. Today the
whole of its protection is the private Cloud Run boundary — `--no-allow-unauthenticated`
with the invoker IAM check on — reached through `gcloud run services proxy`.
There is no login page, no session, no cookie and no middleware anywhere in
`app/`, so anyone who can pass that boundary sees everything.

That boundary is a fine transport, but it is not an application gate: it cannot
express "only the owner, and only for an hour", it cannot protect a page that is
later published behind a load balancer or a tag, and it cannot be reviewed as
code. Step D9 asks for the console's own gate.

## Decision

Serve the console only to one verified Google account, signed in with Google's
OpenID Connect authorization-code flow.

1. **Google OpenID Connect**, `openid email` scopes only, S256 PKCE, a signed
   five-minute login transaction bound to `state` and `nonce`, and a separately
   signed console cookie with an absolute one-hour expiry.
2. **One exact, server-side allowlist**: the configured owner address, compared
   after lower-casing and nothing else, and only when Google reports
   `email_verified` as the boolean true. Navigation is not security, and neither
   is a query parameter, a header or a `hd` claim.
3. **A default-deny guard** in front of every route, mount and future route,
   with an exact public allowlist (`/login`, the two `/auth/` endpoints,
   `/static/…`, a minimal `/healthz`).
4. **`authlib` for the provider flow, `itsdangerous` for the signed cookies,
   `httpx` at runtime for the provider's HTTP.** No hand-written JWT or
   cryptography. The provider is a small typed adapter behind
   `app.services.auth.IdentityProvider`, so library I/O stays out of the domain
   models and the tests use a fake provider with no Google credential.
5. **A synchronous provider seam.** Every route and service in this console is
   synchronous (`def`, not `async def`, with an injectable `Clock`); the adapter
   is blocking for the same reason. D9.2 pins the exact `authlib` API and
   revisits this if the pinned version's supported flow is async-only.

## There is no dashboard password

Owner access is "Continue with Google" as the configured address. Google owns
the password, passkey, second factor and account recovery; the console never
sees, stores, hashes, resets or emails a credential, and there is deliberately
no registration, forgot-password endpoint, reset token or second owner. The
signing keys below are machine credentials, not something anybody types.

## Stateless sessions, and what they cannot do

The console cookie is signed, not stored: there is no session table, no Redis
and no database. That buys a simple single-owner deployment and costs
revocation:

- **Logout clears this browser's copy only.** A copied cookie stays valid until
  its absolute expiry, unless the session signing key is retired from every
  reachable revision.
- **Changing the Google password, revoking consent or rotating the client
  secret does not invalidate a console cookie.** Only rotating
  `SESSION_SIGNING_KEY` (which signs everyone out) does.
- **If per-session revocation becomes a requirement**, that is a new decision:
  choose a shared TTL store explicitly rather than pretend the stateless
  version has it.

The flip side is that paging, refreshing and history restores cannot extend a
session: the issue and expiry times travel inside the signed cookie and are
never rewritten.

## The deliberate D7 transport change

Cloud Run invoker IAM and application login are different credentials with
different audiences, and one does not replace the other. An invoker identity
token does not sign anybody into the console, and a console cookie does not pass
a private Cloud Run edge.

D9 therefore changes the deployment contract on purpose: **private stays the
default**, and publishing the service for login/callback is an explicit,
validated `dashboard_transport=app-auth` choice that also requires the full auth
configuration and a policy readback. Enabling public access on an image whose
gate has not been verified is not an option, and no pre-auth revision may stay
reachable by tag or alias. Until that slice lands, the IAM/proxy boundary is the
whole of the protection, exactly as it is today.

## Consequences

- The console refuses to start when it is configured for Google sign-in and the
  settings are incomplete: there is no "auth off" switch to fall back to, and
  the fixture mode is an explicit loopback demonstration, refused for a real
  source, an enabled invite page or a hosted revision.
- Configuration, not a request, decides the origin, the callback URL and the
  cookie flags. `Host` and forwarded headers are never trusted for them.
- Two independent signing keys and one client secret have to be provisioned
  privately (Secret Manager), and rotating them is an operator runbook, not a
  code change.
- Every future route is protected by default, including ones nobody has written
  yet; adding a public path is a deliberate edit to one list.
- Security tests live in the suite and need no Google account, which is what
  keeps the gate reviewable in a pull request.

## D9.2 addendum: the provider and the pinned versions

D9.2 implements the provider seam against the versions the lockfile resolves:
**Authlib 1.9.1**, **itsdangerous 2.2.0** and **httpx 0.28.1**. All three are
runtime dependencies now: the production image makes the same calls as a
developer checkout, so httpx is no longer development-only.

- Authlib's **Starlette integration** supplies discovery, the authorization
  URL, S256 PKCE, the code exchange and ID-token validation (signature, the
  algorithm set Google publishes, issuer, audience, authorized party, expiry,
  issued-at and nonce). It does not supply the state store: we pass a state,
  nonce and verifier we generated, and keep them in our own signed five-minute
  transaction cookie. That is the guide's "adapt it to the short transaction
  cookie" without adding a session store, and without ever putting a token in
  a cookie.
- The seam is **asynchronous**, superseding the D9.1 note that it would be
  synchronous. Authlib's supported Starlette flow is async-only; the rest of
  the console stays synchronous.
- The transaction is signed with `itsdangerous` under its own salt, and both
  signing keys and salts are separate from the future session cookie's. Its
  issue and expiry times are re-validated against the injected clock on every
  read, so a correct signature over a stale or over-long lifetime is still
  refused. One cookie means one bounded pending attempt per browser.
- Discovery, JWKS and token requests are **lazy**: building the provider makes
  no network call, and a discovery or key-set outage is a generic failure, not
  an unauthenticated session. ID tokens are validated with the library's
  `leeway` default of 120 seconds for clock skew; the transaction window is
  the configuration's (at most 300 seconds) and is not extended by the
  library.
- No provider token is retained: the access token, refresh token and ID token
  are discarded at the adapter boundary, and the returned identity carries a
  subject, the address and the verification flag only. Failure categories are
  generic (`provider`, `identity`, `state`, `expired`, `request`,
  `cancelled`) so no code, verifier or claim reaches a log line.
- Provider failures are re-raised `from None`, so a normal traceback or log
  record shows the generic category and not the provider's message, the code
  or a token. This covers rendered errors and ordinary exception logging; an
  APM tool configured to capture exception internals is a separate privacy
  check, not something this boundary can promise. The pinned Authlib/joserfc
  pair raises `TypeError`/`KeyError` for malformed discovery, JWKS and token
  shapes; those are mapped inside the provider call boundary, and the token
  response must carry a non-empty string `id_token` (nothing is coerced).
- One narrow compatibility check is explicit: joserfc 1.7.7 accepts a JSON
  boolean `iat` because Python booleans are integers, while OpenID Connect
  requires a NumericDate. The adapter rejects a boolean `iat` after parsing
  and before identity construction; re-evaluate this when Authlib/joserfc are
  upgraded.
- The ID token is the identity source. The userinfo endpoint, an access token,
  a query parameter or a Google-looking header is never read for authorization.

## D9.3 addendum: the console session and the sign-in routes

D9.3 adds the public login page and Google's two hops, plus logout, and the
signed cookie that carries a session between them.

- **One session cookie, nothing else.** `SessionCookie` serialises the Google
  subject, the normalised owner address, the absolute issue/expiry times and a
  random session identifier. No provider token, name, picture or whole userinfo
  is stored. The signing key and salt are separate from the transaction
  cookie's, so the two purposes cannot be substituted for one another.
- **The absolute expiry is server-side.** A session carries its own
  `expires_at`; `loads` re-checks the lifetime bound and the window against the
  injected clock. Reading a session on a later request never rewrites the
  cookie, so paging and refreshes cannot extend an hour into a longer session.
  The cookie's `Max-Age` is transport convenience, not the authority.
- **Request semantics.** `GET /login` is a public, minimal page (no shell, no
  navigation, no source read) with the Google button and a generic notice. A
  `next` target is reduced to a local path before it reaches the link or the
  transaction. `POST /auth/logout` requires the exact configured `Origin` and
  the session's identifier as its CSRF token, compared in constant time, then
  expires both auth cookies and redirects to `/login`. `GET /auth/logout` is
  not a route, so a link or a prefetch cannot end a session.
- **Cookie shape.** Hosted sessions use `__Host-dashboard-session` and
  `__Host-dashboard-oauth`: HttpOnly, Secure, SameSite=Lax, Path=/, no Domain.
  The explicit loopback mode (configuration allows `http://` only on
  `127.0.0.1`) uses unprefixed names and no Secure flag. A hosted revision
  cannot configure the insecure form.
- **Generic failure, no session.** Cancellation, a stale or malformed
  transaction and a provider failure clear the pending transaction and land on
  `/login?retry=1`; a verified non-owner gets a generic 403 and neither cookie.
  Logs carry only `sign-in started|accepted|failed|denied` plus the failure
  category, never a code, state, cookie value or address.
- **Discovery failures use the same retry.** A provider failure while starting
  sign-in clears the pending attempt, logs only its category and returns the
  same uncached retry redirect as a callback failure; it does not escape as an
  unhandled server error.
- **Application access-log privacy.** Uvicorn's callback access record has its
  entire query removed before handlers see it, including the trailing-slash
  redirect case. Method, path and status remain; other route diagnostics and
  the callback's actual request parameters are unchanged. Cloud Run's automatic
  request logs and other retained/exported sinks remain an independent D9
  launch check; this application filter cannot sanitize those logs.
- **Stateless limit, stated plainly.** There is no session store, so clearing
  the cookie or letting it expire is the whole of logout for a copied cookie:
  a stolen signed session remains usable until its own `expires_at`. Google's
  authorization code remains single-use, and the transaction cookie is cleared
  on success and failure, which bounds replay of the sign-in attempt. Adding
  server-side revocation would require a store and is not claimed here.

The login routes and `/healthz` remain public; D9.4 installs the default-deny
guard around every other route and mount, and adds the response headers and
history policy.

## D9.4 addendum: the default-deny guard and the response policy

D9.4 puts one pure-ASGI middleware in front of the whole application. It is
installed only when `auth_mode` is `google`; the explicit loopback `fixture`
mode stays a demonstration with no guard, and there is no incomplete-config
bypass.

- **Exact public surface.** The only method/path exceptions are `GET`/`HEAD`
  `/login`, `/auth/google`, `/auth/callback` and `/healthz`, plus safe
  `GET`/`HEAD` `/static/…` assets. There is deliberately no `/auth` prefix
  rule: `/auth/logout` is protected. A route added after the app is built is
  denied until it is listed here.
- **The framework's docs are absent, not merely guarded.** `docs_url`,
  `redoc_url` and `openapi_url` are `None`, so `/docs`, `/redoc` and
  `/openapi.json` are ordinary 404s for an owner and ordinary guarded answers
  for everyone else. No Swagger CSP exception is needed.
- **Refusal shape.** An unauthenticated full-page `GET`/`HEAD` gets a `303` to
  `/login?next=` carrying the quoted path and query; a `/partials/…` path or
  `HX-Request: true` gets `401` plus `HX-Redirect: /login`, so HTMX never swaps
  a login document into a panel. Every non-safe method gets `401` before any
  route, dependency, body parse, source read or store write. `HEAD` responses
  carry no body.
- **One identity rule.** A correctly signed session for another address gets
  `403` and a cleared session cookie, with no source or store work. An expired,
  forged or malformed session is simply unauthenticated: `303`/`401` plus a
  deletion when the browser carried the cookie. Forwarded or identity-looking
  headers (`X-Forwarded-User`, `X-Email`, `Authorization`, …) never
  authenticate, and `Host` is not used for a security decision.
- **Path checks happen after decoding.** Static segments are percent-decoded
  before they are accepted, so `%2e%2e`, backslashes, embedded slashes, empty
  segments and dot-leading names are not public. The static mount is public only
  for `GET`/`HEAD`.
- **Response policy, including refusals.** Every response carries
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, a CSP with `frame-ancestors 'none'`,
  `base-uri 'none'`, `form-action 'self'` and `object-src 'none'`, and HSTS when
  the configured origin is HTTPS. `script-src` is `'self'` plus a fresh
  per-request nonce; inline theme bootstrap and chart-data scripts carry it.
  `style-src` keeps `'unsafe-inline'` because chart markup uses width styles.
  Every non-static response is `Cache-Control: no-store`, including guard
  refusals and owner 404s; static assets keep their own caching.
- **Invites.** `POST /invites` requires the exact configured
  `auth_public_origin`, never the request `Host`, and the session identifier as
  a hidden CSRF token, compared in constant time before the body is parsed or
  the store is touched. The copy button moved to `static/invite.js`, removing
  the inline `onclick`.
- **Logout and history.** The sidebar offers a real `POST /auth/logout` form
  carrying the session CSRF token. Protected bodies set `hx-history="false"`,
  and `static/auth.js` removes only `htmx-history-cache` and reloads a page
  restored from the back/forward cache; the login page loads the same script.
- **Minimal health.** `/healthz` is public and returns only `{"status": "ok"}`.
  It does not expose the contract version, the source or configuration.
- **Proof in the suite.** The guard tests enumerate real routes by descending
  FastAPI's included-router wrappers, across invites and crashes on and off;
  they add a synthetic route, invoke the middleware directly to prove the body
  is not read, and cover forged cookies, forwarded headers, partial/HTMX
  requests, path traversal and the 403 cookie deletion. Existing page tests now
  use a real signed owner session rather than an authorization-off switch.
- **Deliberately unchanged.** The app still does not enforce `Host`; Cloud Run
  and its ingress own the hostname, and no authorization decision depends on
  it. Deployment transport and IAM remain D9.5.

