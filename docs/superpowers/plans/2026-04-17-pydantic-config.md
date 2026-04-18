# Pydantic Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shift TOML configuration validation to `pydantic` for robust, type-safe, and human-readable error reporting.

**Architecture:** Replace manual dictionary parsing in `hashbidder/config.py` with `pydantic` BaseModels. Use Pydantic's validation to handle type conversions and domain model initializations. Update test suite to handle Pydantic's structured error strings instead of manually raised `ValueErrors`.

**Tech Stack:** Python 3.13, `pydantic`, `tomllib`

---

### Task 1: Add Pydantic Dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock` (via command)

- [ ] **Step 1: Add dependency**

Run:
```bash
uv add pydantic>=2.9.2
```

- [ ] **Step 2: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add pydantic dependency"
```

### Task 2: Implement Pydantic Models for Config

**Files:**
- Modify: `hashbidder/config.py`

- [ ] **Step 1: Update `hashbidder/config.py` to use Pydantic**

```python
import tomllib
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from hashbidder.domain.bid_config import BidConfig, SetBidsConfig
from hashbidder.domain.hashrate import Hashrate, HashratePrice, HashUnit
from hashbidder.domain.sats import Sats
from hashbidder.domain.stratum_url import StratumUrl
from hashbidder.domain.time_unit import TimeUnit
from hashbidder.domain.upstream import Upstream

__all__ = [
    "BidConfig",
    "ConfigMode",
    "SetBidsConfig",
    "TargetHashrateConfig",
    "load_config",
]

class ConfigMode(Enum):
    EXPLICIT_BIDS = "explicit-bids"
    TARGET_HASHRATE = "target-hashrate"

class UpstreamModel(BaseModel):
    url: str
    identity: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        try:
            StratumUrl(v)
            return v
        except ValueError as e:
            raise ValueError(f"Invalid upstream URL: {e}") from e

class BidModel(BaseModel):
    price_sat_per_ph_day: int
    speed_limit_ph_s: Decimal

    @field_validator("speed_limit_ph_s")
    @classmethod
    def validate_speed(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("speed_limit_ph_s must be positive")
        return v

class BaseConfigModel(BaseModel):
    default_amount_sat: int

class ExplicitBidsModel(BaseConfigModel):
    mode: Literal[ConfigMode.EXPLICIT_BIDS] | None = None
    upstream: UpstreamModel
    bids: list[BidModel] = Field(default_factory=list)

class TargetHashrateModel(BaseConfigModel):
    mode: Literal[ConfigMode.TARGET_HASHRATE]
    upstream: UpstreamModel
    target_hashrate_ph_s: Decimal
    max_bids_count: int

    @field_validator("target_hashrate_ph_s")
    @classmethod
    def validate_target(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("target_hashrate_ph_s must be positive")
        return v

    @field_validator("max_bids_count")
    @classmethod
    def validate_max_bids(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_bids_count must be >= 1")
        return v

from dataclasses import dataclass
@dataclass(frozen=True)
class TargetHashrateConfig:
    default_amount: Sats
    upstream: Upstream
    target_hashrate: Hashrate
    max_bids_count: int

def load_config(path: Path) -> SetBidsConfig | TargetHashrateConfig:
    with path.open("rb") as f:
        try:
            data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ValueError(f"Invalid TOML: {e}") from e

    mode_raw = data.get("mode")
    if mode_raw is not None and mode_raw not in [m.value for m in ConfigMode]:
        valid = ", ".join(repr(m.value) for m in ConfigMode)
        raise ValueError(f"Invalid mode {mode_raw!r}: must be one of {valid}")

    if mode_raw == ConfigMode.TARGET_HASHRATE.value:
        try:
            parsed_target = TargetHashrateModel.model_validate(data)
        except Exception as e:
            raise ValueError(str(e)) from e
        return TargetHashrateConfig(
            default_amount=Sats(parsed_target.default_amount_sat),
            upstream=Upstream(
                url=StratumUrl(parsed_target.upstream.url),
                identity=parsed_target.upstream.identity
            ),
            target_hashrate=Hashrate(parsed_target.target_hashrate_ph_s, HashUnit.PH, TimeUnit.SECOND),
            max_bids_count=parsed_target.max_bids_count
        )
    else:
        try:
            parsed_explicit = ExplicitBidsModel.model_validate(data)
        except Exception as e:
            raise ValueError(str(e)) from e
        bids = tuple(
            BidConfig(
                price=HashratePrice(
                    sats=Sats(b.price_sat_per_ph_day),
                    per=Hashrate(Decimal(1), HashUnit.PH, TimeUnit.DAY),
                ),
                speed_limit=Hashrate(b.speed_limit_ph_s, HashUnit.PH, TimeUnit.SECOND),
            )
            for b in parsed_explicit.bids
        )
        return SetBidsConfig(
            default_amount=Sats(parsed_explicit.default_amount_sat),
            upstream=Upstream(
                url=StratumUrl(parsed_explicit.upstream.url),
                identity=parsed_explicit.upstream.identity
            ),
            bids=bids
        )
```

- [ ] **Step 2: Run tests**

Run: `make test`
Expected: FAIL. Tests in `tests/unit/test_config.py` assert exact `ValueError` match messages which will differ from Pydantic's `ValidationError` strings formatted within `ValueError`.

- [ ] **Step 3: Update `test_config.py` Error Matchers**

In `tests/unit/test_config.py`, replace exact match string checks with relaxed matching (or remove `match=` entirely) for tests checking structural failures (e.g. `test_missing_default_amount_sat`, `test_missing_upstream_url`, etc.). Because Pydantic reports fields contextually, the exact validation messages changed.

Modify `test_config.py` to fix failing tests until `make test` passes.
(Run `uv run pytest tests/unit/test_config.py` iteratively to fix them).

- [ ] **Step 4: Run tests to verify**

Run: `make test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hashbidder/config.py tests/unit/test_config.py
git commit -m "refactor: use pydantic for robust configuration validation"
```

---

Plan complete and saved to `docs/superpowers/plans/2026-04-17-pydantic-config.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration
**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?