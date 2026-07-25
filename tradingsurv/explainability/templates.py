"""Deterministic natural-language rendering of a ScenarioResult (Step 10).

Template-based, not LLM-based — reproducibility matters here (this text may
end up referenced in a REMIT-relevant compliance review, so the same
scenario must always render the same explanation). ``DriverImpact`` is the
source of truth; this only renders it, never the other way around.
"""

from __future__ import annotations

from ..simulation.engine import ScenarioResult
from .driver_analysis import DriverImpact, interaction_residual

MIN_REPORTED_IMPACT_EUR_MWH = 0.01


def render_explanation(result: ScenarioResult, drivers: list[DriverImpact]) -> str:
    lines = [
        f"Price {_direction(result)} from €{result.old_price_eur_mwh:.0f}/MWh to "
        f"€{result.new_price_eur_mwh:.0f}/MWh."
    ]

    if result.old_marginal_technology != result.new_marginal_technology:
        lines.append("")
        lines.append(f"{result.new_marginal_technology} became marginal (was {result.old_marginal_technology}).")

    reported = [d for d in drivers if abs(d.price_impact_eur_mwh) >= MIN_REPORTED_IMPACT_EUR_MWH]
    if reported:
        lines.append("")
        lines.append("Primary drivers:")
        for driver in reported:
            lines.append(f"• {driver.description} ({driver.price_impact_eur_mwh:+.2f} EUR/MWh)")

        residual = interaction_residual(result.price_diff_eur_mwh, drivers)
        if abs(residual) >= MIN_REPORTED_IMPACT_EUR_MWH:
            lines.append(f"• Interaction effects between the above ({residual:+.2f} EUR/MWh)")

    return "\n".join(lines)


def _direction(result: ScenarioResult) -> str:
    if result.new_price_eur_mwh > result.old_price_eur_mwh:
        return "increased"
    if result.new_price_eur_mwh < result.old_price_eur_mwh:
        return "decreased"
    return "remained unchanged"
