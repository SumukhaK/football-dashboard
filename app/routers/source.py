"""The source page: GET /source.

It says which telemetry source the console is reading, what that source can
answer, and - for a local log file - how the last read of it went. The route owns
no arithmetic; a read that fails becomes the usual banner, never a 500. The
source error is re-exported by the service, so this router imports services only.
"""

from __future__ import annotations

from typing import Annotated

import fastapi
from fastapi import Depends, Request
from fastapi.responses import HTMLResponse

from app.dependencies import get_source_status
from app.services.source_status import SourceStatusService, SourceUnavailableError
from app.templating import templates
from app.view_context import prepare_scope

router = fastapi.APIRouter(tags=["source"], dependencies=[Depends(prepare_scope)])

TEMPLATE = "source.html"


@router.get("/source", response_class=HTMLResponse)
def source_page(
    request: Request,
    service: Annotated[SourceStatusService, Depends(get_source_status)],
) -> HTMLResponse:
    """Render the source page, or the banner when a log file cannot be read."""
    try:
        model = service.build()
    except SourceUnavailableError as exc:
        error = {"kind": exc.kind, "detail": exc.detail}
        return templates.TemplateResponse(
            request, TEMPLATE, {"model": None, "error": error}
        )
    return templates.TemplateResponse(
        request, TEMPLATE, {"model": model, "error": None}
    )
