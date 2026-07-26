from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.justsmart_peak_manager.config_flow import _validate_options
from custom_components.justsmart_peak_manager.const import DOMAIN
from custom_components.justsmart_peak_manager.coordinator import PeakManagerCoordinator
from custom_components.justsmart_peak_manager.frontend import (
    _is_peak_resource,
    async_install_frontend,
)


def manager_entry(**extra):
    data = {
        "grid_power_entity": "sensor.grid_import",
        "power_polarity": "import_positive",
        "target_kw": 4.5,
        "warning_margin_kw": 0.5,
        "protect_monthly_peak": True,
    }
    data.update(extra)
    return MockConfigEntry(domain=DOMAIN, data=data)


def test_frontend_resource_matching_does_not_claim_similarly_named_foreign_urls() -> None:
    assert _is_peak_resource(
        {
            "url": "/local/justsmart_peak_manager/justsmart-peak-manager-card.js?v=0.1.1"
        }
    )
    assert not _is_peak_resource(
        {"url": "/local/vendor/justsmart-peak-manager-card-custom.js"}
    )


def test_control_options_reject_incomplete_and_duplicate_flexible_loads() -> None:
    base = {"wallbox_min_a": 6, "wallbox_max_a": 16}
    assert (
        _validate_options({**base, "load_1_entity": "switch.boiler"})
        == "incomplete_load"
    )
    assert (
        _validate_options(
            {
                **base,
                "load_1_entity": "switch.boiler",
                "load_1_power_kw": 2.0,
                "load_2_entity": "switch.boiler",
                "load_2_power_kw": 1.0,
            }
        )
        == "duplicate_load"
    )


