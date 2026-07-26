"""Maintenance buttons."""

from homeassistant.components.button import ButtonEntity

from .entity import PeakManagerEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data["justsmart_peak_manager"][entry.entry_id]
    async_add_entities([ResetMonthlyPeakButton(coordinator)])


class ResetMonthlyPeakButton(PeakManagerEntity, ButtonEntity):
    _attr_translation_key = "reset_monthly_peak"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "reset_monthly_peak")

    async def async_press(self) -> None:
        await self.coordinator.async_reset_monthly_peak()
