"""models.toml loader: tiers, replica lineup, Stage 3 executor."""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .paths import ROOT

SUBSCRIPTION_ROUTES = {"claude_p", "codex"}


class ModelSpec(BaseModel):
    route: str
    model: str
    generation_mode: Literal["agentic", "tool_free"] = "agentic"


class ReplicaSpec(ModelSpec):
    runs: int = 1


class Config(BaseModel):
    contract_strategy: Literal["monolithic", "chunked"] = "monolithic"
    descriptive_readouts: bool = True
    scoped_multiverse: bool = False
    multiverse_min_active_dimensions: int = Field(default=0, ge=0)
    tiers: dict[str, ModelSpec]
    replicas: dict[str, ReplicaSpec] = {}
    executor: ModelSpec | None = None
    # USD per million tokens for routes that report no price, keyed by model name.
    shadow_prices: dict[str, float] = {}


@lru_cache(maxsize=16)
def _parse(text: str) -> Config:
    return Config.model_validate(tomllib.loads(text))


def _load(path_str: str) -> Config:
    return _parse(Path(path_str).read_text())


def config(path: Path | None = None) -> Config:
    return _load(str(path or os.environ.get("REPROSCOPE_MODELS") or ROOT / "models.toml"))


def tier(name: str) -> ModelSpec:
    c = config()
    if name not in c.tiers:
        raise KeyError(f"unknown tier {name!r}; have {sorted(c.tiers)}")
    return c.tiers[name]


def replicas() -> dict[str, ReplicaSpec]:
    return config().replicas


def shadow_price(model: str) -> float | None:
    """USD per million tokens assumed for a model whose route reports no price."""
    return config().shadow_prices.get(model)


def executor() -> ModelSpec:
    e = config().executor
    if e is None:
        raise KeyError("no [executor] section in models.toml")
    return e


def all_specs() -> list[tuple[str, ModelSpec]]:
    """Every distinct (route, model) in the config, labelled by where it came from."""
    c = config()
    seen: dict[tuple[str, str], str] = {}
    for name, spec in c.tiers.items():
        seen.setdefault((spec.route, spec.model), f"tier:{name}")
    for name, spec in c.replicas.items():
        seen.setdefault((spec.route, spec.model), f"replica:{name}")
    if c.executor:
        seen.setdefault((c.executor.route, c.executor.model), "executor")
    return [(label, ModelSpec(route=r, model=m)) for (r, m), label in seen.items()]