@pytest.mark.asyncio
async def test_coordinator_monitors_then_modulates_explicit_wallbox(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "grid_power_entity": "sensor.grid_import",
            "power_polarity": "import_positive",
            "target_kw": 4.5,
            "warning_margin_kw": 0.5,
            "protect_monthly_peak": True,
            "wallbox_current_entity": "number.wallbox_current",

            "wallbox_min_a": 6,
            "wallbox_max_a": 16,
            "wallbox_phases": "3",
            "voltage": 230,
        },
    )
    entry.add_to_hass(hass)
    hass.states.async_set("sensor.grid_import", "6.0", {"unit_of_measurement": "kW"})
    hass.states.async_set("number.wallbox_current", "16", {"unit_of_measurement": "A"})


    calls: list[ServiceCall] = []

    async def capture(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("number", "set_value", capture)
    coordinator = PeakManagerCoordinator(hass, entry)
    await coordinator.async_load_storage()
    await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    assert coordinator.view.projected_kw == pytest.approx(6.0)
    assert coordinator.view.recommended_reduction_kw >= 1.5
    assert coordinator.mode == "monitor"
    assert calls == []

    await coordinator.async_set_mode("automatic")
    await coordinator.async_refresh()

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == "number.wallbox_current"
    assert 6 <= calls[0].data["value"] < 16
    assert coordinator.active_action.startswith("Wallbox wird auf ")


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_state", ["unavailable", "nan", "inf", "-inf"])
async def test_sensor_gap_does_not_integrate_stale_power(
    hass: HomeAssistant, invalid_state: str
) -> None:
    entry = manager_entry()
    entry.add_to_hass(hass)
    hass.states.async_set("sensor.grid_import", "4.0", {"unit_of_measurement": "kW"})
    coordinator = PeakManagerCoordinator(hass, entry)
    await coordinator.async_refresh()
    energy_before = coordinator.engine.state.energy_ws
    coordinator.engine.state.last_timestamp -= timedelta(minutes=1)

    hass.states.async_set(
        "sensor.grid_import", invalid_state, {"unit_of_measurement": "kW"}
    )
    await coordinator.async_refresh()
    assert coordinator.last_update_success is False
    hass.states.async_set("sensor.grid_import", "6.0", {"unit_of_measurement": "kW"})
    await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    assert coordinator.engine.state.energy_ws == pytest.approx(energy_before)
    assert coordinator.view.data_quality == "partial"


@pytest.mark.asyncio
async def test_manual_load_change_revokes_restore_ownership_and_control_state_persists(
    hass: HomeAssistant,
) -> None:
    entry = manager_entry(
        load_1_entity="switch.boiler",
        load_1_power_kw=2.0,
        load_1_name="Warmwasser",
    )
    entry.add_to_hass(hass)
    manager_context = Context()
    hass.states.async_set("switch.boiler", "off", context=manager_context)
    coordinator = PeakManagerCoordinator(hass, entry)
    coordinator._managed_off_contexts = {
        "switch.boiler": str(manager_context.id)
    }
    coordinator._wallbox_original_current = 10.0
    await coordinator.async_save_storage()

    restored = PeakManagerCoordinator(hass, entry)
    await restored.async_load_storage()
    assert restored._managed_off_contexts == coordinator._managed_off_contexts
    assert restored._wallbox_original_current == 10.0
    assert "switch.boiler" in restored._control_state().managed_off

    hass.states.async_set("switch.boiler", "on", context=Context())
    hass.states.async_set("switch.boiler", "off", context=Context())
    assert "switch.boiler" not in restored._control_state().managed_off
    assert restored._managed_off_contexts == {}


@pytest.mark.asyncio
async def test_manual_wallbox_contexts_revoke_current_and_pause_ownership(
    hass: HomeAssistant,
) -> None:
    entry = manager_entry(
        wallbox_current_entity="number.wallbox_current",
        wallbox_switch_entity="switch.wallbox_enabled",
    )
    entry.add_to_hass(hass)
    current_context = Context()
    pause_context = Context()
    hass.states.async_set("number.wallbox_current", "8", context=current_context)
    hass.states.async_set("switch.wallbox_enabled", "off", context=pause_context)
    coordinator = PeakManagerCoordinator(hass, entry)
    coordinator._wallbox_current_context = str(current_context.id)
    coordinator._wallbox_original_current = 10.0
    coordinator._wallbox_pause_context = str(pause_context.id)

    owned = coordinator._control_state()
    assert owned.wallbox_current_managed is True
    assert owned.wallbox_paused_by_manager is True
    assert owned.wallbox_original_a == 10.0

    hass.states.async_set("number.wallbox_current", "9", context=Context())
    hass.states.async_set("switch.wallbox_enabled", "on", context=Context())
    revoked = coordinator._control_state()
    assert revoked.wallbox_current_managed is False
    assert revoked.wallbox_paused_by_manager is False
    assert revoked.wallbox_original_a is None


@pytest.mark.asyncio
async def test_frontend_install_is_persistent_and_idempotent(hass: HomeAssistant) -> None:
    first_url = await async_install_frontend(hass)
    second_url = await async_install_frontend(hass)

    target = hass.config.path("www/justsmart_peak_manager", "justsmart-peak-manager-card.js")
    assert first_url == second_url
    assert "?v=0.1.1" in first_url
    assert "customElements.define" in Path(target).read_text(encoding="utf-8")

    resources = await Store(hass, 1, "lovelace_resources").async_load()
    matches = [item for item in resources["items"] if "justsmart-peak-manager-card" in item.get("url", "")]
    assert len(matches) == 1
    assert matches[0]["type"] == "module"


@pytest.mark.asyncio
async def test_frontend_storage_is_only_used_when_live_collection_is_unavailable(
    hass: HomeAssistant,
) -> None:
    class LiveResources:
        def __init__(self) -> None:
            self.items = []

        async def async_get_info(self) -> None:
            return None

        def async_items(self):
            return list(self.items)

        async def async_create_item(self, payload) -> None:
            self.items.append({"id": "live-resource", **payload})

    resources = LiveResources()
    hass.data["lovelace"] = SimpleNamespace(resources=resources)
    store = Store(hass, 1, "lovelace_resources")
    original = {"items": [{"id": "other", "type": "module", "url": "/local/other.js"}]}
    await store.async_save(original)

    await async_install_frontend(hass)

    assert len(resources.items) == 1
    assert await store.async_load() == original


@pytest.mark.asyncio
async def test_partial_live_resource_failure_does_not_write_storage_fallback(
    hass: HomeAssistant,
) -> None:
    class PartialLiveResources:
        def __init__(self) -> None:
            self.items = []

        async def async_get_info(self) -> None:
            return None

        def async_items(self):
            return list(self.items)

        async def async_create_item(self, payload) -> None:
            self.items.append({"id": "live-resource", **payload})
            raise RuntimeError("simulated persistence failure after live mutation")

    resources = PartialLiveResources()
    hass.data["lovelace"] = SimpleNamespace(resources=resources)
    store = Store(hass, 1, "lovelace_resources")
    original = {"items": [{"id": "other", "type": "module", "url": "/local/other.js"}]}
    await store.async_save(original)

    await async_install_frontend(hass)

    assert len(resources.items) == 1
    assert await store.async_load() == original


@pytest.mark.asyncio
async def test_config_flow_creates_entry_with_power_sensor(
    hass: HomeAssistant, enable_custom_integrations
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "grid_power_entity": "sensor.grid_import",
            "power_polarity": "import_positive",
            "target_kw": 4.5,
            "warning_margin_kw": 0.5,
            "protect_monthly_peak": True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["grid_power_entity"] == "sensor.grid_import"


@pytest.mark.asyncio
async def test_options_flow_rejects_minimum_current_above_maximum(
    hass: HomeAssistant, enable_custom_integrations
) -> None:
    entry = manager_entry()
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "target_kw": 4.5,
            "warning_margin_kw": 0.5,
            "protect_monthly_peak": True,
            "wallbox_min_a": 32,
            "wallbox_max_a": 1,
            "wallbox_phases": "3",
            "voltage": 230,
            "restore_step_a": 1,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_current_range"
