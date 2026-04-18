# Containerization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a minimal, multi-stage `Dockerfile` to seamlessly deploy `hashbidder` as a container.

**Architecture:** Use a multi-stage Docker build based on `python:3.13-slim`. The builder stage will use `uv` to install dependencies into a virtual environment. The final stage will copy the virtual environment and source code, setting the entrypoint to the CLI.

**Tech Stack:** Docker, Python 3.13, `uv`

---

### Task 1: Create Dockerignore

**Files:**
- Create: `.dockerignore`

- [ ] **Step 1: Write .dockerignore**

```dockerignore
.git
.github
.pytest_cache
.ruff_cache
.venv
__pycache__
*.pyc
.env
docs
tests
```

- [ ] **Step 2: Commit**

```bash
git add .dockerignore
git commit -m "build: add .dockerignore file"
```

### Task 2: Create Dockerfile

**Files:**
- Create: `Dockerfile`

- [ ] **Step 1: Write Dockerfile**

```dockerfile
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
```

- [ ] **Step 2: Build and verify**

Run: `docker build -t hashbidder .`
Expected: Successfully builds without errors.

- [ ] **Step 3: Commit**

```bash
git add Dockerfile
git commit -m "build: add multi-stage Dockerfile for containerization"
```

---

Plan complete and saved to `docs/superpowers/plans/2026-04-17-containerization.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration
**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?