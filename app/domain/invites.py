"""Invite codes and emails in the platform backend's format.

The backend's ``manage_accounts invite`` makes the same codes and stores the same
digest, so an invite made here can be redeemed in the app.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable

# No I, L, O, U, 0 or 1, so a code read aloud or off a screen is not misread.
ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
CODE_LENGTH = 8
GROUP_LENGTH = 4


class InvalidEmailError(ValueError):
    """The email cannot be invited."""


def new_code(choose: Callable[[str], str] = secrets.choice) -> str:
    """A fresh code from ``choose``, shown as XXXX-XXXX."""
    raw = "".join(choose(ALPHABET) for _ in range(CODE_LENGTH))
    return f"{raw[:GROUP_LENGTH]}-{raw[GROUP_LENGTH:]}"


def normalise_code(code: str) -> str:
    """The code as the backend compares it: no spaces or dashes, upper case."""
    return code.replace(" ", "").replace("-", "").upper()


def code_hash(code: str) -> str:
    """SHA-256 hex of the normalised code, the value the backend stores."""
    return hashlib.sha256(normalise_code(code).encode()).hexdigest()


def normalise_email(email: str) -> str:
    """The trimmed, lower-case email, or InvalidEmailError if it is not one."""
    cleaned = email.strip().lower()
    local, _, domain = cleaned.partition("@")
    malformed = not local or not domain or "@" in domain
    # Firestore document ids cannot contain "/", and the email is the id.
    if malformed or "/" in cleaned or any(char.isspace() for char in cleaned):
        raise InvalidEmailError("Enter one email address, like name@example.com.")
    return cleaned
