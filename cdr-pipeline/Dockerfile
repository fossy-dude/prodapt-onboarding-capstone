# Multistage build (astral-sh/uv-docker-example pattern): resolve dependencies
# with uv in a throwaway builder stage, then ship only the venv + source on top
# of a plain python slim image (no uv, no build toolchain, in the final image).

FROM ghcr.io/astral-sh/uv:python3.13-trixie-slim AS builder
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Sync dependencies only (not the project itself — cdr-pipeline is a flat
# src-layout app run via PYTHONPATH=src, not an installable package).
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

FROM python:3.13-slim-trixie

RUN groupadd --system --gid 999 nonroot \
 && useradd --system --gid 999 --uid 999 --create-home nonroot

WORKDIR /app
COPY --from=builder --chown=nonroot:nonroot /app/.venv /app/.venv
COPY --chown=nonroot:nonroot src ./src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

USER nonroot
# Kafka consumer has no listen port; management API is on 8001 (Story 2.5).
EXPOSE 8001

CMD ["python", "-m", "main"]
