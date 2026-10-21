"""Suite-wide guard: no test may build a real Google client.

The app builds its Google clients lazily, through three factories: the
Logging/Trace/Error Reporting readers, the Crashlytics BigQuery client and the
invite store's Firestore client. A test that renders a page over ``source=gcp``
without injecting a fake reaches one of them on its first read, and then uses
whatever Application Default Credentials the developer's machine has. Each
factory is replaced here with one that fails at once, so such a test fails the
same way with or without credentials, before any socket or retry.

Tests of the readers themselves inject fake clients and never call these
factories; a test that genuinely needs one can override the fixture locally.
"""

from __future__ import annotations

from typing import Any, NoReturn

import pytest

import app.main
import app.sources.gcp.crashlytics_reader
import app.sources.gcp.source


def _no_real_google_client(*args: Any, **kwargs: Any) -> NoReturn:
    raise AssertionError(
        "a test reached a real Google client factory; inject a fake source, "
        "service or client instead"
    )


@pytest.fixture(autouse=True)
def no_real_google_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every real Google client factory fail before it can connect."""
    monkeypatch.setattr(
        app.sources.gcp.source, "google_readers", _no_real_google_client
    )
    monkeypatch.setattr(
        app.sources.gcp.crashlytics_reader, "bigquery_client", _no_real_google_client
    )
    monkeypatch.setattr(app.main, "firestore_client", _no_real_google_client)
