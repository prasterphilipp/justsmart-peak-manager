"""Safe, deterministic action planning for explicitly configured flexible loads."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .engine import PeakSnapshot


@dataclass(frozen=True, slots=True)
class FlexibleLoad:
    entity_id: str
    rated_power_kw: float
    name: str

    def __post_init__(self) -> None:
        if not self.entity_id or "." not in self.entity_id:
            raise ValueError("flexible load requires a valid entity_id")
        if self.rated_power_kw <= 0:
            raise ValueError("rated_power_kw must be positive")


@dataclass(frozen=True, slots=True)
class ControlConfig:
    wallbox_min_a: int = 6
    wallbox_max_a: int = 16
    wallbox_phases: int = 3
    voltage: float = 230.0
    restore_step_a: int = 1
    wallbox_can_pause: bool = True
    flexible_loads: tuple[FlexibleLoad, ...] = ()

    def __post_init__(self) -> None:
        if self.wallbox_min_a <= 0 or self.wallbox_max_a < self.wallbox_min_a:
            raise ValueError("wallbox current range is invalid")
        if self.wallbox_phases not in (1, 3):
            raise ValueError("wallbox_phases must be 1 or 3")
        if self.voltage <= 0 or self.restore_step_a <= 0:
            raise ValueError("voltage and restore step must be positive")


@dataclass(frozen=True, slots=True)
class ControlState:
    wallbox_current_a: float | None = None
    wallbox_on: bool = False
    wallbox_current_managed: bool = False
    wallbox_paused_by_manager: bool = False
    wallbox_original_a: float | None = None
    loads_on: frozenset[str] = frozenset()
    managed_off: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ControlAction:
    kind: str
    entity_id: str | None = None
    value: float | None = None
    estimated_reduction_kw: float = 0.0


@dataclass(frozen=True, slots=True)
class ControlPlan:
    requested_reduction_kw: float
    remaining_reduction_kw: float
    actions: tuple[ControlAction, ...]
    message: str


class ControlPlanner:
    """Plan actions without touching Home Assistant or devices."""

    def __init__(self, config: ControlConfig) -> None:
        self.config = config

    def plan(self, peak: PeakSnapshot, state: ControlState, mode: str) -> ControlPlan:
        requested = max(0.0, float(peak.recommended_reduction_kw))
        if mode != "automatic":
            if (
                mode == "monitor"
                and peak.status == "normal"
                and self._has_managed_devices(state)
            ):
                return self._restoration_plan(state)
            return ControlPlan(requested, requested, (), self._recommendation(requested))
        if peak.status == "normal":
            return self._restoration_plan(state)
        if requested <= 0:
            return ControlPlan(0.0, 0.0, (), "Leistungsreserve wird beobachtet")

        remaining = requested
        actions: list[ControlAction] = []
        messages: list[str] = []
        amps = state.wallbox_current_a
        if state.wallbox_on and amps is not None and amps > 0:
            per_amp_kw = self.config.voltage * self.config.wallbox_phases / 1000.0
            current_power_kw = amps * per_amp_kw
            reducible_to_min_kw = max(0.0, (amps - self.config.wallbox_min_a) * per_amp_kw)
            if (
                self.config.wallbox_can_pause
                and remaining > reducible_to_min_kw
            ):
                actions.append(ControlAction("pause_wallbox", estimated_reduction_kw=current_power_kw))
                remaining = max(0.0, remaining - current_power_kw)
                messages.append("Wallbox wird pausiert")
            elif reducible_to_min_kw > 0:
                reduce_a = min(
                    math.ceil(remaining / per_amp_kw),
                    max(0, math.floor(amps - self.config.wallbox_min_a)),
                )
                if reduce_a > 0:
                    target_a = max(self.config.wallbox_min_a, math.floor(amps - reduce_a))
                    reduction_kw = (amps - target_a) * per_amp_kw
                    actions.append(
                        ControlAction(
                            "set_wallbox_current",
                            value=float(target_a),
                            estimated_reduction_kw=reduction_kw,
                        )
                    )
                    remaining = max(0.0, remaining - reduction_kw)
                    messages.append(f"Wallbox wird auf {target_a} A reduziert")

        if remaining > 0:
            names: list[str] = []
            for load in self.config.flexible_loads:
                if load.entity_id not in state.loads_on:
                    continue
                actions.append(
                    ControlAction(
                        "shed_load",
                        entity_id=load.entity_id,
                        estimated_reduction_kw=load.rated_power_kw,
                    )
                )
                names.append(load.name)
                remaining = max(0.0, remaining - load.rated_power_kw)
                if remaining <= 0:
                    break
            if names:
                messages.append("Flexible Lasten pausiert: " + ", ".join(names))

        if remaining > 0:
            messages.append(f"noch {self._kw(remaining)} kW offen")
        return ControlPlan(
            requested, remaining, tuple(actions), " · ".join(messages) or self._recommendation(requested)
        )

    def _restoration_plan(self, state: ControlState) -> ControlPlan:
        actions: list[ControlAction] = []
        if (
            state.wallbox_current_managed
            and state.wallbox_current_a is not None
            and state.wallbox_original_a is not None
            and state.wallbox_current_a < state.wallbox_original_a
        ):
            target = min(
                state.wallbox_original_a,
                state.wallbox_current_a + self.config.restore_step_a,
            )
            actions.append(ControlAction("set_wallbox_current", value=float(target)))
        elif state.wallbox_paused_by_manager and not state.wallbox_on:
            actions.append(ControlAction("resume_wallbox"))
        elif state.managed_off:
            actions.append(
                ControlAction("restore_load", entity_id=sorted(state.managed_off)[0])
            )
        message = "Verbraucher werden kontrolliert freigegeben" if actions else "Netzbezug im Zielbereich"
        return ControlPlan(0.0, 0.0, tuple(actions), message)

    @staticmethod
    def _has_managed_devices(state: ControlState) -> bool:
        return bool(
            state.wallbox_current_managed
            or state.wallbox_paused_by_manager
            or state.managed_off
        )

    @classmethod
    def _recommendation(cls, value: float) -> str:
        if value <= 0:
            return "Netzbezug im Zielbereich"
        return f"{cls._kw(value)} kW Reduktion empfohlen"

    @staticmethod
    def _kw(value: float) -> str:
        return f"{value:.1f}".replace(".", ",")
