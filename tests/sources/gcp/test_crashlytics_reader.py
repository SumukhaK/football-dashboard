"""Tests for the Crashlytics BigQuery reader."""

from __future__ import annotations

from typing import Any

import pytest
from bigquery_fakes import ROW, TABLE, WINDOW, FakeClient, FakeDataset
from bigquery_fakes import crash_source as _source
from google.api_core import exceptions as api_exceptions
from google.cloud import bigquery

from app.domain.errors import SourceUnavailableError
from app.sources.gcp.crashlytics_reader import BigQueryCrashSource


def _params(config: bigquery.QueryJobConfig) -> dict[str, Any]:
    """The query parameters by name."""
    return {p.name: p.value for p in config.query_parameters}


def test_list_query_is_parameterised_filtered_and_capped() -> None:
    """The SQL filters on the window, binds parameters and caps bytes billed."""
    client = FakeClient([ROW])
    events = _source(client).crash_events(WINDOW, 500)
    sql, config, location = client.calls[0]
    assert f"FROM `{TABLE}`" in sql
    assert "WHERE event_timestamp >= @start AND event_timestamp < @end" in sql
    assert "LIMIT @limit" in sql and "issue_id = @issue_id" not in sql
    assert "frames" not in sql and "blame_frame" not in sql
    assert _params(config) == {"start": WINDOW.start, "end": WINDOW.end, "limit": 500}
    assert config.maximum_bytes_billed == 1_000_000_000
    assert location == "US"
    assert [e.event_id for e in events] == ["e1"]


def test_issue_query_binds_the_issue_and_reads_frames() -> None:
    """The detail query narrows by a bound issue id and selects the stack."""
    client = FakeClient([ROW])
    _source(client).issue_events("i1", WINDOW, 50)
    sql, config, _ = client.calls[0]
    assert "AND issue_id = @issue_id" in sql
    assert "event_timestamp >= @start" in sql
    assert "exceptions, blame_frame" in sql
    assert _params(config)["issue_id"] == "i1"
    assert config.maximum_bytes_billed == 1_000_000_000


def test_missing_table_is_no_events() -> None:
    """Before the first daily export the table does not exist: no events."""
    client = FakeClient(error=api_exceptions.NotFound("Table not found"))
    assert _source(client).crash_events(WINDOW, 500) == []
    assert _source(client).issue_events("i1", WINDOW, 50) == []
    assert client.dataset_calls[0] == "proj.firebase_crashlytics"


def test_dataset_location_is_compared_without_case() -> None:
    """BigQuery may report the location in another case; that still matches."""
    client = FakeClient(
        error=api_exceptions.NotFound("Table not found"), dataset=FakeDataset("us")
    )
    assert _source(client).crash_events(WINDOW, 500) == []


def test_missing_dataset_is_a_settings_error() -> None:
    """A wrong project or dataset name names the settings, not an empty export."""
    client = FakeClient(
        error=api_exceptions.NotFound("Dataset not found"),
        dataset=api_exceptions.NotFound("Dataset not found"),
    )
    with pytest.raises(SourceUnavailableError) as raised:
        _source(client).crash_events(WINDOW, 500)
    assert raised.value.kind == "not_found"
    assert "proj.firebase_crashlytics" in raised.value.detail
    assert "crashlytics_project_id and crashlytics_dataset" in raised.value.detail


def test_dataset_in_another_location_is_a_settings_error() -> None:
    """A query in the wrong location reports the table missing; say why."""
    client = FakeClient(
        error=api_exceptions.NotFound("Table not found in location US"),
        dataset=FakeDataset("EU"),
    )
    with pytest.raises(SourceUnavailableError) as raised:
        _source(client).issue_events("i1", WINDOW, 50)
    assert raised.value.kind == "not_found"
    assert "is in EU, not US" in raised.value.detail
    assert "crashlytics_location" in raised.value.detail


def test_dataset_lookup_refused_maps_to_permission_denied() -> None:
    """A refused dataset lookup is the shared permission banner."""
    client = FakeClient(
        error=api_exceptions.NotFound("Table not found"),
        dataset=api_exceptions.PermissionDenied("no access"),
    )
    with pytest.raises(SourceUnavailableError) as raised:
        _source(client).crash_events(WINDOW, 500)
    assert raised.value.kind == "permission_denied"


def test_dataset_lookup_other_error_is_unavailable() -> None:
    """Any other failure of the lookup shows as the unavailable banner."""
    client = FakeClient(
        error=api_exceptions.NotFound("Table not found"),
        dataset=api_exceptions.BadRequest("bad dataset id"),
    )
    with pytest.raises(SourceUnavailableError) as raised:
        _source(client).crash_events(WINDOW, 500)
    assert raised.value.kind == "unavailable"


def test_permission_errors_map_to_permission_denied() -> None:
    """A refused read becomes the shared source error, by kind."""
    client = FakeClient(error=api_exceptions.PermissionDenied("no access"))
    with pytest.raises(SourceUnavailableError) as raised:
        _source(client).crash_events(WINDOW, 500)
    assert raised.value.kind == "permission_denied"


def test_other_google_errors_become_unavailable() -> None:
    """Anything else from Google, such as the byte cap, shows as a banner."""
    client = FakeClient(error=api_exceptions.BadRequest("bytesBilledLimitExceeded"))
    with pytest.raises(SourceUnavailableError) as raised:
        _source(client).crash_events(WINDOW, 500)
    assert raised.value.kind == "unavailable"
    assert "bytesBilledLimitExceeded" in raised.value.detail


def test_client_is_built_once_on_first_query() -> None:
    """Building the reader never calls Google; the first query builds the client."""
    built: list[FakeClient] = []

    def make() -> FakeClient:
        built.append(FakeClient())
        return built[-1]

    source = BigQueryCrashSource(make, TABLE, "US", 1)
    assert built == []
    source.crash_events(WINDOW, 1)
    source.crash_events(WINDOW, 1)
    assert len(built) == 1
