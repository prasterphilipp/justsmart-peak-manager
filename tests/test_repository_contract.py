from __future__ import annotations

import json
import struct
from pathlib import Path

ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / "justsmart_peak_manager"


def test_manifest_describes_private_hacs_ready_config_flow_integration() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    assert manifest["domain"] == "justsmart_peak_manager"
    assert manifest["config_flow"] is True
    assert manifest["version"] == "0.1.0"
    assert manifest["codeowners"] == ["@prasterphilipp"]


def test_all_runtime_platforms_and_frontend_are_present() -> None:
    expected = {
        "__init__.py",
        "config_flow.py",
        "coordinator.py",
        "engine.py",
        "controller.py",
        "sensor.py",
        "binary_sensor.py",
        "number.py",
        "select.py",
        "button.py",
        "frontend.py",
    }
    assert expected <= {path.name for path in COMPONENT.iterdir()}
    assert (COMPONENT / "frontend" / "justsmart-peak-manager-card.js").is_file()


def test_translations_cover_config_options_and_every_entity_key() -> None:
    for language in ("de", "en"):
        data = json.loads((COMPONENT / "translations" / f"{language}.json").read_text())
        assert "config" in data and "options" in data and "entity" in data
        entity = data["entity"]
        assert {"sensor", "binary_sensor", "number", "select", "button"} <= set(entity)
        assert "projected_power" in entity["sensor"]
        assert "active_action" in entity["sensor"]


def test_hacs_metadata_ci_blueprint_and_documentation_are_shipped() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert hacs["domains"] == ["justsmart_peak_manager"]
    assert (ROOT / ".github" / "workflows" / "ci.yml").is_file()
    assert (ROOT / "blueprints" / "automation" / "justsmart" / "peak_manager_notification.yaml").is_file()
    readme = (ROOT / "README.md").read_text()
    assert "15-Minuten" in readme
    assert "Monitor-Modus" in readme
    assert "Automatik" in readme
    assert "custom:justsmart-peak-manager-card" in readme


def test_home_assistant_brand_icons_have_required_png_sizes() -> None:
    def png_size(path: Path) -> tuple[int, int]:
        data = path.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        return struct.unpack(">II", data[16:24])

    brand = COMPONENT / "brand"
    assert png_size(brand / "icon.png") == (256, 256)
    assert png_size(brand / "icon@2x.png") == (512, 512)
    assert (ROOT / "assets" / "justsmart-peak-manager-icon.svg").is_file()
