"""Invite records in Firestore, in the collection the platform backend reads."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.services.invites import InviteRecord
from app.sources.gcp.errors import guarded

COLLECTION = "invites"


class FirestoreInviteStore:
    """Writes invites to ``{prefix}invites``, one document per email."""

    def __init__(self, make_client: Callable[[], Any], prefix: str) -> None:
        """Build the client with ``make_client`` on the first save, not before."""
        # Any: google-cloud-firestore's client has no usable type stubs.
        self._make_client = make_client
        self._prefix = prefix
        self._client: Any = None

    def save(self, email: str, record: InviteRecord) -> None:
        """Replace the invite document for ``email`` (set, not merge)."""
        guarded("firestore", lambda: self._document(email).set(record))

    def _document(self, email: str) -> Any:
        """The invite document for ``email``, building the client if needed."""
        if self._client is None:
            self._client = self._make_client()
        return self._client.collection(self._prefix + COLLECTION).document(email)


def firestore_client(project: str | None) -> Any:
    """A Firestore client for ``project``, using application default credentials."""
    from google.cloud import firestore

    return firestore.Client(project=project)
