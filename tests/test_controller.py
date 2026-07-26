from __future__ import annotations

import pytest

from custom_components.justsmart_peak_manager.controller import (
    ControlConfig,
    ControlPlanner,
    ControlState,
    FlexibleLoad,
)
from custom_components.justsmart_peak_manager.engine import PeakSnapshot


def snapshot(reduction_kw: float, status: str = "limiting") -> PeakSnapshot:
    return PeakSnapshot(
        target_kw=4.5,
        projected_kw=4.5 + reduction_kw,
        recommended_reduction_kw=reduction_kw,
        status=status,
    )


def test_monitor_mode_never_returns_device_actions() -> None:
    planner = ControlPlanner(ControlConfig())
    plan = planner.plan(snapshot(3.0), ControlState(wallbox_current_a=16, wallbox_on=True), "monitor")

    assert plan.actions == ()
    assert plan.requested_reduction_kw == pytest.approx(3.0)
    assert plan.message == "3,0 kW Reduktion empfohlen"


def test_automatic_mode_modulates_wallbox_current_first() -> None:
    planner = ControlPlanner(ControlConfig(wallbox_min_a=6, wallbox_max_a=16, wallbox_phases=3, voltage=230))
    plan = planner.plan(snapshot(3.0), ControlState(wallbox_current_a=16, wallbox_on=True), "automatic")

    assert len(plan.actions) == 1
    assert plan.actions[0].kind == "set_wallbox_current"
    assert plan.actions[0].value == 11
    assert plan.remaining_reduction_kw == 0
    assert plan.message == "Wallbox wird auf 11 A reduziert"


def test_wallbox_is_paused_when_minimum_current_cannot_remove_enough_load() -> None:
    planner = ControlPlanner(ControlConfig(wallbox_min_a=6, wallbox_max_a=16, wallbox_phases=3, voltage=230))
    plan = planner.plan(snapshot(6.0), ControlState(wallbox_current_a=10, wallbox_on=True), "automatic")

    assert plan.actions[0].kind == "pause_wallbox"
    assert plan.remaining_reduction_kw == 0


def test_wallbox_pause_still_happens_when_more_reduction_than_wallbox_power_is_needed() -> None:
    planner = ControlPlanner(
        ControlConfig(
            wallbox_min_a=6,
            wallbox_max_a=16,
            wallbox_phases=3,
            voltage=230,
            flexible_loads=(FlexibleLoad("switch.boiler", 3.0, "Warmwasser"),),
        )
    )
    plan = planner.plan(
        snapshot(9.0),
        ControlState(
            wallbox_current_a=10,
            wallbox_on=True,
            loads_on=frozenset({"switch.boiler"}),
        ),
        "automatic",
    )

    assert [action.kind for action in plan.actions] == ["pause_wallbox", "shed_load"]
    assert plan.remaining_reduction_kw == 0


def test_wallbox_is_never_paused_without_explicit_pause_permission() -> None:
    planner = ControlPlanner(
        ControlConfig(
            wallbox_min_a=6, wallbox_max_a=16, wallbox_phases=3, voltage=230, wallbox_can_pause=False
        )
    )
    plan = planner.plan(snapshot(6.0), ControlState(wallbox_current_a=10, wallbox_on=True), "automatic")

    assert all(action.kind != "pause_wallbox" for action in plan.actions)
    assert plan.actions[0].kind == "set_wallbox_current"
    assert plan.actions[0].value == 6
    assert plan.remaining_reduction_kw > 0


def test_flexible_loads_are_shed_in_priority_order() -> None:
    config = ControlConfig(
        wallbox_min_a=6,
        wallbox_max_a=16,
        flexible_loads=(
            FlexibleLoad("switch.boiler", 2.0, "Warmwasser"),
            FlexibleLoad("switch.pool", 1.0, "Pool"),
        ),
    )
    planner = ControlPlanner(config)
    plan = planner.plan(
        snapshot(2.5),
        ControlState(
            wallbox_current_a=6, wallbox_on=False, loads_on=frozenset({"switch.boiler", "switch.pool"})
        ),
        "automatic",
    )

    assert [action.entity_id for action in plan.actions] == ["switch.boiler", "switch.pool"]
    assert plan.remaining_reduction_kw == 0
    assert "Warmwasser" in plan.message and "Pool" in plan.message


