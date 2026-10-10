"""Fixture telemetry source for offline/test usage.

Reads the four fixture files once at construction, validates every event line
against the contract, and supports time re-basing and EventQuery filtering.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timedelta, UTC
from pathlib import Path

from app.domain.clock import Clock
from app.domain.errors import SourceUnavailableError
from app.domain.models import EventQuery, TelemetryEvent, TimeWindow