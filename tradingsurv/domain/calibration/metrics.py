"""Error metrics for comparing reconstructed vs actual prices (Step 7)."""

from __future__ import annotations

import statistics


def mae(errors: list[float]) -> float:
    """Mean absolute error. ``errors`` is estimated - actual, per hour."""
    if not errors:
        raise ValueError("cannot compute MAE of an empty sequence")
    return statistics.mean(abs(e) for e in errors)


def rmse(errors: list[float]) -> float:
    if not errors:
        raise ValueError("cannot compute RMSE of an empty sequence")
    return statistics.mean(e**2 for e in errors) ** 0.5


def bias(errors: list[float]) -> float:
    """Mean signed error — positive means the model overestimates on average."""
    if not errors:
        raise ValueError("cannot compute bias of an empty sequence")
    return statistics.mean(errors)
