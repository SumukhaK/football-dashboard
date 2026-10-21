"""The Google OpenID Connect adapter: one owner, one five-minute attempt.

Authlib owns the discovery document, the authorization URL, S256 PKCE, the
code exchange and the ID-token validation (signature, allowed algorithm,
issuer, audience, authorized party, expiry and nonce). This module supplies
only the pieces Authlib's Starlette integration would normally keep in a
server-side session: our own signed transaction carries the state, nonce and
verifier, so the console needs no session store for a pending sign-in.

No token leaves this adapter. The verified identity is a frozen value with a
subject, an address and the verification flag, and nothing else.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

import httpx
from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.starlette_client import OAuth
from authlib.integrations.starlette_client.apps import StarletteOAuth2App
from joserfc.errors import JoseError

from app.config import Config
from app.domain.auth import LoginStart, LoginTransaction, VerifiedIdentity
from app.domain.clock import Clock, system_clock
from app.services.auth import AuthFailure, AuthPolicy

GOOGLE_DISCOVERY = "https://accounts.google.com/.well-known/openid-configuration"
GOOGLE_ISSUER = "https://accounts.google.com"
_TOKEN_TIMEOUT_SECONDS = 10.0

# Everything a provider step may raise is mapped to one generic category: the
# log line says "provider", never the payload, the code or a token.
#
# TypeError and KeyError are here because the pinned Authlib 1.9.1/joserfc
# 1.7.7 pair raises them for a malformed discovery, JWKS or token document
# (a list document, a key set without "keys" or with null "keys"). They are
# caught only around provider I/O; our own validation raises AuthFailure,
# which is not in this tuple and is therefore never swallowed.
_PROVIDER_ERRORS = (
    OAuthError,
    httpx.HTTPError,
    JoseError,
    RuntimeError,
    ValueError,
    KeyError,
    TypeError,
)


class CallbackParameters(NamedTuple):
    """The two security parameters a callback may carry, once each."""

    code: str
    state: str


def parse_callback(query: str) -> CallbackParameters:
    """Read ``code`` and ``state``, refusing duplicates and cancellation.

    Duplicates are refused rather than taking the first or last value: which
    one a proxy or a library picked would otherwise decide the security
    parameter for us. A provider error is reported as a cancellation, and
    never reaches a token exchange.
    """
    from urllib.parse import parse_qs

    params = parse_qs(query, keep_blank_values=True)
    if params.get("error"):
        raise AuthFailure("cancelled")
    codes = params.get("code", [])
    states = params.get("state", [])
    if len(codes) != 1 or len(states) != 1 or not codes[0] or not states[0]:
        raise AuthFailure("request")
    return CallbackParameters(code=codes[0], state=states[0])


def safe_return_path(value: str) -> str:
    """The local path a sign-in may return to, or ``/``.

    Only a path on this site is accepted: an absolute URL, a protocol-relative
    ``//host``, a backslash (which some parsers read as a slash) and control
    characters all fall back to the root rather than becoming a redirect.
    """
    candidate = value.strip()
    if (
        not candidate.startswith("/")
        or candidate.startswith("//")
        or "\\" in candidate
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in candidate)
    ):
        return "/"
    return candidate


class GoogleOIDC:
    """The supported Google OIDC flow, with our transaction instead of a session."""

    def __init__(
        self,
        settings: Config,
        policy: AuthPolicy,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Clock = system_clock,
        token_factory: Callable[[int], str] = secrets.token_urlsafe,
    ) -> None:
        if settings.google_client_id is None or settings.google_client_secret is None:
            raise ValueError("Google sign-in needs a client id and secret")
        if settings.auth_callback_url is None:
            raise ValueError("Google sign-in needs auth_callback_url")
        self._client_id = settings.google_client_id
        self._callback = settings.auth_callback_url
        self._policy = policy
        self._clock = clock
        self._token = token_factory
        client_kwargs: dict[str, Any] = {
            "scope": "openid email",
            "code_challenge_method": "S256",
            "timeout": _TOKEN_TIMEOUT_SECONDS,
        }
        if transport is not None:
            client_kwargs["transport"] = transport
        # Registering makes no request: discovery, JWKS and the token endpoint
        # are fetched lazily, so building the app never touches the network.
        oauth = OAuth()
        self._app: StarletteOAuth2App = oauth.register(
            "google",
            client_id=self._client_id,
            client_secret=settings.google_client_secret.get_secret_value(),
            server_metadata_url=GOOGLE_DISCOVERY,
            client_kwargs=client_kwargs,
        )

    async def start(self, return_path: str) -> LoginStart:
        """Build the signed transaction and the Google authorization URL."""
        try:
            rv = await self._app.create_authorization_url(
                self._callback,
                state=self._token(32),
                nonce=self._token(24),
                code_verifier=self._token(48),
            )
        except _PROVIDER_ERRORS:
            # Suppress the provider's exception in the rendered chain: its
            # message and transport detail are not the caller's business.
            raise AuthFailure("provider") from None
        transaction = self._policy.new_transaction(
            state=rv["state"],
            nonce=rv["nonce"],
            code_verifier=rv["code_verifier"],
            return_path=safe_return_path(return_path),
            clock=self._clock,
        )
        return LoginStart(transaction=transaction, authorization_url=rv["url"])

    async def finish(
        self, code: str, state: str, transaction: LoginTransaction
    ) -> VerifiedIdentity:
        """Check the transaction, exchange the code and verify the identity."""
        problem = self._policy.transaction_problem(transaction, state, self._clock())
        if problem is not None:
            raise AuthFailure(problem)

        try:
            token = await self._app.fetch_access_token(
                code=code,
                code_verifier=transaction.code_verifier,
                redirect_uri=self._callback,
            )
            id_token = token.get("id_token") if isinstance(token, Mapping) else None
            if not isinstance(id_token, str) or not id_token:
                # A null, boolean, number, array or object is not an ID token,
                # and is not coerced into one for the library to parse.
                raise AuthFailure("provider")
            claims = await self._app.parse_id_token(
                token,
                nonce=transaction.nonce,
                claims_options={
                    "iss": {"values": [GOOGLE_ISSUER]},
                    "aud": {"values": [self._client_id]},
                    "azp": {"values": [self._client_id]},
                },
            )
        except _PROVIDER_ERRORS:
            raise AuthFailure("provider") from None
        if claims is None:
            raise AuthFailure("provider")
        if isinstance(claims.get("iat"), bool):
            # OpenID Connect requires a NumericDate (an integer). joserfc
            # 1.7.7 accepts a JSON boolean because Python booleans are ints;
            # reject that gap explicitly until a library upgrade covers it.
            raise AuthFailure("provider")

        identity = VerifiedIdentity(
            subject=str(claims.get("sub") or ""),
            email=str(claims.get("email") or ""),
            email_verified=claims.get("email_verified") is True,
        )
        if not identity.subject or not self._policy.allows(identity):
            raise AuthFailure("identity")
        return identity
