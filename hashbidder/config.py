"""Bid configuration file parsing."""

import tomllib
from dataclasses import dataclass
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
    """Which set-bids config format a file uses."""

    EXPLICIT_BIDS = "explicit-bids"
    TARGET_HASHRATE = "target-hashrate"


class UpstreamModel(BaseModel):
    """Pydantic model for upstream pool configuration."""

    url: str
    identity: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Ensure the URL is a valid Stratum URL."""
        try:
            StratumUrl(v)
            return v
        except ValueError as e:
            raise ValueError(f"Invalid upstream URL: {e}") from e


class BidModel(BaseModel):
    """Pydantic model for a single bid entry."""

    price_sat_per_ph_day: int
    speed_limit_ph_s: Decimal

    @field_validator("speed_limit_ph_s")
    @classmethod
    def validate_speed(cls, v: Decimal) -> Decimal:
        """Ensure speed limit is positive."""
        if v <= 0:
            raise ValueError("speed_limit_ph_s must be positive")
        return v


class BaseConfigModel(BaseModel):
    """Common fields for all configuration modes."""

    default_amount_sat: int


class ExplicitBidsModel(BaseConfigModel):
    """Configuration model for explicit-bids mode."""

    mode: Literal["explicit-bids"] | None = None
    upstream: UpstreamModel
    bids: list[BidModel] = Field(default_factory=list)


class TargetHashrateModel(BaseConfigModel):
    """Configuration model for target-hashrate mode."""

    model_config = {"extra": "forbid"}
    mode: Literal["target-hashrate"]
    upstream: UpstreamModel
    target_hashrate_ph_s: Decimal
    max_bids_count: int
    max_price_sat_per_ph_day: int | None = None

    @field_validator("target_hashrate_ph_s")
    @classmethod
    def validate_target(cls, v: Decimal) -> Decimal:
        """Ensure target hashrate is positive."""
        if v <= 0:
            raise ValueError("target_hashrate_ph_s must be positive")
        return v

    @field_validator("max_bids_count")
    @classmethod
    def validate_max_bids(cls, v: int) -> int:
        """Ensure max bids count is at least 1."""
        if v < 1:
            raise ValueError("max_bids_count must be >= 1")
        return v

    @field_validator("max_price_sat_per_ph_day")
    @classmethod
    def validate_max_price(cls, v: int | None) -> int | None:
        """Ensure max price, when set, is positive."""
        if v is not None and v <= 0:
            raise ValueError("max_price_sat_per_ph_day must be positive")
        return v


@dataclass(frozen=True)
class TargetHashrateConfig:
    """Parsed set-bids configuration for target-hashrate mode."""

    default_amount: Sats
    upstream: Upstream
    target_hashrate: Hashrate
    max_bids_count: int
    max_price: HashratePrice | None = None


def load_config(path: Path) -> SetBidsConfig | TargetHashrateConfig:
    """Load and validate a set-bids TOML config file using Pydantic.

    Args:
        path: Path to the TOML config file.

    Returns:
        Parsed and validated configuration.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        ValueError: If the config is invalid.
    """
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
        max_price = (
            HashratePrice(
                sats=Sats(parsed_target.max_price_sat_per_ph_day),
                per=Hashrate(Decimal(1), HashUnit.PH, TimeUnit.DAY),
            )
            if parsed_target.max_price_sat_per_ph_day is not None
            else None
        )
        return TargetHashrateConfig(
            default_amount=Sats(parsed_target.default_amount_sat),
            upstream=Upstream(
                url=StratumUrl(parsed_target.upstream.url),
                identity=parsed_target.upstream.identity,
            ),
            target_hashrate=Hashrate(
                parsed_target.target_hashrate_ph_s, HashUnit.PH, TimeUnit.SECOND
            ),
            max_bids_count=parsed_target.max_bids_count,
            max_price=max_price,
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
                identity=parsed_explicit.upstream.identity,
            ),
            bids=bids,
        )
