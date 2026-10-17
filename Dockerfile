# The console image: Python 3.12, dependencies from the lock file, non-root.
FROM python:3.12-slim

# uv, copied from its published image pinned to the version used to build this
# repository locally.
COPY --from=ghcr.io/astral-sh/uv:0.11.1 /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1

# Dependencies first, so a code change does not reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Only the runtime needs: no fixtures, tests or scripts in the image.
COPY app ./app
COPY contract ./contract
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 console
USER console

ENV PATH="/app/.venv/bin:${PATH}"
EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
