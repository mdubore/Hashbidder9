# Stage 1: Builder
FROM python:3.13-slim AS builder

# Install curl
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock ./

# Install dependencies into a virtual environment
RUN uv sync --frozen --no-install-project --no-dev

# Copy source code and install project
COPY . .
RUN uv sync --frozen --no-dev

# Stage 2: Final Image
FROM python:3.13-slim

# Install gosu
RUN apt-get update && apt-get install -y gosu && rm -rf /var/lib/apt/lists/*

# Create a non-root user and data directory
RUN useradd -m appuser && mkdir -p /app/data && chown appuser:appuser /app/data

WORKDIR /app

# Copy files and set ownership to the new user
COPY --from=builder --chown=appuser:appuser /app /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Set volume for data persistence
VOLUME /app/data

ENTRYPOINT ["hashbidder"]
