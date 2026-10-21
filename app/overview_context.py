"""Overview comparison controls using canonical release/time URLs."""

from dataclasses import replace
from urllib.parse import urlencode

from fastapi import Request
from starlette.exceptions import HTTPException

from app.domain.releases import ReleaseSelection
from app.services.release_comparison import SORT_KEYS
from app.view_context import prepare_scope


def comparison_options(request: Request) -> tuple[str, str]:
    """Reject duplicate/unsupported sort controls before any telemetry read."""
    query = request.query_params
    key, order = query.get("release_sort", "version"), query.get(
        "release_order", "desc"
    )
    if (
        any(len(query.getlist(k)) > 1 for k in ("release_sort", "release_order"))
        or key not in SORT_KEYS
        or order not in ("asc", "desc")
    ):
        raise HTTPException(422, "invalid release comparison sort")
    return key, order


def comparison_links(
    request: Request, key: str, order: str
) -> dict[str, dict[str, str]]:
    """Sort links work as native GETs and HTMX swaps with identical URL state."""
    scope = prepare_scope(request)
    links = {}
    for column in SORT_KEYS:
        direction = "asc" if column == key and order == "desc" else "desc"
        params = {**scope.params(), "release_sort": column, "release_order": direction}
        query = urlencode(params)
        links[column] = {
            "href": "/?" + query,
            "partial": "/partials/overview?" + query,
            "aria_sort": (
                ("ascending" if order == "asc" else "descending")
                if column == key
                else "none"
            ),
        }
    return links


def release_url(request: Request, version: str | None) -> str:
    """Switch to the row's exact release without overwriting it with incoming all."""
    scope = replace(
        prepare_scope(request),
        release=ReleaseSelection.from_query(version or "unknown"),
    )
    return "/?" + urlencode(scope.params())


def overview_refresh_url(request: Request) -> str:
    """Refresh the exact same period, selection and validated sort controls."""
    key, order = comparison_options(request)
    params = {
        **prepare_scope(request).params(),
        "release_sort": key,
        "release_order": order,
    }
    return "/partials/overview?" + urlencode(params)
