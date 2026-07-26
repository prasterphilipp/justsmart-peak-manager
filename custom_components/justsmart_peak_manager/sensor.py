"""Sensors for JustSmart Peak Manager."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfPower, UnitOfTime

from .entity import PeakManagerEntity


@dataclass(frozen=True, kw_only=True)
class PeakSensorDescription(SensorEntityDescription):
    value_fn: Callable = lambda data: None


SENSORS = (
    PeakSensorDescription(
        key="current_import_power",
        translation_key="current_import_power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.current_import_kw,
    ),
    PeakSensorDescription(
        key="interval_average_power",
        translation_key="interval_average_power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.interval_average_kw,
    ),
    PeakSensorDescription(
        key="projected_power",
        translation_key="projected_power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.projected_kw,
    ),
    PeakSensorDescription(
        key="active_limit",
        translation_key="active_limit",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.active_limit_kw,
    ),
    PeakSensorDescription(
        key="headroom",
        translation_key="headroom",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.headroom_kw,
    ),
    PeakSensorDescription(
        key="monthly_peak",
        translation_key="monthly_peak",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.monthly_peak_kw,
    ),
    PeakSensorDescription(
        key="recommended_reduction",
        translation_key="recommended_reduction",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.recommended_reduction_kw,
    ),
    PeakSensorDescription(
        key="interval_remaining",
        translation_key="interval_remaining",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.seconds_remaining),
    ),
    PeakSensorDescription(key="status", translation_key="status", value_fn=lambda d: d.status),
    PeakSensorDescription(
        key="active_action", translation_key="active_action", value_fn=lambda d: d.active_action
    ),
    PeakSensorDescription(
        key="data_quality", translation_key="data_quality", value_fn=lambda d: d.data_quality
    ),
    PeakSensorDescription(
        key="interval_start",
        translation_key="interval_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.interval_start,
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data["justsmart_peak_manager"][entry.entry_id]
    async_add_entities(PeakSensor(coordinator, description) for description in SENSORS)


class PeakSensor(PeakManagerEntity, SensorEntity):
    entity_description: PeakSensorDescription

    def __init__(self, coordinator, description: PeakSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.view)

    @property
    def extra_state_attributes(self):
        if self.entity_description.key == "monthly_peak":
            return {
                "occurred_at": self.coordinator.view.monthly_peak_at,
                "month": self.coordinator.view.month_key,
            }
        if self.entity_description.key == "status":
            return {
                "remaining_reduction_kw": self.coordinator.remaining_reduction_kw,
                "mode": self.coordinator.mode,
            }
        return None
