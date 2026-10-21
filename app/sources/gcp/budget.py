"""A finite wall-clock budget shared by Google source readers."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable

from app.domain.errors import SourceUnavailableError

# One source read is one page section. Six serial reads on Overview must fit
# inside the 60-second hosted request limit with rendering margin left over.
READ_BUDGET_SECONDS = 5.0
# A pager can make more than one RPC; each one may consume at most this much
# time. The reader checks the whole-read budget between pages and entries.
RPC_TIMEOUT_SECONDS = 2.0


class ReadBudget:
    """A monotonic deadline for one reader operation."""

    def __init__(
        self,
        service: str,
        clock: Callable[[], float] = time.monotonic,
        seconds: float = READ_BUDGET_SECONDS,
    ) -> None:
        self._service = service
        self._clock = clock
        self._deadline = clock() + seconds

    def remaining(self) -> float:
        """Return the seconds left, never a negative duration."""
        return max(0.0, self._deadline - self._clock())

    def check(self) -> None:
        """Stop with the existing source error when the budget is gone."""
        if self.remaining() <= 0:
            raise SourceUnavailableError(
                "unavailable",
                f"{self._service}: read budget exhausted; try again later",
            )

    def timeout(self, cap: float) -> float:
        """Return a transport timeout that cannot exceed the remaining budget."""
        remaining = self.remaining()
        if remaining <= 0:
            self.check()
        return min(cap, remaining)


def budgeted[T](entries: Iterable[T], budget: ReadBudget) -> Iterable[T]:
    """Stop consuming a pager once the whole-read budget has expired."""
    for entry in entries:
        budget.check()
        yield entry
