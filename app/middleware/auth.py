"""The default-deny guard and the response security policy.

One pure-ASGI middleware wraps every router and mount. It reads the signed
session cookie, checks it against the current owner policy, and either passes
the request to the application or answers before any route, dependency, body
parse, source read or store write. The public surface is an exact list of
GET/HEAD paths plus the existing static mount; a new route is protected unless
it is deliberately added here.

The same wrapper applies the response policy: a nonce-based CSP, nosniff,
frame denial, no-store for everything but static assets, and HSTS on a hosted
HTTPS origin. Protected successful documents use ``Referrer-Policy:
same-origin`` so a native form POST keeps its exact Origin; login, OAuth,
health, refusals and errors keep ``no-referrer``. The nonce is put in
``scope["state"]`` before the route renders, so inline theme and chart-data
scripts can carry it.
"""

from __future__ import annotations

import logging
import secrets
from http.cookies import CookieError, SimpleCookie
from typing import cast
from urllib.parse import quote, unquote

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.sessions import SessionCookie, local_auth, session_cookie_name
from app.config import Config
from app.domain.auth import ConsoleSession
from app.domain.clock import Clock
from app.services.auth import AuthFailure, AuthPolicy

logger = logging.getLogger("app.auth")

PUBLIC_PATHS = frozenset(
    {"/login", "/auth/google", "/auth/callback", "/health", "/healthz"}
)
GET_OR_HEAD = frozenset({"GET", "HEAD"})
REFERRER_POLICY_DOCUMENT = "same-origin"
REFERRER_POLICY_SENSITIVE = "no-referrer"
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'nonce-{nonce}'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; "
    "object-src 'none'"
)


def response_nonce(scope: Scope) -> str:
    """The request's CSP nonce, creating one for an outer error boundary."""
    state = scope.setdefault("state", {})
    nonce = state.get("csp_nonce")
    if isinstance(nonce, str) and nonce:
        return nonce
    nonce = secrets.token_urlsafe(16)
    state["csp_nonce"] = nonce
    return nonce


def apply_response_policy(
    headers: MutableHeaders,
    *,
    path: str,
    status_code: int,
    nonce: str,
    hosted: bool,
) -> None:
    """Apply the one authoritative policy to a response's headers."""
    headers.setdefault("x-content-type-options", "nosniff")
    headers.setdefault("x-frame-options", "DENY")
    headers.setdefault("referrer-policy", _referrer_policy(path, status_code))
    headers.setdefault(
        "content-security-policy",
        CONTENT_SECURITY_POLICY.format(nonce=nonce),
    )
    if hosted:
        headers.setdefault(
            "strict-transport-security", "max-age=31536000; includeSubDomains"
        )
    if not _is_static(path):
        headers["cache-control"] = "no-store"


def policy_sender(send: Send, scope: Scope, *, nonce: str, hosted: bool) -> Send:
    """Wrap ``send`` so every response start carries the response policy."""

    async def wrapped(message: Message) -> None:
        if message["type"] == "http.response.start":
            apply_response_policy(
                MutableHeaders(scope=message),
                path=str(scope.get("path", "/")),
                status_code=int(message["status"]),
                nonce=nonce,
                hosted=hosted,
            )
        await send(message)

    return wrapped


def _referrer_policy(path: str, status_code: int) -> str:
    """Protected documents need same-origin; auth and errors stay stricter."""
    if status_code == 200 and path not in PUBLIC_PATHS and not _is_static(path):
        return REFERRER_POLICY_DOCUMENT
    return REFERRER_POLICY_SENSITIVE


