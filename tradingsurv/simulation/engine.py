"""simulate(): the Step 9 entry point — old vs new clearing under a scenario."""

from __future__ import annotations

from dataclasses import dataclass

from .actions import ScenarioAction, apply_actions
from .snapshot import AuctionSnapshot


@dataclass(frozen=True)
class ScenarioResult:
    old_price_eur_mwh: float
    new_price_eur_mwh: float
    price_diff_eur_mwh: float
    old_volume_mw: float
    new_volume_mw: float
    old_marginal_technology: str
    new_marginal_technology: str
    old_marginal_asset_id: str
    new_marginal_asset_id: str
    new_snapshot: AuctionSnapshot


def simulate(base: AuctionSnapshot, actions: list[ScenarioAction]) -> ScenarioResult:
    old_result = base.clear()
    new_snapshot = apply_actions(base, actions)
    new_result = new_snapshot.clear()

    return ScenarioResult(
        old_price_eur_mwh=old_result.price_eur_mwh,
        new_price_eur_mwh=new_result.price_eur_mwh,
        price_diff_eur_mwh=new_result.price_eur_mwh - old_result.price_eur_mwh,
        old_volume_mw=old_result.volume_mw,
        new_volume_mw=new_result.volume_mw,
        old_marginal_technology=old_result.marginal_technology,
        new_marginal_technology=new_result.marginal_technology,
        old_marginal_asset_id=old_result.marginal_asset_id,
        new_marginal_asset_id=new_result.marginal_asset_id,
        new_snapshot=new_snapshot,
    )
