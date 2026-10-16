"""The invite page: GET /invites and its HTMX form post.

Only mounted when ``invites_enabled`` is on. The code is shown once in the
response body and never logged, put in a URL or cached.
"""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import parse_qs, urlsplit

import fastapi
from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.dependencies import get_invites
from app.services.invites import (
    InvalidEmailError,
    InviteService,
    SourceUnavailableError,
)
from app.templating import templates

router = fastapi.APIRouter(tags=["invites"])

PAGE_TEMPLATE = "invites.html"
RESULT_TEMPLATE = "partials/invite_result.html"
NO_STORE = {"Cache-Control": "no-store"}
CROSS_ORIGIN = 403


def _require_same_origin(request: Request) -> None:
    """Refuse a post sent from another site's page to this console."""
    origin = request.headers.get("origin")
    if origin is not None and urlsplit(origin).netloc != request.headers.get("host"):
        raise StarletteHTTPException(
            status_code=CROSS_ORIGIN, detail="Invites can only be made from this page"
        )


async def _form_email(request: Request) -> str:
    """The ``email`` field of the url-encoded form body."""
    fields = parse_qs((await request.body()).decode(errors="replace"))
    return fields.get("email", [""])[0]


def _create(service: InviteService, email: str) -> dict[str, Any]:
    """The template context for one invite attempt."""
    try:
        return {"invite": service.create(email)}
    except InvalidEmailError as exc:
        return {"error": str(exc)}
    except SourceUnavailableError as exc:
        return {"error": f"The invite was not saved ({exc.kind}): {exc.detail}"}


@router.get("/invites", response_class=HTMLResponse)
def invites_page(request: Request) -> HTMLResponse:
    """Render the invite form."""
    return templates.TemplateResponse(request, PAGE_TEMPLATE, {}, headers=NO_STORE)


@router.post("/invites", response_class=HTMLResponse)
def create_invite(
    request: Request,
    service: Annotated[InviteService, Depends(get_invites)],
    email: Annotated[str, Depends(_form_email)],
) -> HTMLResponse:
    """Create an invite and render its code once, for HTMX to swap in."""
    _require_same_origin(request)
    context = _create(service, email)
    return templates.TemplateResponse(
        request, RESULT_TEMPLATE, context, headers=NO_STORE
    )
