# TransitPulse API + static site for Cloud Run (IMPLEMENTATION_PLAN M7). Runbook: docs/CLOUD_RUN.md.
#
#   docker build -t transitpulse-api:loop .
#   docker run --rm -p 8080:8080 transitpulse-api:loop          # data endpoints answer 503 without a warehouse
#
# Two stages: uv resolves the locked runtime dependencies (main + the `agent` group, nothing for dev, dbt, ML or
# the pipeline) into /app/.venv; the runtime stage gets that venv plus api/ and web/ only, and runs as uid 10001.

FROM python:3.12-slim-bookworm AS build

COPY --from=ghcr.io/astral-sh/uv:0.12.11 /uv /bin/uv

# bytecode is compiled here so a cold start on Cloud Run doesn't pay for it; the venv lives at its final path
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-default-groups --group agent --no-install-project


FROM python:3.12-slim-bookworm AS runtime

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY api ./api
COPY web ./web

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

# files stay root-owned: the app user can read them but not change them
USER 10001:10001
EXPOSE 8080

# Cloud Run sets PORT; exec so uvicorn is PID 1 and gets SIGTERM directly
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
