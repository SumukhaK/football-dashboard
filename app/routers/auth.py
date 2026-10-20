"""The sign-in routes: the public login page, Google's two hops and logout.

The router is deliberately thin. The provider owns Google and the five-minute
transaction; ``SessionCookie`` owns the console cookie; this module only moves
between them. It reads no telemetry, renders no private navigation, and logs a
generic outcome rather than a code, state, cookie or address.

These routes are public by design (D9.4 puts the guard around everything else).
``POST /auth/logout`` is the only mutating endpoint and it requires the exact
configured Origin plus the CSRF token carried in the session.
"""

from __future__ import annotations

import hmac
import logging
import secrets
from typing import cast
from urllib.parse import parse_qs

import fastapi
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.auth.google import GoogleOIDC, parse_callback, safe_return_path
from app.auth.sessions import (
    SessionCookie,
    cookie_security,
    oauth_cookie_name,
    session_cookie_name,
)
from app.auth.transactions import TransactionCookie
from app.config import Config
from app.domain.auth import LoginTransaction, VerifiedIdentity
from app.services.auth import AuthFailure, AuthPolicy, IdentityProvider
from app.templating import templates

router = fastapi.APIRouter(tags=["auth"])
logger = logging.getLogger("app.auth")

NO_STORE = {"Cache-Control": "no-store"}
RETRY_URL = "/login?retry=1"

RETRY_TEXT = "Sign-in didn't complete. Please try again."
DENIED_TEXT = "That account does not have access to this console."
UNAVAILABLE_TEXT = "Sign-in is not configured on this console."
REFUSED_TEXT = "That request could not be completed."


def _settings(request: Request) -> Config:
    return cast(Config, request.app.state.config)


def _configured(settings: Config) -> bool:
    """Whether the Google settings are present, so a route may call a provider."""
    return not settings.missing_google_auth()


def _provider(request: Request) -> IdentityProvider:
    """The provider seam, built on first use and then kept on the app.

    Building makes no network call; discovery, JWKS and the token endpoint are
    fetched lazily by the adapter itself.
    """
    state = request.app.state
    if state.auth_provider is None:
        state.auth_provider = GoogleOIDC(
            state.config,
            AuthPolicy.from_config(state.config),
            clock=state.clock,
        )
    return cast(IdentityProvider, state.auth_provider)


def _page(
    request: Request,
    *,
    status_code: int = 200,
    notice: str | None = None,
    next_path: str = "/",
) -> HTMLResponse:
    """The minimal public login page, never cached."""
    return templates.TemplateResponse(
        request,
        "login.html",
        {"notice": notice, "next_path": safe_return_path(next_path)},
        status_code=status_code,
        headers=NO_STORE,
    )


def _clear(response: Response, settings: Config, *, session: bool = True) -> Response:
    """Expire the auth cookies on a response about to be returned."""
    flags = cookie_security(settings)
    names = [oauth_cookie_name(settings)]
    if session:
        names.append(session_cookie_name(settings))
    for name in names:
        response.delete_cookie(
            name,
            path=flags["path"],
            secure=flags["secure"],
            httponly=flags["httponly"],
            samesite=flags["samesite"],
        )
    return response


def _retry(settings: Config) -> Response:
    """Clear the pending attempt and send the browser to a clean retry page."""
    response = RedirectResponse(RETRY_URL, status_code=303, headers=NO_STORE)
    return _clear(response, settings, session=False)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    """The public sign-in page: no shell, no navigation, no source read."""
    return _page(
        request,
        notice=RETRY_TEXT if request.query_params.get("retry") == "1" else None,
        next_path=request.query_params.get("next", "/"),
    )


@router.get("/auth/google")
async def start_login(request: Request) -> Response:
    """Begin a sign-in and send the browser to Google with a signed attempt."""
    settings = _settings(request)
    if not _configured(settings):
        return _page(request, status_code=503, notice=UNAVAILABLE_TEXT)

    try:
        start = await _provider(request).start(request.query_params.get("next", "/"))
    except AuthFailure as error:
        return _failure(request, settings, error)
    codec = TransactionCookie.from_config(settings, request.app.state.clock)
    response = RedirectResponse(
        start.authorization_url, status_code=303, headers=NO_STORE
    )
    response.set_cookie(
        oauth_cookie_name(settings),
        codec.dumps(start.transaction),
        max_age=settings.oauth_transaction_max_age_seconds,
        **cookie_security(settings),
    )
    logger.info("sign-in started")
    return response


