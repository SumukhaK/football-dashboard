"""The ASGI entry point: ``uvicorn app.main:app`` serves the configured console.

The factory lives in ``app.factory``, so the fixture demo launcher can build its
own app without also building this environment-configured one.
"""

from app.factory import create_app

app = create_app()
