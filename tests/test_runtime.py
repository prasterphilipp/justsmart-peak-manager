from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.justsmart_peak_manager.engine import PeakSnapshot
from custom_components.justsmart_peak_manager.runtime import power_to_w, snapshot_from_dict, snapshot_to_dict

TZ = ZoneInfo("Europe/Vienna")


def test_power_units_are_normalized_to_watts() -> None:
    assert power_to_w("4.25", "kW") == pytest.approx(4250)
    assert power_to_w("4250", "W") == pytest.approx(4250)
    assert power_to_w("1,5", "kW") == pytest.approx(1500)
    with pytest.raises(ValueError):
        power_to_w("unavailable", "W")
    with pytest.raises(ValueError):
        power_to_w("4", "kWh")


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_power_conversion_rejects_non_finite_values(value: str) -> None:
    with pytest.raises(ValueError):
        power_to_w(value, "W")


def test_snapshot_storage_round_trip_preserves_timezone_and_core_state() -> None:
    original = PeakSnapshot(
        target_kw=4.5,
        warning_margin_kw=0.4,
        interval_start=datetime(2027, 1, 5, 10, 0, tzinfo=TZ),
        energy_ws=3_600_000,
        last_timestamp=datetime(2027, 1, 5, 10, 10, tzinfo=TZ),
        last_import_w=6_000,
        monthly_peak_kw=4.2,
        monthly_peak_at=datetime(2027, 1, 3, 18, 15, tzinfo=TZ),
        month_key="2027-01",
        data_quality="partial",
    )

    restored = snapshot_from_dict(snapshot_to_dict(original))

    assert restored.target_kw == original.target_kw
    assert restored.interval_start == original.interval_start
    assert restored.last_timestamp == original.last_timestamp
    assert restored.monthly_peak_at == original.monthly_peak_at
    assert restored.energy_ws == original.energy_ws
    assert restored.data_quality == "partial"
