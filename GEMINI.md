# Project Overview

`hashbidder` is a Python-based CLI tool designed to manage bidding on the [Braiins Hashpower](https://academy.braiins.com/en/braiins-hashpower/about/) market automatically. It uses the Hashpower API to align open bids with a provided configuration file. The tool is particularly tailored for miners at the [OCEAN Pool](https://ocean.xyz/) running their own DATUM gateway.

**Main Technologies:**
- **Language:** Python >= 3.13
- **Package Manager / Runner:** `uv`
- **CLI Framework:** `click`
- **HTTP Client:** `httpx`
- **Configuration:** `python-dotenv` for `.env` files, TOML for bid configuration.
- **Build System:** `hatchling`

**Architecture:**
The project follows a clean architecture approach, strictly enforced via `import-linter`.
- **Domain Layer (`hashbidder.domain`):** Contains core business logic and models. It has no outward dependencies on use cases, clients, or the CLI.
- **Use Cases (`hashbidder.use_cases`):** Independent modules handling specific actions (e.g., hashvalue calculation, pinging the market, setting bids manually or by target hashrate). They must not import from the CLI layer.
- **CLI Layer (`hashbidder.main`):** The entry point built with `click`.

# Building and Running

**Prerequisites:**
You need `uv` installed to manage dependencies and run the application. `uv` will automatically create a virtual environment and install dependencies on the first run.

**Configuration:**
1. Copy the example environment file: `cp .env.example .env`
2. Fill in your Braiins API key (Owner key is required for bidding; Read-only key is sufficient for `ping` and read operations).
3. If using `target-hashrate` mode, set your `OCEAN_ADDRESS` in `.env`.
4. Create a TOML bid config file (e.g., `bids.toml`) defining either `manual` bids or `target-hashrate` goals.

**Running the Application:**
Use `uv run hashbidder` to execute CLI commands.

*Examples:*
- Show help: `uv run hashbidder --help`
- Fetch the order book: `uv run hashbidder ping`
- Print current bids: `uv run hashbidder bids`
- Reconcile bids (Dry run): `uv run hashbidder set-bids --bid-config bids.toml --dry-run`
- Reconcile bids (Execute): `uv run hashbidder set-bids --bid-config bids.toml`

# Development Conventions

The project has established commands to ensure code quality, formatting, and strict type safety.

**Testing and Validation:**
Run the following commands using `make`:
- `make check`: Runs all checks (formatting, linting, type-checking, import linting, and tests). This is the recommended command before submitting changes.
- `make format`: Formats code using `ruff`.
- `make lint`: Lints code using `ruff`.
- `make typecheck`: Runs strict type-checking using `mypy`.
- `make imports`: Validates architectural boundaries using `import-linter`.
- `make test`: Runs the test suite using `pytest`.

**Coding Style:**
- **Line Length:** 88 characters.
- **Docstrings:** Follow the Google convention.
- **Typing:** Strict typing is enforced (`strict = true` in mypy configuration).
- **Exceptions:** The `S101` rule (use of `assert`) is ignored in tests, `hashbidder/main.py`, and `hashbidder/domain/stratum_url.py`.