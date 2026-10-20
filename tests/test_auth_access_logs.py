"""The real Uvicorn access-record shape must not retain callback queries."""

from __future__ import annotations

import logging

import pytest

from app.main import create_app
from tests.auth.support import NOW, google_config


@pytest.fixture
def access_logger(monkeypatch: pytest.MonkeyPatch) -> logging.Logger:
    """Require application wiring to install its filter on a fresh logger."""
    logger = logging.getLogger("uvicorn.access")
    monkeypatch.setattr(logger, "filters", [])
    create_app(google_config(), clock=lambda: NOW)
    return logger


@pytest.mark.parametrize("path", ["/auth/callback", "/auth/callback/"])
def test_callback_queries_are_removed_before_access_records_are_formatted(
    path: str, access_logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    """Keep method, path and status while removing every callback query field."""
    target = f"{path}?code=PRIVATE-CODE&state=PRIVATE-STATE&error=PRIVATE-ERROR"

    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        access_logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:1234",
            "GET",
            target,
            "1.1",
            303,
        )

    assert f'GET {path} HTTP/1.1" 303' in caplog.text
    assert "PRIVATE-" not in caplog.text
    assert "?" not in caplog.records[-1].getMessage()
    assert target not in str(caplog.records[-1].args)


def test_other_access_queries_remain_visible(
    access_logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    """The callback privacy rule does not discard ordinary route diagnostics."""
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        access_logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:1234",
            "GET",
            "/requests?window=24",
            "1.1",
            200,
        )

    assert "/requests?window=24" in caplog.text


def test_other_log_record_shapes_are_unchanged(
    access_logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    """Messages without the Uvicorn request tuple remain valid log messages."""
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        access_logger.info("plain message")
        access_logger.info("single %s", "argument")
        access_logger.info("mapping %(value)s", {"value": "argument"})
        access_logger.info(
            "%s %s %s %s %s", "client", "method", None, "version", "status"
        )

    assert "plain message" in caplog.text
    assert "single argument" in caplog.text
    assert "mapping argument" in caplog.text
    assert "client method None version status" in caplog.text
