"""Native selection form: explicit IST input to a canonical safe GET URL."""

from datetime import datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException

from app.services.labels import IST
from app.services.view_scope import PAGE_PATHS, parse_scope

router = APIRouter(tags=["selection"])
FILTER_FIELDS = (
    "route",
    "status",
    "event",
    "component",
    "type",
    "android_version",
    "tab",
    "severity",
)


@router.get("/selection")
def select_view(request: Request) -> RedirectResponse:
    """Validate form selection, clear stale cursors and redirect within the console."""
    query = request.query_params
    page = query.get("page", "/")
    if page not in PAGE_PATHS or any(len(query.getlist(k)) > 1 for k in query):
        raise HTTPException(422, "invalid selection target or duplicate parameter")
    params = {
        k: v
        for k, v in query.items()
        if k in (*FILTER_FIELDS, "hours", "api_version", "start", "end") and v
    }
    try:
        if "start_ist" in query or "end_ist" in query:
            if any(key in query for key in ("hours", "start", "end")):
                raise ValueError("use one time representation")
            for name in ("start", "end"):
                raw = query.get(name + "_ist", "")
                if len(raw) > 19:
                    raise ValueError("IST input must be a local date and time")
                local = datetime.fromisoformat(raw)
                if local.tzinfo is not None:
                    raise ValueError("IST input must not include another timezone")
                params[name] = local.replace(tzinfo=IST).isoformat()
        settings = request.app.state.config
        scope = parse_scope(
            params,
            request.app.state.clock(),
            settings.default_window_hours,
            settings.history_max_range_days,
            settings.history_max_lookback_days,
        )
    except (ValueError, OverflowError) as exc:
        raise HTTPException(422, str(exc)) from exc
    kept = {k: v for k, v in params.items() if k in FILTER_FIELDS}
    return RedirectResponse(
        page + "?" + urlencode({**kept, **scope.params()}), status_code=303
    )
