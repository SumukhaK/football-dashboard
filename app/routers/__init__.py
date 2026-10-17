"""Router registration and navigation data."""

from typing import TypedDict


class NavItem(TypedDict, total=False):
    """One navigation link; a page that can be switched off names its flag."""

    name: str
    path: str
    enabled_by: str


class NavSection(TypedDict):
    """A group of navigation links under its own heading."""

    name: str
    items: list[NavItem]


NAVIGATION: list[NavSection] = [
    {
        "name": "Backend",
        "items": [
            {"name": "Overview", "path": "/"},
            {"name": "Errors", "path": "/errors"},
            {"name": "Requests", "path": "/requests"},
            {"name": "Assistant", "path": "/assistant"},
        ],
    },
    {
        "name": "Android app",
        "items": [
            {"name": "Crashes", "path": "/crashes", "enabled_by": "crashes_enabled"},
        ],
    },
    {
        "name": "Platform",
        "items": [
            {"name": "Data", "path": "/data"},
            {"name": "Access", "path": "/access"},
            # The one page that writes, so it is only offered when it is on.
            {"name": "Invites", "path": "/invites", "enabled_by": "invites_enabled"},
        ],
    },
]
