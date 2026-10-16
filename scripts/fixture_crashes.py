"""Sample Crashlytics events, shaped like rows of the BigQuery batch export.

Four issues over the six days before the fixture END, on the staging Android
app: a fatal crash on the match screen that a later app version fixes, a fatal
crash in the assistant, a non-fatal network error and one ANR.
"""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

from scripts.fixture_core import END, SEED

DEVICES = (
    ("Google", "Pixel 7", "14"),
    ("Google", "Pixel 8", "15"),
    ("samsung", "SM-S911B", "14"),
    ("OnePlus", "CPH2449", "13"),
)
INSTALLS = 6

# (issue_id, error_type, exception type, message, frames, events, versions)
ISSUES: tuple[tuple[Any, ...], ...] = (
    (
        "4f1c2a9be0d34c5e",
        "FATAL",
        "java.lang.IllegalStateException",
        "Prediction is not loaded",
        (
            "com.footballintelligence.app.match.MatchViewModel.showPrediction",
            "com.footballintelligence.app.match.MatchScreenKt.MatchScreen",
            "androidx.compose.runtime.ComposerImpl.doCompose",
        ),
        7,
        ("2.4.0", "2.4.1"),
    ),
    (
        "8b7d06e1c2f94a13",
        "FATAL",
        "kotlinx.serialization.SerializationException",
        "Field 'citations' is required for type ChatResponse",
        (
            "kotlinx.serialization.internal.PluginExceptionsKt.throwMissingFieldException",
            "com.footballintelligence.app.assistant.ChatRepository.send",
            "com.footballintelligence.app.assistant.AssistantViewModel.ask",
        ),
        3,
        ("2.5.0",),
    ),
    (
        "c39e5f2a7d1b4e80",
        "NON_FATAL",
        "java.net.SocketTimeoutException",
        "timeout",
        (
            "okhttp3.internal.http2.Http2Stream.waitForIo",
            "com.footballintelligence.app.network.ApiClient.get",
            "com.footballintelligence.app.fixtures.FixturesRepository.load",
        ),
        5,
        ("2.5.0",),
    ),
    (
        "e02a4b8c9f6d1735",
        "ANR",
        "com.google.firebase.crashlytics.ndk.AppNotResponding",
        "Input dispatching timed out",
        (
            "com.footballintelligence.app.history.SeasonHistoryParser.parse",
            "com.footballintelligence.app.history.HistoryScreenKt.HistoryScreen",
        ),
        1,
        ("2.5.0",),
    ),
)


def _frame(symbol: str, line: int, blamed: bool) -> dict[str, Any]:
    """One stack frame in the export's frame shape."""
    file = symbol.rsplit(".", 2)[-2] + ".kt"
    return {
        "symbol": symbol,
        "file": file,
        "line": line,
        "library": "com.footballintelligence.app.stg",
        "blamed": blamed,
    }


def _event(rng: random.Random, issue: tuple[Any, ...], index: int) -> dict[str, Any]:
    """One export row for the index-th event of an issue."""
    issue_id, error_type, exc_type, message, symbols, _, versions = issue
    frames = [_frame(s, 40 + 7 * n, n == 0) for n, s in enumerate(symbols)]
    manufacturer, model, android = DEVICES[rng.randrange(len(DEVICES))]
    when = END - timedelta(minutes=rng.randrange(10, 6 * 24 * 60))
    return {
        "event_id": f"{issue_id[:8]}{index:024x}",
        "event_timestamp": when.isoformat().replace("+00:00", "Z"),
        "issue_id": issue_id,
        "error_type": error_type,
        "application": {"display_version": versions[index % len(versions)]},
        "device": {"manufacturer": manufacturer, "model": model},
        "operating_system": {"display_version": android},
        "installation_uuid": f"{rng.randrange(INSTALLS):032x}",
        "exceptions": [
            {
                "type": exc_type,
                "exception_message": message,
                "nested": False,
                "frames": frames,
            }
        ],
        "blame_frame": frames[0],
    }


def crash_events() -> list[dict[str, Any]]:
    """Every sample crash event, newest first."""
    rng = random.Random(SEED)
    rows = [_event(rng, issue, n) for issue in ISSUES for n in range(issue[5])]
    return sorted(rows, key=lambda row: row["event_timestamp"], reverse=True)
