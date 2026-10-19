"""Display labels for raw names, durations and windows.

Services put these labels into their view models, so a template never has to
format a name, a duration or a window size itself.
"""

from __future__ import annotations

from datetime import datetime

# Durations under two seconds read better in milliseconds; from two seconds
# they read better in seconds with one decimal.
SECONDS_FROM_MS = 2000

SECONDS_PER_MINUTE = 60
MINUTES_PER_HOUR = 60
HOURS_PER_DAY = 24


def display_name(raw: str) -> str:
    """Turn a raw name into its display label.

    ``prediction_model_v1`` becomes "Prediction model v1" and
    ``model_with_tools`` becomes "Model with tools". Only the first word's first
    letter is raised, so a word that is already shouted stays as it is. An empty
    or blank name comes back unchanged.
    """
    words = [word for word in raw.split("_") if word]
    if not words:
        return raw
    first = words[0]
    return " ".join([first[:1].upper() + first[1:], *words[1:]])


def format_duration_ms(milliseconds: float | None) -> str:
    """A duration as "386 ms" or "86.1 s"; a missing one as "no data"."""
    if milliseconds is None:
        return "no data"
    if milliseconds < SECONDS_FROM_MS:
        return f"{milliseconds:.0f} ms"
    return f"{milliseconds / 1000:.1f} s"


def window_label(hours: int) -> str:
    """The window as a page subtitle names it, for example "Last 24 hours"."""
    if hours == 1:
        return "Last hour"
    if hours == 168:
        return "Last 7 days"
    return f"Last {hours} hours"


def relative_time(moment: datetime, now: datetime) -> str:
    """How long ago a moment was, as the requests list reads it.

    Seconds under a minute, minutes under an hour, hours under a day, then days.
    A moment in the future reads as "0 s ago" rather than going backwards.
    """
    seconds = max(0, int((now - moment).total_seconds()))
    if seconds < SECONDS_PER_MINUTE:
        return f"{seconds} s ago"
    minutes = seconds // SECONDS_PER_MINUTE
    if minutes < MINUTES_PER_HOUR:
        return f"{minutes} min ago"
    hours = minutes // MINUTES_PER_HOUR
    if hours < HOURS_PER_DAY:
        return f"{hours} h ago"
    days = hours // HOURS_PER_DAY
    return "1 day ago" if days == 1 else f"{days} days ago"


def window_span(hours: int) -> str:
    """The window as the picker and the card comparison name it: "24h", "7d"."""
    return "7d" if hours == 168 else f"{hours}h"


def window_comparison_label(hours: int) -> str:
    """The window compared with the one before it, for the page subtitle."""
    return f"{window_label(hours)} compared with the {_previous_span(hours)} before"


def _previous_span(hours: int) -> str:
    """The previous window's length in words: "hour", "24 hours", "7 days"."""
    if hours == 1:
        return "hour"
    if hours == 168:
        return "7 days"
    return f"{hours} hours"
