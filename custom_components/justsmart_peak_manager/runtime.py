"""Pure runtime helpers shared by the Home Assistant adapter and tests."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from .engine import PeakSnapshot

_DATETIME_FIELDS = ("interval_start", "last_timestamp", "monthly_peak_at")
_STORAGE_FIELDS = (
    "target_kw",
    "warning_margin_kw",
    "protect_monthly_peak",
    "interval_start",
    "energy_ws",
    "last_timestamp",
    "last_import_w",
    "monthly_peak_kw",
    "monthly_peak_at",
    "month_key",
    "data_quality",
)


def power_to_w(state: str | float | int, unit: str | None) -> float:
    """Normalize a Home Assistant power state to watts."""
    try:
        value = float(str(state).strip().replace(",", "."))
    except (TypeError, ValueError) as err:
        raise ValueError(f"invalid power state: {state}") from err
    if not math.isfinite(value):
        raise ValueError(f"invalid power state: {state}")
    normalized = str(unit or "W").strip().lower()
    if normalized == "w":
        return value
    if normalized == "kw":
        return value * 1000.0
    raise ValueError(f"unsupported power unit: {unit}")


def snapshot_to_dict(snapshot: PeakSnapshot) -> dict[str, Any]:
    """Serialize only durable engine state, never transient derived values."""
    data: dict[str, Any] = {}
    for field in _STORAGE_FIELDS:
        value = getattr(snapshot, field)
        data[field] = value.isoformat() if field in _DATETIME_FIELDS and value is not None else value
    return data


def snapshot_from_dict(data: dict[str, Any]) -> PeakSnapshot:
    """Restore durable engine state from Home Assistant Store data."""
    values = {field: data[field] for field in _STORAGE_FIELDS if field in data}
    for field in _DATETIME_FIELDS:
        value = values.get(field)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError(f"stored {field} must contain timezone information")
            values[field] = parsed
    return PeakSnapshot(**values)
