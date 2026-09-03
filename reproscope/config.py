"""models.toml loader: tiers, replica lineup, Stage 3 executor."""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from .paths import ROOT

SUBSCRIPTION_ROUTES = {"claude_p", "codex"}


class ModelSpec(BaseModel):
    route: str
    model: str


class ReplicaSpec(ModelSpec):
    runs: int = 1


class Config(BaseModel):
    tiers: dict[str, ModelSpec]
    replicas: dict[str, ReplicaSpec] = {}
    executor: ModelSpec | None = None
    # USD per million tokens for routes that report no price, keyed by model name.
    shadow_prices: dict[str, float] = {}


@lru_cache(maxsize=None)
def _load(path_str: str) -> Config:
    return Config.model_validate(tomllib.loads(Path(path_str).read_text()))


def config(path: Path | None = None) -> Config:
    return _load(str(path or ROOT / "models.toml"))


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
