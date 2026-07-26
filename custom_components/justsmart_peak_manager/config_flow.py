"""Config and options flows for JustSmart Peak Manager."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

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
    DEFAULT_RESTORE_STEP_A,
    DEFAULT_TARGET_KW,
    DEFAULT_VOLTAGE,
    DEFAULT_WALLBOX_MAX_A,
    DEFAULT_WALLBOX_MIN_A,
    DEFAULT_WALLBOX_PHASES,
    DEFAULT_WARNING_MARGIN_KW,
    DOMAIN,
    POWER_POLARITIES,
)


def _number(minimum: float, maximum: float, step: float, unit: str):
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _entity(domain: str | list[str], device_class: str | None = None):
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=domain, device_class=device_class))


def _validate_options(data: dict[str, Any]) -> str | None:
    if float(data[CONF_WALLBOX_MIN_A]) > float(data[CONF_WALLBOX_MAX_A]):
        return "invalid_current_range"
    entities: list[str] = []
    for index in range(1, 4):
        entity = data.get(CONF_LOAD_ENTITY.format(index=index))
        power = data.get(CONF_LOAD_POWER.format(index=index))
        if bool(entity) != (power is not None):
            return "incomplete_load"
        if power is not None and float(power) <= 0:
            return "invalid_load_power"
        if entity:
            entity_id = str(entity)
            if entity_id in entities:
                return "duplicate_load"
            entities.append(entity_id)
    return None


class JustSmartPeakManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(str(user_input[CONF_GRID_POWER_ENTITY]))
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="JustSmart Peak Manager", data=user_input)
        schema = vol.Schema(
            {
                vol.Required(CONF_GRID_POWER_ENTITY): _entity("sensor", "power"),
                vol.Required(CONF_POWER_POLARITY, default="import_positive"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=POWER_POLARITIES, translation_key=CONF_POWER_POLARITY
                    )
                ),
                vol.Required(CONF_TARGET_KW, default=DEFAULT_TARGET_KW): _number(0.5, 50, 0.1, "kW"),
                vol.Required(CONF_WARNING_MARGIN_KW, default=DEFAULT_WARNING_MARGIN_KW): _number(
                    0, 10, 0.1, "kW"
                ),
                vol.Required(CONF_PROTECT_MONTHLY_PEAK, default=True): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return PeakManagerOptionsFlow()


class PeakManagerOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := _validate_options(user_input):
                errors["base"] = error
            else:
                return self.async_create_entry(title="", data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            current.update(user_input)
        fields: dict[Any, Any] = {
            vol.Required(CONF_TARGET_KW, default=current.get(CONF_TARGET_KW, DEFAULT_TARGET_KW)): _number(
                0.5, 50, 0.1, "kW"
            ),
            vol.Required(
                CONF_WARNING_MARGIN_KW, default=current.get(CONF_WARNING_MARGIN_KW, DEFAULT_WARNING_MARGIN_KW)
            ): _number(0, 10, 0.1, "kW"),
            vol.Required(
                CONF_PROTECT_MONTHLY_PEAK, default=current.get(CONF_PROTECT_MONTHLY_PEAK, True)
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_WALLBOX_CURRENT_ENTITY,
                description={"suggested_value": current.get(CONF_WALLBOX_CURRENT_ENTITY)},
            ): _entity("number"),
            vol.Optional(
                CONF_WALLBOX_SWITCH_ENTITY,
                description={"suggested_value": current.get(CONF_WALLBOX_SWITCH_ENTITY)},
            ): _entity(["switch", "input_boolean"]),
            vol.Required(
                CONF_WALLBOX_MIN_A, default=current.get(CONF_WALLBOX_MIN_A, DEFAULT_WALLBOX_MIN_A)
            ): _number(1, 32, 1, "A"),
            vol.Required(
                CONF_WALLBOX_MAX_A, default=current.get(CONF_WALLBOX_MAX_A, DEFAULT_WALLBOX_MAX_A)
            ): _number(1, 63, 1, "A"),
            vol.Required(
                CONF_WALLBOX_PHASES, default=current.get(CONF_WALLBOX_PHASES, DEFAULT_WALLBOX_PHASES)
            ): selector.SelectSelector(selector.SelectSelectorConfig(options=["1", "3"])),
            vol.Required(CONF_VOLTAGE, default=current.get(CONF_VOLTAGE, DEFAULT_VOLTAGE)): _number(
                100, 400, 1, "V"
            ),
            vol.Required(
                CONF_RESTORE_STEP_A, default=current.get(CONF_RESTORE_STEP_A, DEFAULT_RESTORE_STEP_A)
            ): _number(1, 10, 1, "A"),
        }
        for index in range(1, 4):
            entity_key, power_key, name_key = (
                CONF_LOAD_ENTITY.format(index=index),
                CONF_LOAD_POWER.format(index=index),
                CONF_LOAD_NAME.format(index=index),
            )
            fields[vol.Optional(entity_key, description={"suggested_value": current.get(entity_key)})] = (
                _entity(["switch", "input_boolean"])
            )
            fields[vol.Optional(power_key, description={"suggested_value": current.get(power_key)})] = (
                _number(0.1, 30, 0.1, "kW")
            )
            fields[vol.Optional(name_key, description={"suggested_value": current.get(name_key)})] = (
                selector.TextSelector()
            )
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(fields), errors=errors
        )
