# D9: Owner-only Google sign-in

Status: **Implementation and deployment pending.** This guide publishes the D9 execution plan. Rechecked 19 October 2026 against main at `f9bd2ba399cc4930a1d2b832f0bb6819b1324abb` (PR #28 merged). Publishing the plan does not add authentication to the running console.

**Owner access will use “Continue with Google” as sumukh.aithal@gmail.com. There is no dashboard-local password to generate or reset.** Google handles the account password, passkey, second factor and account recovery. Application signing secrets below are separate machine credentials; they are not a password you type into the dashboard.

This guide is the detailed D9 implementation plan in the existing `guide/` documentation folder. Do not create a competing plan in `docs/` or `tasks/`. D8.3 requests, D8.4 errors and D8.5 crashes are merged. Recheck current main and open PRs before implementation, especially deployment follow-up PR #29 and README/screenshots PR #22. Preserve other agents' changes.

Suggested first branch: `dash/D9-1-owner-auth`; focused PRs follow the ordered slices below. Proposed title: `feat(app): restrict the console to its owner`.

## 1. Verified state and scope

| Area | Repository evidence / required outcome |
|---|---|
| Authentication | `app/main.py` has no authentication middleware or auth routes; `app/config.py` has no OIDC/session/owner settings. Existing page routes do not require a user session. |
| D7 | Deployment scripts already exist under `deploy/`. Earlier wording that D7 was unimplemented was stale. They require private Cloud Run invocation and print the gcloud proxy command. |
| Live cloud | Not inspected in this planning task. Repository flags are not proof of current live IAM, secrets, revision, traffic or exposure. |
| Interim access | Keep real telemetry private behind Cloud Run IAM; use the authenticated proxy until D9 is implemented and verified. Loopback fixtures are development data. |
| Selected owner | Only the server-verified Google account `sumukh.aithal@gmail.com`. Another verified Google account must still get 403. |
| Protected data | Overview, errors, requests/details/traces, assistant usage/cost, Data/Access, source diagnostics, optional crashes/details, and optional invite form/writes. |
| Backend accounts | Football Android/backend passwords and invite codes remain separate; do not reuse, reset or couple them to dashboard sign-in. |

Verify with `git status --short`, `git log -1`, `git ls-files --error-unmatch guide/D9-owner-login.md` and a source search for auth middleware/settings/routes. Keep this plan and its README/index links committed together; completed documentation must not remain an untracked local handoff. Stage the intended files explicitly rather than collecting unrelated local work with `git add .`.

## 2. Owner setup, password generation and reset

### Prepare the Google account

1. Open [Google Account security](https://myaccount.google.com/security) as `sumukh.aithal@gmail.com`. Confirm recovery email/phone and set up a passkey or 2-Step Verification with an independent recovery method.
2. If you want a new Google password, generate a unique long password in your password manager and set it in Google's Password screen. Save it in the manager. Do not give that password to DeepSeek/Codex or put it in this repo, .env, Secret Manager, a screenshot or chat. The dashboard never receives it.
3. Under Google Account → Security & sign-in → How you sign in to Google → 2-Step Verification, create backup codes where supported. Keep them privately outside this repository and separately from the phone. Creating a new set invalidates the old set. [Google's instructions](https://support.google.com/accounts/answer/1187538?hl=en).
4. After D9 ships, open the configured dashboard HTTPS URL → Continue with Google → choose the exact owner account → complete Google's challenge → return to the intended console page.
5. Dashboard logout clears this browser's console session, not Google's global session. Use the account chooser to switch accounts; other accounts remain forbidden. After the console's one-hour expiry, sign in again. Google may reuse its own existing login.

### Recovery and reset runbook

| Situation | What to do |
|---|---|
| Change a known password | Google Account → Security & sign-in → Password → reauthenticate and set a new password. [Official password instructions](https://support.google.com/accounts/answer/41078?hl=en). |
| Forgotten Google password / lost second factor | Use [Google Account recovery](https://accounts.google.com/signin/recovery); use a passkey, recovery method or unused backup code when offered. No dashboard forgot-password/email-reset endpoint is to be built. |
| Wrong account chosen / 403 | Retry Google's account chooser with the owner. Never widen the allowlist, accept a form email or disable verification to bypass the denial. |
| OAuth client/redirect error | Fix the operator configuration described below. Resetting a Google password does not fix `redirect_uri_mismatch`, `invalid_client` or Cloud Run IAM denial. |
| Dashboard cookie suspected stolen | Contain public access if needed, rotate `SESSION_SIGNING_KEY`, promote only a new-key revision, remove old-key traffic tags/aliases, and sign in again. Rotate OAuth transaction key if it may be exposed too. |
| Google account compromised | Recover/secure the Google account; contain dashboard exposure, rotate both signing keys, inspect access, then restore owner access. Do not add a temporary public/no-auth recovery mode. |
| Permanent owner replacement | Requires an explicit owner/operator decision, exact allowlist configuration change, session-key rotation and tests proving the old owner denied and replacement accepted. No first-visitor registration or silent second owner. |

**Changing/recovering the Google password does not automatically revoke an already issued stateless dashboard session.** Logout only clears this browser's copy. A copied signed cookie can remain usable until its absolute expiry unless its signing key is retired from every reachable revision. Revoking Google consent/client secret alone also does not revoke console cookies.

Google identity recovery and Google Cloud administration are distinct permissions. If the same account loses both, an existing separately authorized cloud administrator is needed for containment; this guide does not create one or promise that an agent can recover Google's account.

## 3. Selected architecture and non-goals

Use Google's OpenID Connect authorization-code flow with S256 PKCE, a signed short-lived login transaction, and a separately signed one-hour console cookie. Authorization is an exact server-side verified-owner allowlist. The guard executes before routing dependencies, body parsing, service/cache/source/store work; hidden navigation is not security.

Keep the current Python 3.12/FastAPI/Jinja/HTMX architecture. Use Authlib's Starlette integration for discovery/code flow/ID-token validation, explicit runtime `httpx`, and `itsdangerous` for signed cookies. `httpx` is currently development-only and must be available in the production image. Resolve compatible versions into `uv.lock` and document their purpose; do not hand-write JWT or cryptography.

Before implementation add an ADR in the repo's existing location, or `guide/adr/001-owner-google-login.md` if none exists. Record this choice, stateless-session limits, dependencies and the deliberate D7 transport change. A typed provider adapter/service keeps library I/O outside domain models and thin routers; tests use fake provider/HTTP/clock without Google credentials.

No local password database, registration, reset emails, role-management UI, backend credential reuse, refresh-token storage, Firebase Auth migration, IAP/Cloudflare migration, new session database or paid edge product. IAM/proxy remains a valid interim mode. If immediate per-session revocation becomes required, explicitly select a shared TTL store first; do not pretend the stateless version has it.

## 4. Configuration contract

All settings belong to `app/config.py` using pydantic-settings and model-level validation for dependent fields. Keep names consistent across code, tests, deployment scripts and placeholder-only `.env.example`.

| Setting | Contract |
|---|---|
| `AUTH_MODE` | Default `google`. Only alternative `fixture` is an explicit loopback demonstration mode, never a generic `off`/`disabled` switch. |
| `OWNER_EMAIL` | Exactly one address, `sumukh.aithal@gmail.com`. Lowercase normalization only; no wildcard, comma list, Gmail dot removal or plus-address equivalence. |
| `GOOGLE_CLIENT_ID` | OAuth Web application client ID, not Android client ID, API key or service-account ID. |
| `GOOGLE_CLIENT_SECRET` | Server SecretStr/config secret; never in HTML, errors or logs. |
| `AUTH_PUBLIC_ORIGIN` | Canonical scheme/host/optional port only. No userinfo/path/query/fragment. HTTPS hosted; explicit `http://127.0.0.1:8080` permitted only for local Google-flow testing. |
| `AUTH_CALLBACK_URL` | Must exactly equal configured origin + `/auth/callback`. Never derive from request Host or forwarded headers. |
| `SESSION_SIGNING_KEY` | Independent random secret with at least 32 bytes entropy; no default, checked-in value or fallback key. |
| `OAUTH_SIGNING_KEY` | Different independent random secret for login transactions; reject equal keys. |
| `SESSION_MAX_AGE_SECONDS` | Default and maximum 3600; shorter positive policy allowed. Enforce absolute expiry on the server. |
| `OAUTH_TRANSACTION_MAX_AGE_SECONDS` | Default and maximum 300, with one bounded pending transaction per browser. |
| Existing `SOURCE`, `INVITES_ENABLED`, `K_REVISION` | Fixture bypass refuses startup unless source=fixture, invites disabled, and K_REVISION absent. Real local logs require auth too. |

Missing/unsafe required Google settings fail startup; never silently bypass auth or fall back to public fixtures. Keys are stable across healthy replicas/restarts, not regenerated at process start. Construct source/provider clients lazily: no telemetry/discovery/JWKS/token network requests at app startup.

Fixture bypass must be bound to loopback, show a fixture-mode indicator and refuse non-loopback serving. Validate actual launcher/ASGI local binding, not a client-controlled Host header. Cloud Run's `0.0.0.0` binding and K_REVISION must never enable bypass. Tests should inject safe fake auth/provider/clock rather than depend on a production bypass.

## 5. Login transaction, verified identity and session

1. `GET /login` is a minimal accessible public page, with Google button, theme and generic retry/error text, no private navigation and zero source reads.
2. `GET /auth/google` generates unpredictable state, nonce and PKCE verifier with S256 challenge. Bind these, validated local return path and original issue/expiry times to a signed five-minute OAuth cookie. Replace the prior transaction; do not grow a list for every attempt.
3. Use fixed Google discovery metadata and scopes `openid email` only. Account chooser/login_hint is convenience, not authorization. Do not request offline access, refresh tokens, profile pictures or Google Cloud data/API scopes.
4. `GET /auth/callback` requires the bound unexpired transaction and matching state before exchanging the code with configured callback and PKCE verifier. Reject absent/duplicate/malformed security parameters. On cancel/failure/stale state clear the transaction and return a generic retry response without a console session.
5. Let the supported library validate signature/allowed algorithm/current Google keys, supported Google issuer, intended audience, authorized party where required, expiry, issued-at and nonce. Require nonempty `sub`, `email_verified is True` and normalized email exactly equal to the owner. String `"true"` is not boolean true. Unvalidated userinfo, an access token, query email or Google-looking header is not identity.
6. Use `sub` as the stable Google identity within the session; verified Gmail equality remains the owner authorization rule. Do not use `hd` or any `@gmail.com` suffix as the allowlist. A different verified user gets generic 403 and no console cookie, even if listed as a Google test user.
7. On success discard provider access/refresh/ID tokens, clear transaction cookie, create a fresh console cookie with minimal sub, owner email, original iat/exp and random session/CSRF identifier, then 303 to the safe local return path. Never serialize whole userinfo/tokens/credentials/telemetry into the session or logs.
8. Every protected request validates signature, schema, age/future timestamps, nonempty identity and current owner configuration before application work. Paging/refresh must not renew original iat/exp. Max-Age or a sliding serializer timestamp alone does not enforce one-hour absolute expiry.
9. `POST /auth/logout` requires the session CSRF token and exact configured Origin, clears console and pending OAuth cookies, and 303 redirects to /login. GET logout cannot mutate authentication.

Use separate HTTPS cookies such as `__Host-dashboard-session` and `__Host-dashboard-oauth`: HttpOnly, Secure, SameSite=Lax, Path=/, no Domain, bounded size/Max-Age. Distinct keys and signing purposes prevent substituting a transaction cookie for a session. Signed cookies are readable, not encrypted. HTTP loopback development uses distinct non-__Host- cookie names and no Secure flag only in explicit local mode; production rejects insecure settings.

Authlib requires session/state storage: adapt it to the short transaction cookie, not a long-lived cookie containing OAuth tokens or full userinfo. Test actual serialized fields and middleware order. Clear state on success/error and reject replayed callbacks/code exchanges. Cookie clearing is not strict cross-instance transaction revocation; Google's single-use code is also part of replay defense. Do not claim per-session revocation without a store.

Bound provider network timeouts, cache metadata/JWKS appropriately, and fail closed on outages, unknown keys or malformed responses. No unverified JWT fallback, indefinite redeemed-code retries or unbounded transaction state. Existing valid console sessions may continue until their own expiry during a Google outage.

## 6. Default-deny guard and every route/caller

Use one pure-ASGI guard wrapping all routers and mounts. Public exceptions are exact method/path or static path boundaries, never a broad `startswith("/auth")`. Unknown/new routes remain protected. Normal lifespan passes through; future websocket scopes require explicit owner authorization.

| Current surface | Unauthenticated behavior |
|---|---|
| `/`, `/errors`, `/requests`, `/assistant`, `/data`, `/access`, `/source` | Full HTML GET/HEAD: 303 to login with safe local return path. |
| `/requests/{request_id}`, `/crashes`, `/crashes/{issue_id}` | Same guard, including optional detail routes; no existence/data leak before auth. |
| `/partials/overview`, `/partials/errors`, `/partials/assistant`, `/partials/data`, `/partials/access`, `/partials/crashes`, `/partials/requests`, `/partials/request_rows` | 401 with `HX-Redirect: /login`. Both partial paths and HX-Request variants are covered; never insert a full login document inside a panel. |
| `GET /invites` / `POST /invites` when enabled | GET protected; POST 401 before body/dependency/store work. Owner POST also needs CSRF and exact trusted Origin, plain form and HTMX. |
| `POST /auth/logout` / any future writes | Valid owner session + CSRF + exact Origin. Missing/malformed/foreign Origin fails closed. All non-safe methods require authorization. |
| Other email in a valid signed session | 403, clear invalid-owner session, zero source/cache/store calls. |
| `/docs`, `/redoc`, `/openapi.json` | Disable in hosted mode or guard identically, including framework-created routes. |
| `/login`, `GET /auth/google`, `GET /auth/callback` | Exact public allowlist; any future /auth/* endpoint is protected unless deliberately reviewed. |
| `/static/…` | Only existing static mount with normal traversal protection; no secrets/config/private data placed here. |
| `/healthz` | Public minimal `{"status":"ok"}`, zero source reads. Current liveness exposes contract_version: remove that field publicly or put detail behind auth. There is no current /health route. |

Invites currently compare Origin netloc to Host and permit an absent Origin. Replace this with exact configured scheme/host/port validation plus a session-bound CSRF token using safe comparison. Update invite/logout hidden fields and HTMX headers/callers, not just server routes. Optional/local invites are not exempt. Provider callback uses state/nonce/PKCE rather than form-CSRF.

Validate next/return targets against external URLs, //host, backslashes, control characters, encoded/double-encoded bypasses and login loops; fallback to `/`. Configure trusted hosts and explicitly trust only the hosting proxy's forwarded input. Callback/origin/cookie security must come from configuration, not an untrusted request host.

Sensitive HTML, partials, auth responses/errors/redirects and invite results get `Cache-Control: no-store` (private where applicable). Static public assets can retain versioned caching. Add nosniff, frame denial/frame-ancestors, no-referrer, HTTPS HSTS and a CSP tested against existing theme bootstrap, chart JSON/scripts, HTMX and inline width styles. Prefer compatible nonces/hashes/explicit style allowances; never break charts or allow arbitrary script execution for convenience.

**HTMX/browser history:** HTMX push-url can save page snapshots in localStorage. Disable sensitive snapshots with `hx-history="false"` on the protected document; ensure history-cache-miss restores go through the same guard. Clear any existing application-owned sensitive HTMX history entries during migration/logout using the installed HTMX version's supported behavior; do not clear unrelated localStorage. Test actual logout/back/forward, HTMX restoration and browser bfcache in both themes. Cache-Control alone does not govern HTMX localStorage or prove browser memory was cleared; never claim downloaded telemetry can be recalled.

Auth/login/denial logs contain minimal outcome categories and pseudonymous identity only when needed. Suppress raw callback queries, codes/state, cookies, Authorization headers and provider payloads in app/uvicorn/error logs. Redirect promptly to a clean URL. App filtering does not redact Cloud Run's automatic request logs: inspect every retained/exported sink and configure narrow callback-request exclusions/redaction while keeping sanitized auth outcome logs. Block public promotion until verified; unit tests do not prove cloud log privacy.

## 7. OAuth client and secret setup (operator runbook)

Future authorized steps only; no real credentials are generated/read as part of this documentation task.

1. Open Google Auth Platform in the intended project. Configure branding/contact and External audience for personal Gmail; use Testing with only the owner where the current product supports it. Check current consent/testing requirements in the console. Provider test-user membership never replaces server allowlisting.
2. Create a **Web application** OAuth client. Prefer separate development and production clients. Register exact `http://127.0.0.1:8080/auth/callback` locally and `https://<canonical-dashboard-host>/auth/callback` in production. Scheme, port, path and trailing slash must match. No wildcard or Android client.
3. Request only openid email. Save the Google-created client secret privately outside the repository. It is not the Google account password, API key or service-account key.
4. Generate separate session/OAuth signing keys using the recipe below. Upload each and the client secret to separate Secret Manager secrets. Grant runtime Secret Accessor on those specific secrets only, never project-wide or on platform credentials.
5. Bind numeric secret versions to the matching Cloud Run environment variables. A newly added version alone does not update existing environment-bound instances: deploy a new revision. Record names/version numbers, never values. [Cloud Run secret configuration](https://docs.cloud.google.com/run/docs/configuring/services/secrets).

**Key-generation example (Bash/Cloud Shell, later operator execution):** run outside a repository; output files are temporary operator-only credentials, not committed .env examples. On Windows use an owner-only ACL location or Cloud Shell; chmod is not Windows ACL protection. No value is echoed.

~~~bash
umask 077
AUTH_PRIVATE_DIR="$(mktemp -d)"
export AUTH_PRIVATE_DIR
python3 - <<'PY'
import os
from pathlib import Path
import secrets

directory = Path(os.environ["AUTH_PRIVATE_DIR"])
for name in ("session-signing-key", "oauth-signing-key"):
    with (directory / name).open("x", encoding="ascii") as secret_file:
        secret_file.write(secrets.token_urlsafe(48))
PY
~~~

Set the intended non-secret `GCP_PROJECT_ID` before using templates. First creation uses `gcloud secrets create`; later rotation uses `versions add` with freshly generated files. Do not echo secrets, embed values in CLI arguments, enable shell tracing or paste values in a chat.

~~~bash
gcloud secrets create dashboard-session-signing-key --project "$GCP_PROJECT_ID" --replication-policy automatic --data-file "$AUTH_PRIVATE_DIR/session-signing-key"
gcloud secrets create dashboard-oauth-signing-key --project "$GCP_PROJECT_ID" --replication-policy automatic --data-file "$AUTH_PRIVATE_DIR/oauth-signing-key"
# Rotation example, after generating a fresh key file:
gcloud secrets versions add dashboard-session-signing-key --project "$GCP_PROJECT_ID" --data-file "$AUTH_PRIVATE_DIR/session-signing-key"
~~~

Use equivalent file/stdin handling for `dashboard-google-client-secret` with Google's generated value. After upload remove temporary files using the environment's appropriate practice; do not promise deletion securely erases SSD/cloud storage. If storing local development secrets, use an ignored operator-only file with explicit loading: current Config does not automatically load a .env file merely because one exists. Never copy secrets into fixtures/images/test outputs.

## 8. D7 transport, deployment sequencing and rollback

Cloud Run invoker IAM and application Google OIDC are different credentials/audiences. An app cookie does not pass a private Cloud Run edge; an invoker identity token does not replace the owner app session. [Cloud Run end-user authentication](https://docs.cloud.google.com/run/docs/authenticating/end-users).

At the checked main revision, `deploy/deploy.sh` uses `--no-allow-unauthenticated`, `--invoker-iam-check`, `--set-env-vars`, `--to-latest` and `require_private`. PR #29 changes redeploy setting preservation; integrate its final behavior before D9. D9 must deliberately change the transport/promotion contract and behavioral tests. Do not append a contradictory public flag, replace all environment variables and lose auth config, or send traffic to an unverified latest image.

Keep private as the default deployment mode. Add explicit validated `DASHBOARD_TRANSPORT=app-auth` only for a verified Google-auth image. It requires full auth configuration/secret bindings and policy/config readback; failed reads abort rather than look like empty safe policies. If public promotion is approved, keep invoker checks enabled and use only a service-scoped allUsers/roles/run.invoker binding for this dashboard. Do not also disable checks or broaden project IAM. If policy forbids it, retain IAM/proxy access.

1. Finish D9 code slices, exact-head review, CI and production image build. Read actual project/region/origin from ignored operator config, not guesses or committed credentials.
2. Deploy pinned digest to a candidate with `--no-traffic` while transport remains private. Preserve runtime account, telemetry config, min=0/max=1. Bind numeric secret versions and AUTH_MODE=google. Cloud invites stay disabled. Startup stays network-free.
3. Check candidate readiness/config and app-denial behavior through authorized operator transport (proxy/tag access as deliberately configured). An untagged no-traffic revision is not automatically reachable. A complete hosted browser callback cannot be proved behind an IAM edge the browser cannot pass.
4. Verify real Google flow locally using the development Web client and fixtures, plus offline security tests. For production, send 100% only to the fully guarded candidate **while still private**; remove tags/aliases that expose any old pre-auth revision.
5. Only after explicit deployment/IAM authorization, enable public HTTP transport on this dashboard service for login/callback. Never expose an old image first. Backend API/databases/telemetry services stay untouched.
6. Immediately test owner sign-in, separate signed-out/non-owner browsers, direct service URL/approved aliases, partial/detail/write denials, expiry/logout/history and absence of sensitive logs. If failure occurs, restore private transport first. If browser access is unavailable, keep this launch slice pending.
7. Preserve narrow Logging/Error Reporting/custom Trace reader roles. D9 adds only per-secret read access; no Firestore, telemetry writes or new Crashlytics permissions. Keep INVITES_ENABLED=false; hosted invite writing is a separate least-privilege decision.
8. Record commit/digest/revision, origin, traffic/tag map, policy readback, secret version numbers and positive/negative evidence without credential values. A guide, merged code or successful image build alone is not deployed owner login.

Traffic tags can reach revisions at 0% traffic. Enumerate/remove old pre-auth and old-key tagged URLs before public access and after key rotation. Every reachable revision must enforce the current intended boundary.

Rollback to a known good auth-enabled revision by explicit name. If only pre-auth code is available, remove public invoker access, ensure invoker checks enabled, verify anonymous requests blocked, then roll back privately. Never choose --to-latest as an emergency guess. Rolling back to old signing keys can revive stolen cookies; redeploy good code with fresh versions instead.

## 9. Secret rotation and troubleshooting

| Symptom | Action |
|---|---|
| `redirect_uri_mismatch` | Compare canonical origin, callback and Web client registration exactly, including port/trailing slash. No wildcard/Host-based workaround. |
| `invalid_client` / secret unavailable | Check the correct client/secret pair, enabled numeric version, per-secret runtime permission and deployed binding. Do not log secret values. |
| Missing state / redirect loop | Check five-minute lifetime, cookie host/name/flags, forwarded scheme trust and browser cookie settings. Retry from login; never disable state/nonce/PKCE. |
| Google succeeds, console 403 | Verify selected account and server-verified owner claim; consent is not authorization. Do not print the full ID token. |
| Cloud Run 403 before /login | Transport is private or ingress disallows access. Use IAM proxy until controlled promotion; an application password reset cannot fix it. |
| 401 after one hour | Expected absolute expiry. HTMX redirects to login; sign in again. |
| Google outage | Generic retryable login failure, no public data fallback or unverified token acceptance. |

**Signing-key rotation:** generate fresh independent files, add new secret versions, deploy a candidate pinned to them, verify new login/old-cookie denial, promote all serving traffic, remove old-key tags, then retire old versions when no valid consumer needs them. Never retain a compromised verification fallback key. Session-key rotation signs everyone out; OAuth-key rotation cancels pending logins. These are acceptable for a single owner.

**Google client-secret rotation:** rotate/create the Web client's secret in Google Auth Platform, privately upload its new version, bind a new revision, test a fresh login, then retire the old client secret under Google's current supported workflow. It affects new code exchanges, not existing console sessions. If compromised, rotate session keys as needed for containment. Do not generate an OAuth client secret with the random application-key recipe.

Immediate containment can restore private edge access while rotating keys and removing old reachable revisions. Already downloaded data and in-flight responses cannot be recalled. New secret versions, Google password changes, consent revocation and local logout alone are not proof that copied console cookies stopped working.

## 10. Ordered prompts for DeepSeek

Give DeepSeek this **whole file** as context, then execute one slice at a time. Each coding slice includes validation, a conventional commit, a push and a focused PR into `main`; do not leave completed work only on the local machine. Follow the human's current instructions and repository merge protections. Administrator overrides, real-secret provisioning, IAM changes and deployment require the relevant explicit authorization. Preserve unrelated work and review each slice before starting dependent work; do not widen into new auth features.

### D9.1 — Decision, typed policy and configuration

Prompt: “Implement D9.1 only against current main. Read create_app, Config, Clock, dependencies and deployment tests. Add the ADR, validated auth settings, minimal immutable identity/session models and a typed provider interface. Required hosted config fails closed. Add tests first and placeholders only; create no real secrets and change no live IAM. Preserve source/service behavior.”

Likely files: `app/config.py`, `app/domain/auth.py`, `app/services/auth.py`, `.env.example`, ADR and matching config/domain/service tests. Domain imports no app modules. Update test configuration explicitly for the secure default; do not let existing tests make Google network calls.

Acceptance: missing/equal/weak keys, callback mismatch, unsafe origin, wildcard/malformed owner and forbidden bypass rejected. Valid safe config accepted; startup stays network-free. ADR explicitly records no dashboard password, stateless limits and D7 migration.

### D9.2 — Google provider and five-minute transaction

Prompt: “Implement supported Google OIDC adapter and bounded signed login transaction. Add justified runtime Authlib/httpx/itsdangerous with compatible lockfile. Use discovery, S256 PKCE, bound state/nonce and configured callback. Test real library validation with fake HTTP/keys and injected clock/randomness; never save/expose provider tokens or write JWT crypto.”

Likely files: `app/auth/google.py`, `app/auth/transactions.py`, provider/service tests, `pyproject.toml` and `uv.lock`. Keep adapter small and typed, not a general identity framework.

Acceptance: verified owner accepted; other email, false/missing/string verification, wrong issuer/audience/azp/nonce/signature/algorithm, empty sub, expiry/future token, invalid/missing/expired state, bad PKCE, duplicate callback parameters, cancel/outage/malformed provider responses denied. Tests exercise actual adapter validation, not just an always-trusting fake.

### D9.3 — Login UI/routes, absolute session and logout

Prompt: “Implement /login, /auth/google, /auth/callback and POST logout using verified identity/transaction contracts. Add minimal theme-compatible public login UI without private shell/source reads. Use separate signed console cookie, absolute original expiry, safe return validation, CSRF logout and generic errors. Test actual serialized cookie contents, flags and logs.”

Likely files: `app/routers/auth.py`, `app/auth/sessions.py`, login template/minimal CSS, app wiring and router/session tests. Follow current module conventions; split provider/cookie/routing responsibilities.

Acceptance: owner flow succeeds offline; no OAuth tokens/full claims in cookie/HTML/logs; forged/expired/future/malformed/cross-purpose cookies fail. Requests do not renew expiry. Transaction clears on success/error; replay fails. Logout validates Origin/CSRF and expires correct cookies; GET logout and malicious next cannot mutate session/leave site.

### D9.4 — Global authorization, writes, headers and history

Prompt: “Install pure-ASGI default-deny guard around all routes/mounts with correct ordering. Enforce exact public exceptions, minimal /healthz, guarded/disabled docs, HTMX 401 redirect and no-store/security policy. Protect invites/logout before body/dependency/store work using CSRF plus exact configured Origin. Update forms/HTMX callers and disable sensitive history snapshots; no production bypass to preserve tests.”

Likely files: `app/middleware/auth.py`, app wiring/auth dependencies, health/invite routers, invite/sidebar logout templates, protected document/header helper and route tests. Inspect every include_router/mount, optional route, page refresh, pagination and detail caller, including the merged requests side panel and crash detail routes.

Acceptance: enumerate all routes/mounts for fixture/real-source fakes, invites on/off and crashes on/off; unauthorized requests trigger zero source/cache/store/body work. Cover all methods/HX variants, forged identity/forwarded headers, prefix/traversal bypasses, optional details, CSRF/Origin failures and docs. Add a new synthetic route to prove default protection. Owner functionality works. History-cache-miss restores guarded; no new sensitive HTMX localStorage snapshots.

### D9.5 — Deployment safety and operator documentation

Prompt: “Refactor D7 scripts and behavioral fake-gcloud tests for private-default/explicit app-auth transport. Preserve telemetry/runtime/scaling/env settings and numeric secret bindings. Candidate deploy must not auto-promote; failed build/deploy/policy reads stop later mutations. Document owner setup/recovery, rotation, tag retirement and private-first rollback. Prepare commands/evidence checklist; do not execute cloud changes under this coding slice.”

Likely files: `deploy/deploy.sh` or a small focused helper, `deploy/.env.deploy.example`, deploy README, D7/D9 guides, main/guide README access notes and `tests/test_deploy_behaviour.py`. Coordinate with existing local doc owners instead of overwriting them. Current README/index already link D9; avoid unnecessary navigation churn.

Acceptance: fake-gcloud tests prove private default, explicit opt-in, no lost auth/env/secrets, correct candidate/promotion order, no public-old-image window, tag checks, policy-read fail-closed behavior and rollback boundary. Only per-secret reads added. Production image includes runtime auth dependencies and safely refuses missing config.

### D9.6 — Real owner verification and controlled launch

Prompt: “After exact-head review/CI, follow section 8 with the owner/authorized operator. Test local Google flow, private candidate readiness/denials, then only explicitly approved protected deployment/transport promotion. Verify owner/non-owner/signed-out access, partial/detail/write boundaries, expiry, logout/back/bfcache/HTMX, direct URLs/aliases, logs and key rotation. If browser/deployment access is unavailable, mark launch pending and keep IAM/proxy.”

Evidence identifies commit/digest/revision/date, tested accounts by role, paths, secret versions, traffic tags and policy readback without secrets. A screenshot or 200 response without negative checks is insufficient. Documentation completion does not imply deployed authentication.

## 11. Verification and definition of done

Use current CI commands and frozen lockfile install after dependency changes; build the runtime image, not only a developer environment.

~~~bash
uv sync --frozen --extra dev
uv run ruff check .
uv run black --check .
uv run mypy app tests
uv run pytest --cov=app --cov-report=term-missing
docker build --tag football-dashboard:d9-review .
~~~

Preserve Python 3.12, strict types, documented public APIs and current layering; no runtime dependency beyond the selected auth stack without a reason. Code files ≤400 lines/functions ≤40, app coverage ≥80%. Do not skip/weaken/delete existing tests. Mutation-check representative owner/expiry/CSRF branches in an isolated copy and restore; corresponding tests must fail. Browser checks supplement offline security tests, not replace them.

- [ ] Guide/ADR intentionally tracked in a reviewed PR; current main/PR integrations checked.
- [ ] Google login works with exact owner; no password/reset/email/signup system added.
- [ ] Invalid/unverified/other identities denied before all data/cache/store work.
- [ ] Full pages, partials, details, optional writes, framework docs and new routes guarded by default.
- [ ] State/nonce/PKCE, bounded transaction, absolute expiry, cookie flags, CSRF, safe redirects and security headers verified.
- [ ] Provider access/refresh/ID tokens and client/signing secret values absent from console cookies, templates and logs. Only the specified state/nonce/PKCE transaction fields may use the short OAuth cookie; session/CSRF identifiers remain permitted. Callback codes/state and all cookie values are absent from app/retained/exported request logs.
- [ ] Offline tests, actual runtime build and real owner/non-owner browser flow recorded.
- [ ] HTMX localStorage/history, logout/back/forward and bfcache behavior tested without claiming downloaded data erased.
- [ ] Private-to-public sequence and rollback verified; no pre-auth/old-key traffic-tag route remains reachable.
- [ ] Pinned secrets/per-secret IAM checked; cloud invites disabled; no backend permissions broadened.
- [ ] Google account recovery vs session/client-secret rotation documented/exercised with stateless limits.

Until evidence exists, report **D9 implementation/deployment pending**, not dashboard end-to-end complete. Updating this file completes the requested planning handoff only.

## 12. Primary references (checked 19 October 2026)

- [Google OIDC flow and ID-token claims/validation](https://developers.google.com/identity/openid-connect/openid-connect) and [Web OAuth client/callback setup](https://developers.google.com/identity/protocols/oauth2/web-server).
- [Authlib Starlette OIDC](https://docs.authlib.org/en/v1.6.7/client/starlette.html) and [PKCE integration](https://docs.authlib.org/en/stable/oauth2/client/web/index.html): verify chosen pinned version before coding; example documentation version is not a required dependency pin.
- [Starlette middleware/session behavior](https://starlette.dev/middleware/), [HTMX sensitive-history prevention](https://htmx.org/attributes/hx-history/) / [history restoration](https://htmx.org/docs/#history), and [Python secrets](https://docs.python.org/3/library/secrets.html).
- [Cloud Run IAM](https://docs.cloud.google.com/run/docs/securing/managing-access), [end-user authentication](https://docs.cloud.google.com/run/docs/authenticating/end-users), [secret bindings](https://docs.cloud.google.com/run/docs/configuring/services/secrets) and [traffic/tag rollback](https://docs.cloud.google.com/run/docs/rollouts-rollbacks-traffic-migration).
- [Cloud Logging HTTP request fields](https://docs.cloud.google.com/logging/docs/reference/v2/rest/v2/LogEntry#httprequest) and [routing/exclusions](https://docs.cloud.google.com/logging/docs/routing/overview): platform query logging requires independent verification.
- [Google password change/reset](https://support.google.com/accounts/answer/41078?hl=en), [account recovery](https://accounts.google.com/signin/recovery) and [backup codes](https://support.google.com/accounts/answer/1187538?hl=en).

This documentation publication adds no authentication code, real credentials, OAuth client, cloud policy/public-access change or deployment. Execute and verify the D9 implementation slices before claiming owner-only dashboard login works.
