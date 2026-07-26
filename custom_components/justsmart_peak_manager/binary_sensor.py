"""Peak warning binary sensor."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .entity import PeakManagerEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data["justsmart_peak_manager"][entry.entry_id]
    async_add_entities([PeakInterventionSensor(coordinator)])


class PeakInterventionSensor(PeakManagerEntity, BinarySensorEntity):
    _attr_translation_key = "intervention_required"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "intervention_required")

    @property
    def is_on(self) -> bool:
        return self.coordinator.view.status == "limiting"
