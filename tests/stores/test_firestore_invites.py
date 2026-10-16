"""Tests for the Firestore invite store, with a fake client."""

from __future__ import annotations

from typing import Any

import pytest
from google.api_core import exceptions as api_exceptions

from app.domain.errors import SourceUnavailableError
from app.stores.firestore_invites import FirestoreInviteStore

RECORD: dict[str, str | None] = {"email": "ann@example.com", "redeemed_at": None}


class FakeDocument:
    """Records set() calls on one document."""

    def __init__(self, client: FakeClient, path: str) -> None:
        self._client = client
        self._path = path

    def set(self, data: dict[str, Any]) -> None:
        """Record a full replace of this document."""
        if self._client.error is not None:
            raise self._client.error
        self._client.writes.append((self._path, data))


class FakeCollection:
    """Hands out documents under one collection name."""

    def __init__(self, client: FakeClient, name: str) -> None:
        self._client = client
        self._name = name

    def document(self, doc_id: str) -> FakeDocument:
        """The document ``doc_id`` in this collection."""
        return FakeDocument(self._client, f"{self._name}/{doc_id}")


class FakeClient:
    """A stand-in for google.cloud.firestore.Client."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.writes: list[tuple[str, dict[str, Any]]] = []

    def collection(self, name: str) -> FakeCollection:
        """The collection ``name``."""
        return FakeCollection(self, name)


def test_save_sets_the_prefixed_invite_document() -> None:
    """The record lands in {prefix}invites under the email."""
    client = FakeClient()
    FirestoreInviteStore(lambda: client, "staging_").save("ann@example.com", RECORD)
    assert client.writes == [("staging_invites/ann@example.com", RECORD)]


def test_client_is_built_lazily_and_once() -> None:
    """No client exists until the first save, then it is reused."""
    built: list[FakeClient] = []

    def make() -> FakeClient:
        built.append(FakeClient())
        return built[-1]

    store = FirestoreInviteStore(make, "")
    assert built == []
    store.save("a@b.c", RECORD)
    store.save("d@e.f", RECORD)
    assert len(built) == 1
    assert [path for path, _ in built[0].writes] == ["invites/a@b.c", "invites/d@e.f"]


def test_google_errors_become_source_errors() -> None:
    """A refused write is a SourceUnavailableError the page can show."""
    client = FakeClient(api_exceptions.PermissionDenied("no access"))
    store = FirestoreInviteStore(lambda: client, "staging_")
    with pytest.raises(SourceUnavailableError) as caught:
        store.save("ann@example.com", RECORD)
    assert caught.value.kind == "permission_denied"
