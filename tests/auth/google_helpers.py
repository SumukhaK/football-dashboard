"""Shared steps for the GoogleOIDC tests: the owner, a started login and its outcome."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest

from app.auth.google import GoogleOIDC
from app.domain.auth import LoginStart, VerifiedIdentity
from app.services.auth import AuthFailure
from tests.auth.support import (
    FakeGoogle,
)

OWNER = "sumukh.aithal@gmail.com"


# A constant, not a literal in the call: a rendered traceback prints the
# source line of the frame that called finish(), so the privacy test can only
# prove the provider's copy of the code is gone if the caller's own is not
# spelled out on that line.
CODE = "fake-code"


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run one adapter call to completion; the seam is async, the tests are not."""
    return asyncio.run(coro)


def started(provider: GoogleOIDC, return_path: str = "/") -> LoginStart:
    return run(provider.start(return_path))


def ready(fake: FakeGoogle, provider: GoogleOIDC) -> LoginStart:
    """Start a sign-in and make the fake answer for exactly that transaction."""
    start = started(provider)
    fake.expected_verifier = start.transaction.code_verifier
    fake.id_token_overrides = {"nonce": start.transaction.nonce}
    return start


def finish(provider: GoogleOIDC, start: LoginStart) -> VerifiedIdentity:
    return run(provider.finish(CODE, start.transaction.state, start.transaction))


def failure(provider: GoogleOIDC, start: LoginStart) -> AuthFailure:
    with pytest.raises(AuthFailure) as caught:
        finish(provider, start)
    return caught.value
