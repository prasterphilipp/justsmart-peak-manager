"""Home Assistant runtime coordinator for JustSmart Peak Manager."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_GRID_POWER_ENTITY,
    CONF_LOAD_ENTITY,
    CONF_LOAD_NAME,
    CONF_LOAD_POWER,
    CONF_POWER_POLARITY,
    CONF_PROTECT_MONTHLY_PEAK,
    CONF_RESTORE_STEP_A,
    CONF_TARGET_KW,
    CONF_VOLTAGE,
    CONF_WALLBOX_CURRENT_ENTITY,
    CONF_WALLBOX_MAX_A,
    CONF_WALLBOX_MIN_A,
    CONF_WALLBOX_PHASES,
    CONF_WALLBOX_SWITCH_ENTITY,
    CONF_WARNING_MARGIN_KW,
    CONTROL_COOLDOWN_SECONDS,
    DEFAULT_MODE,
    DEFAULT_RESTORE_STEP_A,
    DEFAULT_TARGET_KW,
    DEFAULT_VOLTAGE,
    DEFAULT_WALLBOX_MAX_A,
    DEFAULT_WALLBOX_MIN_A,
    DEFAULT_WALLBOX_PHASES,
    DEFAULT_WARNING_MARGIN_KW,
    DOMAIN,
    MODES,
    STORAGE_KEY,
    STORAGE_SAVE_INTERVAL_SECONDS,
    STORAGE_VERSION,
    UPDATE_INTERVAL_SECONDS,
)
from .controller import ControlConfig, ControlPlanner, ControlState, FlexibleLoad
from .engine import PeakEngine, PeakSnapshot
from .runtime import power_to_w, snapshot_from_dict, snapshot_to_dict

_LOGGER = logging.getLogger(__name__)


class PeakManagerCoordinator(DataUpdateCoordinator[PeakSnapshot]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self.entry = entry
        cfg = self.config
        self.engine = PeakEngine(
            float(cfg.get(CONF_TARGET_KW, DEFAULT_TARGET_KW)),
            float(cfg.get(CONF_WARNING_MARGIN_KW, DEFAULT_WARNING_MARGIN_KW)),
            bool(cfg.get(CONF_PROTECT_MONTHLY_PEAK, True)),
        )
        self.store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry.entry_id}")
        self.mode = DEFAULT_MODE
        self.active_action = "Netzbezug im Zielbereich"
        self.remaining_reduction_kw = 0.0
        self._restored = False
        self._last_saved_interval = None
        self._last_saved_at = None
        self._last_control_at = None
        self._managed_off_contexts: dict[str, str] = {}
        self._wallbox_current_context: str | None = None
        self._wallbox_original_current: float | None = None
        self._wallbox_pause_context: str | None = None
        self._source_was_unavailable = False

    @property
    def config(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    @property
    def view(self) -> PeakSnapshot:
        data = self.data or self.engine.snapshot()
        return replace(data, active_action=self.active_action)

    async def async_load_storage(self) -> None:
        stored = await self.store.async_load() or {}
        self.mode = stored.get("mode") if stored.get("mode") in MODES else DEFAULT_MODE
        raw_snapshot = stored.get("snapshot")
        if isinstance(raw_snapshot, dict):
            try:
                restored = snapshot_from_dict(raw_snapshot)
                self.engine = PeakEngine.from_snapshot(restored)
                self._restored = True
            except (TypeError, ValueError):
                _LOGGER.warning("Ignoring invalid stored Peak Manager state", exc_info=True)
        control = stored.get("control")
        if isinstance(control, dict):
            contexts = control.get("managed_off_contexts")
            if isinstance(contexts, dict):
                self._managed_off_contexts = {
                    str(entity_id): str(context_id)
                    for entity_id, context_id in contexts.items()
                    if entity_id and context_id
                }
            current_context = control.get("wallbox_current_context")
            self._wallbox_current_context = (
                str(current_context) if current_context else None
            )
            original = control.get("wallbox_original_current")
            self._wallbox_original_current = (
                float(original) if original is not None else None
            )
            pause_context = control.get("wallbox_pause_context")
            self._wallbox_pause_context = (
                str(pause_context) if pause_context else None
            )
        self._apply_options_to_engine()

    async def async_save_storage(self) -> None:
        await self.store.async_save(
            {
                "mode": self.mode,
                "snapshot": snapshot_to_dict(self.engine.snapshot()),
                "control": {
                    "managed_off_contexts": self._managed_off_contexts,
                    "wallbox_current_context": self._wallbox_current_context,
                    "wallbox_original_current": self._wallbox_original_current,
                    "wallbox_pause_context": self._wallbox_pause_context,
                },
            }
        )

    async def _async_update_data(self) -> PeakSnapshot:
        cfg = self.config
        source = self.hass.states.get(cfg[CONF_GRID_POWER_ENTITY])
        if source is None or source.state in ("unknown", "unavailable"):
            self._source_was_unavailable = True
            raise UpdateFailed(f"Netzleistung nicht verfügbar: {cfg[CONF_GRID_POWER_ENTITY]}")
        try:
            power_w = power_to_w(source.state, source.attributes.get("unit_of_measurement"))
        except ValueError as err:
            self._source_was_unavailable = True
            raise UpdateFailed(str(err)) from err
        if cfg.get(CONF_POWER_POLARITY, "import_positive") == "import_negative":
            power_w = -power_w
        now = dt_util.now()
        if self._restored or self._source_was_unavailable:
            snapshot = self.engine.resume(power_w, now)
            self._restored = False
            self._source_was_unavailable = False
        else:
            snapshot = self.engine.update(power_w, now)
        snapshot = await self._async_apply_control(snapshot, now)
        save_due = (
            self._last_saved_at is None
            or snapshot.interval_start != self._last_saved_interval
            or (now - self._last_saved_at).total_seconds()
            >= STORAGE_SAVE_INTERVAL_SECONDS
        )
        if save_due:
            self._last_saved_interval = snapshot.interval_start
            self._last_saved_at = now
            await self.async_save_storage()
        return snapshot

    async def _async_apply_control(self, snapshot: PeakSnapshot, now) -> PeakSnapshot:
        planner = ControlPlanner(self._control_config())
        state = self._control_state()
        plan = planner.plan(snapshot, state, self.mode)
        self.remaining_reduction_kw = plan.remaining_reduction_kw
        self.active_action = plan.message
        if plan.actions and self._control_due(now):
            for action in plan.actions:
                await self._async_execute_action(action)
                self._last_saved_interval = snapshot.interval_start
                self._last_saved_at = now
                await self.async_save_storage()
            self._last_control_at = now
        return replace(snapshot, active_action=self.active_action)

    def _control_due(self, now) -> bool:
        return (
            self._last_control_at is None
            or (now - self._last_control_at).total_seconds() >= CONTROL_COOLDOWN_SECONDS
        )

    def _control_config(self) -> ControlConfig:
        cfg = self.config
        loads: list[FlexibleLoad] = []
        for index in range(1, 4):
            entity_id = cfg.get(CONF_LOAD_ENTITY.format(index=index))
            power = cfg.get(CONF_LOAD_POWER.format(index=index))
            if entity_id and power:
                loads.append(
                    FlexibleLoad(
                        str(entity_id),
                        float(power),
                        str(cfg.get(CONF_LOAD_NAME.format(index=index)) or entity_id),
                    )
                )
        switch_entity = cfg.get(CONF_WALLBOX_SWITCH_ENTITY)
        return ControlConfig(
            wallbox_min_a=int(float(cfg.get(CONF_WALLBOX_MIN_A, DEFAULT_WALLBOX_MIN_A))),
            wallbox_max_a=int(float(cfg.get(CONF_WALLBOX_MAX_A, DEFAULT_WALLBOX_MAX_A))),
            wallbox_phases=int(float(cfg.get(CONF_WALLBOX_PHASES, DEFAULT_WALLBOX_PHASES))),
            voltage=float(cfg.get(CONF_VOLTAGE, DEFAULT_VOLTAGE)),
            restore_step_a=int(float(cfg.get(CONF_RESTORE_STEP_A, DEFAULT_RESTORE_STEP_A))),
            wallbox_can_pause=bool(switch_entity),
            flexible_loads=tuple(loads),
        )

    def _control_state(self) -> ControlState:
        cfg = self.config
        current_entity = cfg.get(CONF_WALLBOX_CURRENT_ENTITY)
        switch_entity = cfg.get(CONF_WALLBOX_SWITCH_ENTITY)
        current = None
        current_state = self.hass.states.get(current_entity) if current_entity else None
        if current_state is not None:
            try:
                current = float(str(current_state.state).replace(",", "."))
            except ValueError:
                current = None
        if self._wallbox_current_context and not self._state_has_context(
            current_state, self._wallbox_current_context
        ):
            self._wallbox_current_context = None
            self._wallbox_original_current = None

        switch_state = self.hass.states.get(switch_entity) if switch_entity else None
        wallbox_on = False
        if switch_state is not None:
            wallbox_on = switch_state.state == STATE_ON
        elif current is not None:
            wallbox_on = current > 0
        if self._wallbox_pause_context and not self._state_has_context(
            switch_state, self._wallbox_pause_context
        ):
            self._wallbox_pause_context = None

        loads_on = {
            str(entity_id)
            for index in range(1, 4)
            if (entity_id := cfg.get(CONF_LOAD_ENTITY.format(index=index)))
            and (state := self.hass.states.get(entity_id)) is not None
            and state.state == STATE_ON
        }
        for entity_id, context_id in tuple(self._managed_off_contexts.items()):
            state = self.hass.states.get(entity_id)
            if (
                state is None
                or state.state == STATE_ON
                or not self._state_has_context(state, context_id)
            ):
                self._managed_off_contexts.pop(entity_id, None)

        return ControlState(
            wallbox_current_a=current,
            wallbox_on=wallbox_on,
            wallbox_current_managed=self._wallbox_current_context is not None,
            wallbox_paused_by_manager=self._wallbox_pause_context is not None,
            wallbox_original_a=self._wallbox_original_current,
            loads_on=frozenset(loads_on),
            managed_off=frozenset(self._managed_off_contexts),
        )

    @staticmethod
    def _state_has_context(state, expected_context_id: str) -> bool:
        return bool(
            state is not None
            and state.context is not None
            and str(state.context.id) == expected_context_id
        )

    async def _async_execute_action(self, action) -> None:
        cfg = self.config
        if action.kind == "set_wallbox_current" and (
            entity_id := cfg.get(CONF_WALLBOX_CURRENT_ENTITY)
        ):
            current_state = self.hass.states.get(entity_id)
            if self._wallbox_current_context is None and current_state is not None:
                try:
                    self._wallbox_original_current = float(
                        str(current_state.state).replace(",", ".")
                    )
                except ValueError:
                    self._wallbox_original_current = None
            context = Context()
            await self.hass.services.async_call(
                "number",
                "set_value",
                {"entity_id": entity_id, "value": action.value},
                blocking=True,
                context=context,
            )
            if (
                self._wallbox_original_current is not None
                and action.value < self._wallbox_original_current
            ):
                self._wallbox_current_context = str(context.id)
            else:
                self._wallbox_current_context = None
                self._wallbox_original_current = None
        elif action.kind in ("pause_wallbox", "resume_wallbox") and (
            entity_id := cfg.get(CONF_WALLBOX_SWITCH_ENTITY)
        ):
            domain = str(entity_id).split(".", 1)[0]
            service = "turn_off" if action.kind == "pause_wallbox" else "turn_on"
            context = Context()
            await self.hass.services.async_call(
                domain,
                service,
                {"entity_id": entity_id},
                blocking=True,
                context=context,
            )
            self._wallbox_pause_context = (
                str(context.id) if action.kind == "pause_wallbox" else None
            )
        elif action.kind in ("shed_load", "restore_load") and action.entity_id:
            domain = action.entity_id.split(".", 1)[0]
            service = "turn_off" if action.kind == "shed_load" else "turn_on"
            context = Context()
            await self.hass.services.async_call(
                domain,
                service,
                {"entity_id": action.entity_id},
                blocking=True,
                context=context,
            )
            if action.kind == "shed_load":
                self._managed_off_contexts[action.entity_id] = str(context.id)
            else:
                self._managed_off_contexts.pop(action.entity_id, None)

    async def async_set_target(self, value: float) -> None:
        self.engine.set_target(value)
        await self.async_save_storage()
        await self.async_request_refresh()

    async def async_set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"Unsupported mode: {mode}")
        self.mode = mode
        if mode == "monitor":
            self.active_action = "Monitor-Modus – keine automatische Steuerung"
        await self.async_save_storage()
        await self.async_request_refresh()

    async def async_reset_monthly_peak(self) -> None:
        self.data = self.engine.reset_monthly_peak(dt_util.now())
        await self.async_save_storage()
        self.async_update_listeners()

    def _apply_options_to_engine(self) -> None:
        cfg = self.config
        self.engine.set_target(float(cfg.get(CONF_TARGET_KW, DEFAULT_TARGET_KW)))
        self.engine.state.warning_margin_kw = float(
            cfg.get(CONF_WARNING_MARGIN_KW, DEFAULT_WARNING_MARGIN_KW)
        )
        self.engine.state.protect_monthly_peak = bool(cfg.get(CONF_PROTECT_MONTHLY_PEAK, True))
