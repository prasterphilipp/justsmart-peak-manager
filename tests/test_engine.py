from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.justsmart_peak_manager.engine import PeakEngine, PeakSnapshot

TZ = ZoneInfo("Europe/Vienna")


def at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2027, 1, 5, hour, minute, second, tzinfo=TZ)


def test_first_sample_mid_interval_projects_current_power_conservatively() -> None:
    engine = PeakEngine(target_kw=4.5)
    snapshot = engine.update(6_000, at(10, 7))

    assert snapshot.projected_kw == pytest.approx(6.0)
    assert snapshot.interval_average_kw == pytest.approx(6.0)
    assert snapshot.data_quality == "partial"


def test_projects_clock_aligned_quarter_hour_average() -> None:
    engine = PeakEngine(target_kw=4.5, warning_margin_kw=0.5)
    engine.update(2_000, at(10, 0))
    snapshot = engine.update(6_000, at(10, 5))

    assert snapshot.interval_start == at(10, 0)
    assert snapshot.interval_end == at(10, 15)
    assert snapshot.elapsed_seconds == pytest.approx(300)
    assert snapshot.interval_average_kw == pytest.approx(2.0)
    assert snapshot.projected_kw == pytest.approx(4.6666667)
    assert snapshot.headroom_kw == pytest.approx(-0.1666667)
    assert snapshot.recommended_reduction_kw == pytest.approx(0.25)
    assert snapshot.status == "limiting"


def test_splits_energy_at_quarter_boundary_and_records_month_peak() -> None:
    engine = PeakEngine(target_kw=4.0)
    engine.update(4_000, at(10, 0))
    engine.update(2_000, at(10, 15))
    snapshot = engine.update(2_000, at(10, 20))

    assert snapshot.interval_start == at(10, 15)
    assert snapshot.interval_average_kw == pytest.approx(2.0)
    assert snapshot.monthly_peak_kw == pytest.approx(4.0)
    assert snapshot.monthly_peak_at == at(10, 0)


def test_export_never_reduces_import_energy_or_creates_negative_peak() -> None:
    engine = PeakEngine(target_kw=3.0)
    engine.update(-5_000, at(11, 0))
    snapshot = engine.update(-2_000, at(11, 14, 59))

    assert snapshot.current_import_kw == 0
    assert snapshot.interval_average_kw == 0
    assert snapshot.projected_kw == 0
    assert snapshot.recommended_reduction_kw == 0
    assert snapshot.status == "normal"


def test_month_rollover_resets_monthly_peak() -> None:
    engine = PeakEngine(target_kw=4.0)
    engine.update(7_000, datetime(2027, 1, 31, 23, 45, tzinfo=TZ))
    engine.update(7_000, datetime(2027, 2, 1, 0, 0, tzinfo=TZ))
    snapshot = engine.update(2_000, datetime(2027, 2, 1, 0, 5, tzinfo=TZ))

    assert snapshot.month_key == "2027-02"
    assert snapshot.monthly_peak_kw == 0


def test_restored_engine_does_not_integrate_unobserved_downtime() -> None:
    stored = PeakSnapshot(
        target_kw=4.0,
        warning_margin_kw=0.5,
        interval_start=at(12, 0),
        energy_ws=1_200_000,
        last_timestamp=at(12, 5),
        last_import_w=4_000,
        monthly_peak_kw=3.2,
        monthly_peak_at=at(9, 0),
        month_key="2027-01",
    )
    engine = PeakEngine.from_snapshot(stored)
    snapshot = engine.resume(6_000, at(12, 10))

    assert snapshot.energy_ws == pytest.approx(1_200_000)
    assert snapshot.data_quality == "partial"
    assert snapshot.last_import_w == 6_000


def test_warning_uses_margin_and_sunk_month_peak_can_raise_active_limit() -> None:
    engine = PeakEngine(target_kw=4.0, warning_margin_kw=0.5, protect_monthly_peak=True)
    engine.set_monthly_peak(5.5, at(8, 0))
    engine.update(5_100, at(13, 0))
    snapshot = engine.update(5_100, at(13, 5))

    assert snapshot.active_limit_kw == pytest.approx(5.5)
    assert snapshot.status == "warning"


def test_required_instant_reduction_scales_with_remaining_interval_time() -> None:
    engine = PeakEngine(target_kw=5.0)
    engine.update(4_000, at(10, 0))
    snapshot = engine.update(8_000, at(10, 10))

    assert snapshot.projected_kw == pytest.approx(5.3333333)
    assert snapshot.recommended_reduction_kw == pytest.approx(1.0)


def test_repeated_dst_hour_remains_chronological_and_uses_distinct_intervals() -> None:
    engine = PeakEngine(target_kw=5.0)
    first_fold = datetime(2027, 10, 31, 2, 55, tzinfo=TZ, fold=0)
    second_fold = datetime(2027, 10, 31, 2, 5, tzinfo=TZ, fold=1)

    engine.update(4_000, first_fold)
    snapshot = engine.update(4_000, second_fold)

    assert second_fold.timestamp() > first_fold.timestamp()
    assert snapshot.interval_start.fold == 1
    assert snapshot.interval_start.hour == 2
    assert snapshot.interval_start.minute == 0


def test_resume_across_dst_fold_discards_energy_from_the_previous_absolute_interval() -> None:
    first_fold = datetime(2027, 10, 31, 2, 5, tzinfo=TZ, fold=0)
    second_fold = datetime(2027, 10, 31, 2, 5, tzinfo=TZ, fold=1)
    engine = PeakEngine(target_kw=5.0)
    engine.update(4_000, first_fold)
    assert engine.state.energy_ws > 0

    snapshot = engine.resume(6_000, second_fold)

    assert snapshot.interval_start.fold == 1
    assert snapshot.interval_start.timestamp() != PeakEngine._interval_start(
        first_fold
    ).timestamp()
    assert snapshot.energy_ws == 0
    assert snapshot.elapsed_seconds == pytest.approx(300)
    assert snapshot.seconds_remaining == pytest.approx(600)
    assert snapshot.data_quality == "partial"
