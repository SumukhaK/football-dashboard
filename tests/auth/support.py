"""A fake Google for the D9.2 provider tests: real tokens, no network.

The provider is exercised against Authlib's real OpenID validation. Only the
two HTTP endpoints are faked, through an ``httpx.MockTransport``, so the tests
cover signature, algorithm, issuer, audience and nonce checking without a
Google credential or a live call. Tokens are signed with a local RSA key that
is published as the fake JWKS.
"""

from __future__ import annotations

import base64
import hashlib
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs

import httpx
from joserfc import jwt
from joserfc.jwk import RSAKey

from app.auth.google import GoogleOIDC
from app.config import Config
from app.services.auth import AuthPolicy

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
ISSUER = "https://accounts.google.com"
CLIENT_ID = "114958444175-abcdefghijklmnop.apps.googleusercontent.com"
CALLBACK = "https://console.example/auth/callback"
# Deliberately low-entropy, non-secret placeholders. They meet the settings
# validator (32+ bytes, eight distinct characters, the two keys differ) without
# looking like credentials to a secret scanner: the console has no test key.
AUTH_SESSION_KEY = "test-only-session-signing-key-0000000000"
AUTH_OAUTH_KEY = "test-only-oauth-signing-key-1111111111"


def google_config(**overrides: Any) -> Config:
    """A fully configured hosted console, with placeholder credentials."""
    fields: dict[str, Any] = {
        "auth_mode": "google",
        "google_client_id": CLIENT_ID,
        "google_client_secret": "GOCSPX-not-a-real-secret",
        "auth_public_origin": "https://console.example",
        "auth_callback_url": CALLBACK,
        "session_signing_key": AUTH_SESSION_KEY,
        "oauth_signing_key": AUTH_OAUTH_KEY,
    }
    fields.update(overrides)
    return Config(**fields)


def policy() -> AuthPolicy:
    """The policy the fake console runs with."""
    return AuthPolicy.from_config(google_config())


def pkce_challenge(verifier: str) -> str:
    """The S256 challenge a correct client must send for ``verifier``."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def make_key(kid: str = "test-key") -> RSAKey:
    """A local signing key, published as the fake JWKS.

    No algorithm is pinned on the key itself, so a test can sign with an
    algorithm the published metadata does not allow.
    """
    return RSAKey.generate_key(2048, parameters={"kid": kid})


@dataclass
class FakeGoogle:
    """Google's discovery document, JWKS and token endpoint, in memory."""

    key: RSAKey = field(default_factory=make_key)
    other_key: RSAKey = field(default_factory=lambda: make_key("other-key"))
    # What the endpoint returns, unless a test narrows it.
    id_token_overrides: dict[str, Any] = field(default_factory=dict)
    omit_claims: tuple[str, ...] = ()
    token_status: int = 200
    token_body: dict[str, Any] | None = None
    discovery_status: int = 200
    jwks_status: int = 200
    # A well-formed response is the default; a test may replace the JSON with a
    # malformed shape to exercise the adapter's failure boundary.
    discovery_body: Any = None
    jwks_body: Any = None
    token_error_body: dict[str, Any] | None = None
    outage: Exception | None = None
    expected_code: str = "fake-code"
    expected_redirect_uri: str = CALLBACK
    expected_verifier: str = ""
    # Everything the adapter was asked for, so a test can inspect the request.
    requests: list[httpx.Request] = field(default_factory=list)

    # -- endpoints ---------------------------------------------------------

    def transport(self) -> httpx.MockTransport:
        """The transport the provider must use instead of the network."""
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.outage is not None:
            raise self.outage
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            if self.discovery_status != 200:
                return httpx.Response(self.discovery_status)
            if self.discovery_body is not None:
                return httpx.Response(200, json=self.discovery_body)
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_endpoint": "https://oauth2.googleapis.com/token",
                    "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
        if path.endswith("/certs"):
            if self.jwks_status != 200:
                return httpx.Response(self.jwks_status)
            if self.jwks_body is not None:
                return httpx.Response(200, json=self.jwks_body)
            return httpx.Response(200, json={"keys": [self.key.as_dict(private=False)]})
        if path.endswith("/token"):
            return self._token(request)
        return httpx.Response(404)

    def _token(self, request: httpx.Request) -> httpx.Response:
        if self.token_status != 200:
            return httpx.Response(
                self.token_status,
                json=self.token_error_body or {"error": "invalid_grant"},
            )
        form = parse_qs(request.content.decode())
        if form.get("code") != [self.expected_code]:
            return httpx.Response(400, json={"error": "invalid_grant"})
        if self.expected_verifier and form.get("code_verifier") != [
            self.expected_verifier
        ]:
            return httpx.Response(400, json={"error": "invalid_grant"})
        if form.get("redirect_uri") != [self.expected_redirect_uri]:
            return httpx.Response(400, json={"error": "invalid_grant"})
        if self.token_body is not None:
            return httpx.Response(200, json=self.token_body)
        return httpx.Response(
            200,
            json={
                "access_token": "fake-access-token",
                "token_type": "Bearer",
                "expires_in": 3600,
                "id_token": self.id_token(),
            },
        )

    # -- tokens ------------------------------------------------------------

    def id_token(
        self,
        *,
        signer: RSAKey | None = None,
        algorithm: str = "RS256",
        **overrides: Any,
    ) -> str:
        """A signed ID token, with every claim a test may need to bend."""
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "azp": CLIENT_ID,
            "sub": "1234567890",
            "email": "sumukh.aithal@gmail.com",
            "email_verified": True,
            "iat": now - 10,
            "exp": now + 300,
            "nonce": "test-nonce",
        }
        claims.update(self.id_token_overrides)
        claims.update(overrides)
        for claim in self.omit_claims:
            claims.pop(claim, None)
        signing_key = signer or self.key
        header = {"alg": algorithm, "kid": signing_key.as_dict()["kid"]}
        return jwt.encode(header, claims, signing_key, algorithms=[algorithm])


def build_provider(
    fake: FakeGoogle,
    *,
    tokens: list[str] | None = None,
    clock: Any = None,
) -> GoogleOIDC:
    """The adapter under test, wired to the fake and to a fixed clock."""
    counter = {"n": 0}

    def token_factory(length: int) -> str:
        if tokens is not None:
            value = tokens[counter["n"]]
            counter["n"] += 1
            return value
        counter["n"] += 1
        return f"token-{counter['n']}-" + "x" * length

    settings = google_config()
    return GoogleOIDC(
        settings,
        AuthPolicy.from_config(settings),
        transport=fake.transport(),
        clock=clock or (lambda: NOW),
        token_factory=token_factory,
    )
