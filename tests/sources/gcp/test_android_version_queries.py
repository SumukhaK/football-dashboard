"""Bound independent Android version predicates before BigQuery row/bytes caps."""

import pytest
from bigquery_fakes import ROW, WINDOW, FakeClient, crash_source


@pytest.mark.parametrize("version", ["2.5.1", "unknown", 'v" OR true --'])
@pytest.mark.parametrize("issue", [None, "i1"])
def test_android_query_binds_version_before_limit(
    version: str, issue: str | None
) -> None:
    """Version is a parameter, never SQL text or an inferred backend API identity."""
    client = FakeClient([ROW])
    source = crash_source(client)
    if issue is None:
        source.version_crash_events(WINDOW, 5000, version)
    else:
        source.version_issue_events(issue, WINDOW, 50, version)
    sql, config, _ = client.calls[0]
    params = {p.name: p.value for p in config.query_parameters}
    assert params["android_version"] == version
    assert params["start"] == WINDOW.start and params["end"] == WINDOW.end
    assert params["limit"] == (5000 if issue is None else 50)
    assert config.maximum_bytes_billed == 1_000_000_000
    assert sql.index("@android_version") < sql.index("LIMIT @limit")
    assert "COALESCE(NULLIF(application.display_version" in sql
    assert "api_version" not in sql
    if version != "unknown":
        assert version not in sql
    if issue is not None:
        assert params["issue_id"] == issue and "exceptions, blame_frame" in sql


@pytest.mark.parametrize("version", ["", "x" * 65, "bad\nversion"])
def test_bad_android_query_never_calls_bigquery(version: str) -> None:
    """Boundary validation happens before a query could incur work."""
    client = FakeClient([ROW])
    with pytest.raises(ValueError):
        crash_source(client).version_crash_events(WINDOW, 5000, version)
    assert client.calls == []
