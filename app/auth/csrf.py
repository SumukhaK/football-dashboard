"""Same-origin and per-session CSRF checks shared by every write.

Both checks are pure comparisons. The CSRF value is the random identifier
already inside the signed session, and the origin comes from configuration,
never from a request Host or forwarded header.
"""

from __future__ import annotations

import hmac

from starlette.requests import Request

from app.config import Config


def same_origin(request: Request, settings: Config) -> bool:
    """Whether this write carries exactly the configured console origin."""
    configured = settings.auth_public_origin
    return bool(configured) and request.headers.get("origin") == configured


def matches(expected: str, submitted: str | None) -> bool:
    """Whether the submitted value is the session's identifier, in constant time."""
    if not submitted:
        return False
    return hmac.compare_digest(expected.encode(), submitted.encode())
