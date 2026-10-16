"""Display labels for raw names, durations and windows.

Services put these labels into their view models, so a template never has to
format a name, a duration or a window size itself.
"""

from __future__ import annotations

# Durations under two seconds read better in milliseconds; from two seconds
# they read better in seconds with one decimal.
SECONDS_FROM_MS = 2000


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
