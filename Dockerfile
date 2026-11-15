# GenMedia Studio container (Cloud Run).
#
# Layered for fast rebuilds: dependencies install from pyproject.toml/uv.lock
# before the app code is copied, so code-only changes reuse the cached
# dependency layer. .dockerignore keeps experiments, docs and tests out.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PORT=8080

WORKDIR /app

# System libraries for OpenCV (libGL) and GLib.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# uv from its official image (pinned), instead of pip-installing it.
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv

# 1) Dependencies only (cached unless pyproject.toml or uv.lock change).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

# 2) App code.
COPY . .

EXPOSE 8080

# One process per container; Cloud Run scales instances. Mesop keeps UI state
# per session in memory, so one worker plus threads (and session affinity on
# the service) keeps a user on the same state. WEB_CONCURRENCY / THREADS can
# be tuned per deploy.
CMD ["sh", "-c", "exec gunicorn --bind :${PORT} --workers ${WEB_CONCURRENCY:-1} --threads ${THREADS:-8} --timeout 0 --forwarded-allow-ips='*' -k uvicorn.workers.UvicornWorker main:app"]