class AuthGuardMiddleware:
    """Deny by default, then apply the console's response security policy."""

    def __init__(self, app: ASGIApp, *, settings: Config, clock: Clock) -> None:
        self.app = app
        self.settings = settings
        self.clock = clock
        self.policy = AuthPolicy.from_config(settings)
        self.cookie_name = session_cookie_name(settings)
        self.hosted = (settings.auth_public_origin or "").startswith("https://")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind == "lifespan":
            await self.app(scope, receive, send)
            return
        if kind == "websocket":
            # No websocket is offered; one added later must be authorized
            # explicitly rather than inherit an unauthenticated connection.
            await send({"type": "websocket.close", "code": 1008})
            return
        if kind != "http":
            await self.app(scope, receive, send)
            return

        nonce = secrets.token_urlsafe(16)
        scope.setdefault("state", {})["csp_nonce"] = nonce
        path = str(scope.get("path", "/"))
        method = str(scope.get("method", "GET")).upper()

        if self._public(method, path):
            await self.app(scope, receive, self._sender(send, scope, nonce))
            return

        session, carried = self._session(scope)
        if session is not None:
            problem = self.policy.problem(session, self.clock())
            if problem is None:
                scope["state"]["auth_session"] = session
                await self.app(scope, receive, self._sender(send, scope, nonce))
                return
            if problem == "identity":
                logger.warning("request denied: identity")
                await self._reply(scope, send, nonce, 403, b"Forbidden", expire=carried)
                return

        await self._unauthorized(scope, send, nonce, carried)

    def _public(self, method: str, path: str) -> bool:
        """The exact public exceptions; everything else needs the owner."""
        if method not in GET_OR_HEAD:
            return False
        return path in PUBLIC_PATHS or _public_static(path)

    def _session(self, scope: Scope) -> tuple[ConsoleSession | None, bool]:
        """The session this browser carries, and whether it carried one at all."""
        value = _cookie(scope, self.cookie_name)
        if value is None:
            return None, False
        try:
            codec = SessionCookie.from_config(self.settings, self.clock)
            return codec.loads(value), True
        except (AuthFailure, ValueError):
            return None, True

    async def _unauthorized(
        self, scope: Scope, send: Send, nonce: str, carried: bool
    ) -> None:
        """Send a page to /login, or a header redirect for an HTMX panel."""
        method = str(scope.get("method", "GET")).upper()
        path = str(scope.get("path", "/"))
        if method in GET_OR_HEAD and not self._panel_request(scope):
            target = path
            query = scope.get("query_string", b"").decode("latin-1")
            if query:
                target = f"{path}?{query}"
            location = "/login?next=" + quote(target, safe="")
            await self._reply(
                scope, send, nonce, 303, b"", location=location, expire=carried
            )
            return
        await self._reply(
            scope,
            send,
            nonce,
            401,
            b"Authentication required",
            hx_redirect=True,
            expire=carried,
        )

    def _panel_request(self, scope: Scope) -> bool:
        """A partial path or an HTMX request must not receive a login document."""
        path = str(scope.get("path", "/"))
        if path == "/partials" or path.startswith("/partials/"):
            return True
        return _header(scope, b"hx-request") == "true"

    def _sender(self, send: Send, scope: Scope, nonce: str) -> Send:
        """Apply the response policy to whatever the application sends."""
        return policy_sender(send, scope, nonce=nonce, hosted=self.hosted)

    async def _reply(
        self,
        scope: Scope,
        send: Send,
        nonce: str,
        status: int,
        body: bytes,
        *,
        location: str | None = None,
        hx_redirect: bool = False,
        expire: bool = False,
    ) -> None:
        """A guard-owned response, carrying the same policy as the app's."""
        headers = MutableHeaders()
        headers["content-type"] = "text/plain; charset=utf-8"
        if location is not None:
            headers["location"] = location
        if hx_redirect:
            headers["hx-redirect"] = "/login"
        if expire:
            headers.append("set-cookie", self._expired_cookie())
        reply = policy_sender(send, scope, nonce=nonce, hosted=self.hosted)
        await reply(
            {"type": "http.response.start", "status": status, "headers": headers.raw}
        )
        head = scope.get("method") == "HEAD"
        await reply({"type": "http.response.body", "body": b"" if head else body})

    def _expired_cookie(self) -> str:
        """A deletion for the session cookie, with the same name and flags."""
        secure = "" if local_auth(self.settings) else "; Secure"
        return (
            f"{self.cookie_name}=; Path=/; Max-Age=0; "
            "Expires=Thu, 01 Jan 1970 00:00:00 GMT; "
            f"HttpOnly; SameSite=lax{secure}"
        )


def _header(scope: Scope, name: bytes) -> str | None:
    """One request header, decoded, without trusting its case."""
    headers = cast(list[tuple[bytes, bytes]], scope.get("headers") or [])
    for key, value in headers:
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def _cookie(scope: Scope, name: str) -> str | None:
    """One cookie from the request header, or None when absent or malformed."""
    raw = _header(scope, b"cookie")
    if not raw:
        return None
    jar = SimpleCookie()
    try:
        jar.load(raw)
    except CookieError:
        return None
    morsel = jar.get(name)
    return morsel.value if morsel is not None else None


def _is_static(path: str) -> bool:
    """Whether this path belongs to the one static mount."""
    return path == "/static" or path.startswith("/static/")


def _public_static(path: str) -> bool:
    """Whether this is a plain static asset path, without a traversal segment."""
    if not _is_static(path):
        return False
    return all(_static_segment(part) for part in path.split("/")[1:])


def _static_segment(part: str) -> bool:
    """One static path segment that cannot escape the mount or hide a file.

    The segment is decoded first so ``%2e%2e`` cannot smuggle a ``..`` past a
    check that only looks at the raw scope path.
    """
    decoded = unquote(part)
    return (
        bool(decoded)
        and decoded not in {".", ".."}
        and not decoded.startswith(".")
        and "/" not in decoded
        and "\\" not in decoded
        and "\x00" not in decoded
    )