def test_normal_state_restores_only_devices_previously_managed_by_peak_manager() -> None:
    config = ControlConfig(wallbox_max_a=16, restore_step_a=1)
    planner = ControlPlanner(config)
    state = ControlState(
        wallbox_current_a=10,
        wallbox_on=False,
        wallbox_current_managed=True,
        wallbox_paused_by_manager=True,
        wallbox_original_a=16,
        managed_off=frozenset({"switch.boiler"}),
    )
    plan = planner.plan(snapshot(0, status="normal"), state, "automatic")

    assert [action.kind for action in plan.actions] == ["set_wallbox_current"]
    assert plan.actions[0].value == 11


def test_current_modulation_never_reenables_wallbox_switched_off_by_user() -> None:
    planner = ControlPlanner(ControlConfig(restore_step_a=1))
    plan = planner.plan(
        snapshot(0, status="normal"),
        ControlState(
            wallbox_current_a=10,
            wallbox_on=False,
            wallbox_current_managed=True,
            wallbox_paused_by_manager=False,
            wallbox_original_a=16,
        ),
        "automatic",
    )

    assert [action.kind for action in plan.actions] == ["set_wallbox_current"]


def test_wallbox_is_reenabled_only_after_manager_paused_it() -> None:
    planner = ControlPlanner(ControlConfig(restore_step_a=1))
    plan = planner.plan(
        snapshot(0, status="normal"),
        ControlState(
            wallbox_current_a=6,
            wallbox_on=False,
            wallbox_current_managed=True,
            wallbox_paused_by_manager=True,
            wallbox_original_a=6,
        ),
        "automatic",
    )

    assert [action.kind for action in plan.actions] == ["resume_wallbox"]


def test_current_restoration_stops_at_original_limit_not_configured_maximum() -> None:
    planner = ControlPlanner(
        ControlConfig(wallbox_max_a=32, restore_step_a=10)
    )
    plan = planner.plan(
        snapshot(0, status="normal"),
        ControlState(
            wallbox_current_a=8,
            wallbox_current_managed=True,
            wallbox_original_a=10,
        ),
        "automatic",
    )

    assert len(plan.actions) == 1
    assert plan.actions[0].kind == "set_wallbox_current"
    assert plan.actions[0].value == 10


def test_warning_state_holds_managed_devices_instead_of_restoring() -> None:
    planner = ControlPlanner(ControlConfig())
    state = ControlState(
        wallbox_current_a=8,
        wallbox_current_managed=True,
        wallbox_original_a=16,
        managed_off=frozenset({"switch.boiler"}),
    )

    plan = planner.plan(snapshot(0, status="warning"), state, "automatic")

    assert plan.actions == ()


def test_monitor_mode_safely_returns_one_owned_device_per_cycle() -> None:
    planner = ControlPlanner(ControlConfig())
    state = ControlState(managed_off=frozenset({"switch.boiler", "switch.pool"}))

    plan = planner.plan(snapshot(0, status="normal"), state, "monitor")

    assert len(plan.actions) == 1
    assert plan.actions[0].kind == "restore_load"


@pytest.mark.parametrize("status", ["warning", "limiting"])
def test_monitor_mode_does_not_restore_during_elevated_peak(status: str) -> None:
    planner = ControlPlanner(ControlConfig())
    state = ControlState(managed_off=frozenset({"switch.boiler"}))

    plan = planner.plan(snapshot(0, status=status), state, "monitor")

    assert plan.actions == ()


def test_invalid_electrical_configuration_is_rejected() -> None:
    with pytest.raises(ValueError):
        ControlConfig(wallbox_min_a=16, wallbox_max_a=6)
