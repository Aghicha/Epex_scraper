"""Generation asset — the unit of the asset registry (Step 1 / db.generation_asset)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GenerationAsset:
    """One generation unit in the asset registry.

    ``id`` is a stable identifier (ENTSO-E resource EIC where available,
    otherwise a synthetic id); ``technology`` selects which cost model in
    ``tradingsurv.domain.costs`` applies to it.
    """

    id: str
    zone: str
    name: str
    technology: str
    capacity_mw: float
    efficiency: float | None = None
    fuel: str | None = None
    must_run: bool = False
    owner: str | None = None
    source: str = "manual"

    def __post_init__(self) -> None:
        if self.capacity_mw <= 0:
            raise ValueError(f"capacity_mw must be > 0, got {self.capacity_mw}")
        if self.efficiency is not None and not (0 < self.efficiency <= 1):
            raise ValueError(f"efficiency must be in (0, 1], got {self.efficiency}")
