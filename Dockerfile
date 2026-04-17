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

# Create a non-root user
RUN useradd -m appuser

WORKDIR /app

# Copy files and set ownership to the new user
COPY --from=builder --chown=appuser:appuser /app /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Switch to the non-root user
USER appuser

ENTRYPOINT ["hashbidder"]
