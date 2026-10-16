"""Tests for the invite service: the record it writes and the code it returns."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from app.services.invites import (
    InvalidEmailError,
    InviteRecord,
    InviteService,
    NewInvite,
)

NOW = datetime(2026, 10, 16, 5, 0, tzinfo=UTC)


class FakeStore:
    """Keeps saved records in a dict, as Firestore set() would."""

    def __init__(self) -> None:
        self.records: dict[str, InviteRecord] = {}

    def save(self, email: str, record: InviteRecord) -> None:
        """Replace the record for ``email``."""
        self.records[email] = record


def _service(store: FakeStore, code: str = "K7MP-W3QX") -> InviteService:
    """A service with a fixed clock and a fixed code."""
    return InviteService(store, lambda: NOW, 7, new_code=lambda: code)


def test_create_writes_the_backend_document_shape() -> None:
    """The document matches what the platform's manage_accounts invite writes."""
    store = FakeStore()
    invite = _service(store).create("  Ann@Example.com ")

    assert invite == NewInvite("K7MP-W3QX", datetime(2026, 10, 23, 5, 0, tzinfo=UTC))
    assert store.records == {
        "ann@example.com": {
            "email": "ann@example.com",
            "code_hash": hashlib.sha256(b"K7MPW3QX").hexdigest(),
            "expires_at": "2026-10-23T05:00:00+00:00",
            "redeemed_at": None,
        }
    }


def test_a_new_invite_replaces_the_old_one() -> None:
    """Inviting the same email again leaves only the newest code."""
    store = FakeStore()
    _service(store, "AAAA-AAAA").create("ann@example.com")
    _service(store, "BBBB-BBBB").create("ANN@example.com")

    record = store.records["ann@example.com"]
    assert record["code_hash"] == hashlib.sha256(b"BBBBBBBB").hexdigest()
    assert len(store.records) == 1


def test_lifetime_and_default_code() -> None:
    """The expiry is the clock plus the configured days; the code is XXXX-XXXX."""
    invite = InviteService(FakeStore(), lambda: NOW, 1).create("ann@example.com")
    assert invite.expires_at == datetime(2026, 10, 17, 5, 0, tzinfo=UTC)
    assert len(invite.code) == 9
    assert invite.code[4] == "-"


def test_invalid_email_saves_nothing() -> None:
    """A bad email is rejected before anything is written."""
    store = FakeStore()
    with pytest.raises(InvalidEmailError):
        _service(store).create("not-an-email")
    assert store.records == {}
