# Root Makefile for Hashbidder9

.PHONY: all clean check

all: hashbidder9.s9pk

hashbidder9.s9pk: javascript/index.js icon.png
	start-cli s9pk pack --arch x86_64

javascript/index.js: $(shell find startos -name "*.ts") package.json tsconfig.json
	npm install
	npm run build

clean:
	rm -rf javascript
	rm -f *.s9pk

format:
	uv run ruff format .
	uv run ruff check --select I --fix .

lint:
	uv run ruff check .

typecheck:
	uv run mypy .

test:
	uv run pytest -v

check: format lint typecheck test
