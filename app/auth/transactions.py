"""The signed, five-minute login transaction cookie.

One pending sign-in travels in one signed cookie: the state, nonce and PKCE
verifier the callback must match, the local path to return to, and the times
the attempt was issued and expires. Starting another sign-in replaces the
cookie, so a browser never accumulates pending attempts.

The payload is signed, not encrypted. It holds no token and no identity, and
the key purpose is separate from the session cookie's, so a pending-login
cookie can never be presented as a session.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from itsdangerous import BadData, URLSafeTimedSerializer

from app.config import Config
from app.domain.auth import LoginTransaction
from app.domain.clock import Clock
from app.services.auth import AuthFailure

# The serializer's salt is the purpose. D9.3 signs the console session with a
# different key and a different salt, so neither value can stand in for the
# other even if a key were ever shared by mistake.
TRANSACTION_SALT = "dashboard-oauth-transaction"
_FIELDS = ("state", "nonce", "code_verifier", "return_path", "issued_at", "expires_at")


@dataclass(frozen=True, slots=True)
class TransactionCookie:
    """Serialises one ``LoginTransaction`` and refuses anything else."""

    signing_key: str
    max_age_seconds: int
    clock: Clock

    @classmethod
    def from_config(cls, settings: Config, clock: Clock) -> TransactionCookie:
        """The codec the console runs with, from its validated settings."""
        if settings.oauth_signing_key is None:
            raise ValueError("oauth_signing_key is required for login transactions")
        return cls(
            signing_key=settings.oauth_signing_key.get_secret_value(),
            max_age_seconds=settings.oauth_transaction_max_age_seconds,
            clock=clock,
        )

    @property
    def serializer(self) -> URLSafeTimedSerializer:
        """A serializer bound to this key and this purpose."""
        return URLSafeTimedSerializer(self.signing_key, salt=TRANSACTION_SALT)

    def dumps(self, transaction: LoginTransaction) -> str:
        """Sign one transaction into the cookie value."""
        payload = {
            "state": transaction.state,
            "nonce": transaction.nonce,
            "code_verifier": transaction.code_verifier,
            "return_path": transaction.return_path,
            "issued_at": transaction.issued_at.isoformat(),
            "expires_at": transaction.expires_at.isoformat(),
        }
        return str(self.serializer.dumps(payload))

    def loads(self, value: str) -> LoginTransaction:
        """Read a transaction back, or raise ``AuthFailure("transaction")``.

        The signature is checked first; then the shape, the configured
        lifetime bound and the window against the injected clock. A payload
        that is signed but wrong is still refused, which is what bounds the
        cookie even if the signing key were ever leaked.
        """
        try:
            payload = self.serializer.loads(value)
        except BadData as exc:
            raise AuthFailure("transaction") from exc
        if not isinstance(payload, dict) or set(payload) != set(_FIELDS):
            raise AuthFailure("transaction")

        transaction = self._transaction(payload)
        lifetime = transaction.expires_at - transaction.issued_at
        if lifetime.total_seconds() > self.max_age_seconds:
            raise AuthFailure("transaction")
        if not transaction.is_valid_at(self.clock()):
            raise AuthFailure("transaction")
        return transaction

    @staticmethod
    def _transaction(payload: dict[str, object]) -> LoginTransaction:
        """Validate every field's presence, type and order."""
        strings = {
            name: payload[name]
            for name in ("state", "nonce", "code_verifier", "return_path")
        }
        if not all(isinstance(value, str) and value for value in strings.values()):
            raise AuthFailure("transaction")
        if not str(strings["return_path"]).startswith("/"):
            raise AuthFailure("transaction")

        try:
            issued_at = datetime.fromisoformat(str(payload["issued_at"]))
            expires_at = datetime.fromisoformat(str(payload["expires_at"]))
        except ValueError as exc:
            raise AuthFailure("transaction") from exc
        if issued_at.tzinfo is None or expires_at.tzinfo is None:
            raise AuthFailure("transaction")
        if expires_at <= issued_at:
            raise AuthFailure("transaction")

        return LoginTransaction(
            state=str(strings["state"]),
            nonce=str(strings["nonce"]),
            code_verifier=str(strings["code_verifier"]),
            return_path=str(strings["return_path"]),
            issued_at=issued_at,
            expires_at=expires_at,
        )
