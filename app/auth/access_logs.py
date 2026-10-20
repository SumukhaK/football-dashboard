"""Remove OAuth callback queries from Uvicorn's application access records.

Filtering the record before handlers format it leaves the request untouched,
so the callback still receives the original code and state. Cloud Run request
logs are independent and still require the D9 launch privacy check.
"""

from __future__ import annotations

import logging


class _CallbackQueryFilter(logging.Filter):
    """Keep the callback's path and status, but none of its query fields."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Scrub Uvicorn's request-target argument before any handler sees it."""
        args = record.args
        if isinstance(args, tuple) and len(args) == 5:
            client, method, target, version, status = args
            if isinstance(target, str):
                path = target.partition("?")[0]
                if path.rstrip("/") == "/auth/callback":
                    record.args = (client, method, path, version, status)
        return True


def configure_auth_access_logs() -> None:
    """Install callback-query filtering once on the Uvicorn access logger."""
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, _CallbackQueryFilter) for item in logger.filters):
        logger.addFilter(_CallbackQueryFilter())
