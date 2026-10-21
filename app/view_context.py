"""Request dependency and presentation context for shared scope controls."""

from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import Request
from starlette.exceptions import HTTPException

from app.domain.errors import SourceUnavailableError
from app.services.labels import IST
from app.services.view_scope import (
    SCOPE_KEYS,
    ViewScope,
    parse_scope,
    scoped_url,
    sort_releases,
)
from app.sources.base import ReleaseDiscovery


def prepare_scope(request: Request) -> ViewScope:
    """Resolve and validate scope once before a telemetry route reads data."""
    if hasattr(request.state, "view_scope"):
        return cast(ViewScope, request.state.view_scope)
    settings = request.app.state.config
    page = request.url.path.removeprefix("/partials")
    default = settings.default_window_hours
    if page == "/data":
        default = settings.data_default_window_hours
    elif page.startswith("/crashes"):
        default = 168
    elif page == "/access":
        default = settings.access_default_window_hours
    try:
        if any(len(request.query_params.getlist(key)) > 1 for key in SCOPE_KEYS):
            raise ValueError("duplicate scope parameter")
        scope = parse_scope(
            request.query_params,
            request.app.state.clock(),
            default,
            settings.history_max_range_days,
            settings.history_max_lookback_days,
        )
    except (ValueError, OverflowError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    request.state.view_scope = scope
    return scope


def scope_url(request: Request, url: str) -> str:
    """Render an internal URL with the request's validated scope."""
    parts = urlsplit(url)
    version = request.query_params.get("android_version")
    if (
        version
        and not parts.netloc
        and not parts.scheme
        and parts.path.removeprefix("/partials").startswith("/crashes")
    ):
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        params.setdefault("android_version", version)
        url = parts.path + "?" + urlencode(params)
    return scoped_url(url, prepare_scope(request))


def quick_url(request: Request, path: str, hours: int) -> str:
    """Replace a custom range and clear stale cursors, retaining other filters."""
    params = dict(request.query_params)
    for key in ("start", "end", "before", "before_id", "open", "log_page"):
        params.pop(key, None)
    params["hours"] = str(hours)
    return path + "?" + urlencode(params)


def release_context(request: Request, scope: ViewScope) -> dict[str, Any]:
    """Keep incomplete discovery and failures distinct from a complete empty result."""
    if hasattr(request.state, "release_context"):
        return cast(dict[str, Any], request.state.release_context)
    labels: tuple[str, ...] = ()
    error = None
    truncated = False
    empty = False
    source = request.app.state.source
    try:
        if not isinstance(source, ReleaseDiscovery):
            raise SourceUnavailableError(
                "unavailable", "source does not support discovery"
            )
        catalogue = source.release_catalogue(scope.window)
        labels, truncated = catalogue.versions, catalogue.truncated
        empty = not truncated and (
            scope.release.kind == "exact"
            and scope.release.value not in labels
            or scope.release.kind == "unknown"
            and not catalogue.has_unknown
        )
    except SourceUnavailableError as exc:
        error = exc.detail
    if scope.release.kind == "exact" and scope.release.value not in labels:
        assert scope.release.value is not None
        labels += (scope.release.value,)
    context = {
        "release_options": sort_releases(labels),
        "discovery_error": error,
        "discovery_truncated": truncated,
        "discovery_empty": empty,
    }
    request.state.release_context = context
    return context


def scope_context(request: Request) -> dict[str, Any]:
    """Build presentation context from one validated request scope."""
    if request.url.path.startswith(("/auth", "/login")):
        return {}
    scope = prepare_scope(request)
    now = request.app.state.clock()
    label = scope.release.value or (
        "Unknown API release" if scope.release.kind == "unknown" else "All API releases"
    )
    context = {
        "view_scope": scope,
        "scope_fields": scope.params(),
        "scope_label": label,
        **release_context(request, scope),
        "range_start": scope.window.start.astimezone(IST).strftime("%Y-%m-%dT%H:%M"),
        "range_end": min(scope.window.end, now)
        .astimezone(IST)
        .strftime("%Y-%m-%dT%H:%M"),
    }
    if scope.custom:
        context["window_label"] = (
            f"{scope.window.start.astimezone(IST):%d %b %Y %H:%M} – {scope.window.end.astimezone(IST):%d %b %Y %H:%M} IST"
        )
        context["comparison_label"] = (
            "Selected period compared with the preceding equal-length period"
        )
    return context
