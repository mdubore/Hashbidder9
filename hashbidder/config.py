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
    mode: Literal["explicit-bids"] | None = None
    upstream: UpstreamModel
    bids: list[BidModel] = Field(default_factory=list)

class TargetHashrateModel(BaseConfigModel):
    model_config = {"extra": "forbid"}
    mode: Literal["target-hashrate"]
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