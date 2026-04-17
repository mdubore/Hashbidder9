.PHONY: format lint typecheck imports test check .check-uv

.check-uv:
	@command -v uv >/dev/null 2>&1 || { echo >&2 "Error: 'uv' is not installed. Please install it from https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }

format: .check-uv
	uv run ruff format .
	uv run ruff check --select I --fix .

lint: .check-uv
	uv run ruff check .

typecheck: .check-uv
	uv run mypy .

imports: .check-uv
	uv run lint-imports

test: .check-uv
	uv run pytest -v

check: format lint typecheck imports test
