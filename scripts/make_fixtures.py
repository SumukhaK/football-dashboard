"""Generate the console's sample telemetry into ``fixtures/`` (seed 7).

Run ``uv run python scripts/make_fixtures.py``. The output is byte-identical on
every run. The story it tells, all on 2026-10-07/08 UTC:

- revision 00041 starts with the assistant failed, so its chats get 503s;
- the 04:00 refresh fails and falls back to the old data, and the 05:00 one works;
- revision 00042 starts at 06:00 with every component loaded;
- one chat retries Ollama twice then answers, one gives up after three attempts;
- one account is locked out after five failed sign-ins (03:12);
- one client is rate limited in a burst (11:40);
- the instance runs out of memory at 17:42.
"""

from __future__ import annotations

import json
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    # Running as a script puts scripts/ on the path, not the repo root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.fixture_chats import chats
from scripts.fixture_core import END, SEED, Ids, Line
from scripts.fixture_platform import (
    error_groups,
    platform_events,
    platform_lines,
)
from scripts.fixture_traffic import (
    Traffic,
    account_scenarios,
    everyday_starts,
    lockout,
)

_DAY = datetime(2026, 10, 8, tzinfo=UTC)
CHAT_STARTS = (
    datetime(2026, 10, 7, 20, 15, tzinfo=UTC),
    datetime(2026, 10, 8, 1, 40, tzinfo=UTC),
    *(
        _DAY + timedelta(hours=h, minutes=m)
        for h, m in (
            (7, 10),
            (8, 25),
            (9, 50),
            (11, 5),
            (12, 30),
            (14, 15),
            (15, 40),
            (16, 55),
        )
    ),
)
LOCKOUT_AT = datetime(2026, 10, 8, 3, 12, tzinfo=UTC)
ACCOUNT_SCENARIOS_AT = datetime(2026, 10, 7, 21, 0, tzinfo=UTC)
BURST_AT = datetime(2026, 10, 8, 11, 40, tzinfo=UTC)


def _traffic_lines(rng: random.Random, traffic: Traffic) -> list[Line]:
    lines: list[Line] = []
    for start in everyday_starts(rng, END - timedelta(minutes=1)):
        if rng.random() < 0.03:
            lines += traffic.everyday_auth(start)
        else:
            lines += traffic.everyday(start)
    lines += account_scenarios(traffic, ACCOUNT_SCENARIOS_AT)
    lines += lockout(traffic, LOCKOUT_AT, traffic.users[3])
    return lines + traffic.rate_limit_burst(BURST_AT, 30)


def build() -> dict[str, Any]:
    """Return every fixture file's content, keyed by file name."""
    rng = random.Random(SEED)
    ids = Ids(rng)
    traffic = Traffic(rng, ids)
    chat_lines, traces = chats(ids, rng, traffic.users, CHAT_STARTS)
    lines = platform_lines(rng) + _traffic_lines(rng, traffic) + chat_lines
    lines.sort(key=lambda line: line["timestamp"])
    return {
        "events.jsonl": lines,
        "traces.json": traces,
        "error_groups.json": error_groups(lines),
        "platform_events.json": platform_events(),
    }


def write(output_dir: Path, files: dict[str, Any]) -> None:
    """Write ``files`` into ``output_dir`` with LF line endings."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        if name.endswith(".jsonl"):
            text = "".join(json.dumps(line) + "\n" for line in content)
        else:
            text = json.dumps(content, indent=2) + "\n"
        (output_dir / name).write_text(text, encoding="utf-8", newline="\n")


def main(output_dir: Path = Path("fixtures")) -> None:
    """Generate every fixture file into ``output_dir``."""
    write(output_dir, build())


if __name__ == "__main__":
    main()
