"""Tests for the small event accessors the services share."""

from __future__ import annotations

from app.services.events import severity_tone, status_tone


def test_status_tone_reads_a_status_in_tiers() -> None:
    """A status code picks its tone by class."""
    assert status_tone(200) == "ok"
    assert status_tone(301) == "ok"
    assert status_tone(404) == "warn"
    assert status_tone(499) == "warn"
    assert status_tone(500) == "fail"
    assert status_tone(503) == "fail"


def test_status_tone_without_a_status_is_neutral() -> None:
    """A request with no status at all is not shown as a success or a failure."""
    assert status_tone(None) == "neutral"


def test_severity_tone_reads_a_severity() -> None:
    """Error and critical read as failures, warning as a warning."""
    assert severity_tone("ERROR") == "fail"
    assert severity_tone("CRITICAL") == "fail"
    assert severity_tone("WARNING") == "warn"
    assert severity_tone("INFO") == "ok"
    assert severity_tone("DEBUG") == "ok"