@router.get("/auth/callback")
async def callback(request: Request) -> Response:
    """Check the attempt, exchange the code and start a console session."""
    settings = _settings(request)
    if not _configured(settings):
        return _page(request, status_code=503, notice=UNAVAILABLE_TEXT)

    transaction = _transaction(request, settings)
    if transaction is None:
        logger.warning("sign-in failed: transaction")
        return _retry(settings)
    try:
        identity = await _finish(request, transaction)
    except AuthFailure as error:
        return _failure(request, settings, error)
    return _signed_in(request, settings, transaction, identity)


def _transaction(request: Request, settings: Config) -> LoginTransaction | None:
    """The pending attempt this browser carries, or None when it cannot be used."""
    value = request.cookies.get(oauth_cookie_name(settings))
    if value is None:
        return None
    codec = TransactionCookie.from_config(settings, request.app.state.clock)
    try:
        return codec.loads(value)
    except AuthFailure:
        return None


async def _finish(request: Request, transaction: LoginTransaction) -> VerifiedIdentity:
    """Read the callback parameters and let the provider verify the code."""
    parameters = parse_callback(request.url.query)
    return await _provider(request).finish(
        parameters.code, parameters.state, transaction
    )


def _failure(request: Request, settings: Config, error: AuthFailure) -> Response:
    """Turn a named failure into a generic page or retry, and clear the attempt."""
    if error.kind == "identity":
        logger.warning("sign-in denied: identity")
        response = _page(request, status_code=403, notice=DENIED_TEXT)
        return _clear(response, settings)
    logger.warning("sign-in failed: %s", error.kind)
    return _retry(settings)


def _signed_in(
    request: Request,
    settings: Config,
    transaction: LoginTransaction,
    identity: VerifiedIdentity,
) -> Response:
    """Create the one-hour session, clear the attempt and return to the page."""
    clock = request.app.state.clock
    policy = AuthPolicy.from_config(settings)
    session = policy.new_session(identity, secrets.token_urlsafe(32), clock)
    response = RedirectResponse(
        transaction.return_path, status_code=303, headers=NO_STORE
    )
    response.set_cookie(
        session_cookie_name(settings),
        SessionCookie.from_config(settings, clock).dumps(session),
        max_age=settings.session_max_age_seconds,
        **cookie_security(settings),
    )
    _clear(response, settings, session=False)
    logger.info("sign-in accepted")
    return response


@router.post("/auth/logout")
async def logout(request: Request) -> Response:
    """End the session, but only for this Origin and with its CSRF token."""
    settings = _settings(request)
    if not _configured(settings):
        return _page(request, status_code=503, notice=UNAVAILABLE_TEXT)
    if request.headers.get("origin") != settings.auth_public_origin:
        logger.warning("sign-out refused: origin")
        return _page(request, status_code=403, notice=REFUSED_TEXT)

    clock = request.app.state.clock
    value = request.cookies.get(session_cookie_name(settings))
    if value is None:
        logger.info("sign-out without a session")
        return _clear(RedirectResponse("/login", 303, headers=NO_STORE), settings)
    try:
        session = SessionCookie.from_config(settings, clock).loads(value)
    except AuthFailure:
        logger.warning("sign-out refused: session")
        return _clear(RedirectResponse("/login", 303, headers=NO_STORE), settings)

    fields = parse_qs((await request.body()).decode(errors="replace"))
    submitted = fields.get("csrf_token", [""])[0]
    matches = bool(submitted) and hmac.compare_digest(
        session.session_id.encode(), submitted.encode()
    )
    if not matches:
        logger.warning("sign-out refused: csrf")
        return _page(request, status_code=403, notice=REFUSED_TEXT)

    logger.info("sign-out accepted")
    return _clear(RedirectResponse("/login", 303, headers=NO_STORE), settings)
