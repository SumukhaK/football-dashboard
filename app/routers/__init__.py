"""Router registration and navigation data."""

from dataclasses import dataclass

NAVIGATION = [
    {"name": "Overview", "path": "/"},
    {"name": "Errors", "path": "/errors"},
    {"name": "Requests", "path": "/requests"},
    {"name": "Assistant", "path": "/assistant"},
    {"name": "Data", "path": "/data"},
    {"name": "Access", "path": "/access"},
]


@dataclass
class RouteInfo:
    """Metadata for a single route."""

    path: str
    name: str
