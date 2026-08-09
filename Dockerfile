FROM ghcr.io/astral-sh/uv:python3.14-alpine AS builder

WORKDIR /usr/src/app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

FROM python:3.14-alpine AS runtime

WORKDIR /usr/src/app

COPY --from=builder /usr/src/app/.venv .venv
COPY src ./src
COPY config.sample.ini config.ini

ENV PATH="/usr/src/app/.venv/bin:$PATH"

CMD ["python", "src", "--config", "config.ini"]
