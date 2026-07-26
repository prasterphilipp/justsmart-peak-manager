"""Adjustable target peak entity."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfPower

from .entity import PeakManagerEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data["justsmart_peak_manager"][entry.entry_id]
    async_add_entities([PeakLimitNumber(coordinator)])


class PeakLimitNumber(PeakManagerEntity, NumberEntity):
    _attr_translation_key = "peak_limit"
    _attr_native_min_value = 0.5
    _attr_native_max_value = 50.0
    _attr_native_step = 0.1
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "peak_limit")

    @property
    def native_value(self) -> float:
        return self.coordinator.engine.state.target_kw

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_target(float(value))
