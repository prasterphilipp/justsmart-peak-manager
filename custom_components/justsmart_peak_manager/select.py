"""Operating mode select."""

from homeassistant.components.select import SelectEntity

from .const import MODES
from .entity import PeakManagerEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data["justsmart_peak_manager"][entry.entry_id]
    async_add_entities([PeakModeSelect(coordinator)])


class PeakModeSelect(PeakManagerEntity, SelectEntity):
    _attr_translation_key = "operating_mode"
    _attr_options = MODES

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "operating_mode")

    @property
    def current_option(self) -> str:
        return self.coordinator.mode

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_mode(option)
