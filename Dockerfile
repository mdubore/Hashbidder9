# Stage 1: Builder
FROM python:3.13-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./

# Install dependencies into a virtual environment
RUN uv sync --frozen --no-install-project --no-dev

# Copy source code and install project
COPY . .
RUN uv sync --frozen --no-dev

# Stage 2: Final Image
FROM python:3.13-slim

WORKDIR /app
COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH"

ENTRYPOINT ["hashbidder"]
