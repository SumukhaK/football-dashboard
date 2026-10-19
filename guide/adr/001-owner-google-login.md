# ADR 001: owner-only Google sign-in for the console

- **Status:** accepted; implemented slice by slice (D9.1 landed, D9.2–D9.6 pending)
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
