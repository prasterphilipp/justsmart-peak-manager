"""Install and register the bundled Peak Manager Lovelace card."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    FRONTEND_FILE,
    FRONTEND_RESOURCE_ID,
    FRONTEND_TARGET_DIR,
    FRONTEND_URL,
    VERSION,
)

_LOGGER = logging.getLogger(__name__)


def _copy_frontend(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".js.tmp")
    shutil.copy2(source, tmp)
    tmp.replace(target)


async def async_install_frontend(hass: HomeAssistant) -> str:
    source = Path(__file__).parent / "frontend" / FRONTEND_FILE
    target = Path(hass.config.path(FRONTEND_TARGET_DIR, FRONTEND_FILE))
    await hass.async_add_executor_job(_copy_frontend, source, target)
    url = f"{FRONTEND_URL}?v={VERSION}"
    live_updated = await _async_update_live_collection(hass, url)
    if live_updated is None:
        await _async_update_storage(hass, url)
    return url


def _is_peak_resource(item: dict[str, Any]) -> bool:
    return (
        item.get("id") == FRONTEND_RESOURCE_ID
        or urlsplit(str(item.get("url", ""))).path == FRONTEND_URL
    )


async def _async_update_live_collection(hass: HomeAssistant, url: str) -> bool | None:
    lovelace = hass.data.get("lovelace")
    collection = getattr(lovelace, "resources", None)
    if collection is None:
        return None
    try:
        if hasattr(collection, "async_get_info"):
            await collection.async_get_info()
        items = list(collection.async_items())
        matches = [item for item in items if isinstance(item, dict) and _is_peak_resource(item)]
        payload = {"res_type": "module", "url": url}
        if matches:
            await collection.async_update_item(str(matches[0]["id"]), payload)
            for duplicate in matches[1:]:
                await collection.async_delete_item(str(duplicate["id"]))
        else:
            await collection.async_create_item(payload)
        return True
    except Exception:  # A loaded live collection owns persistence; retry later rather than desync storage.
        _LOGGER.debug("Could not update live Lovelace resources", exc_info=True)
        return False


async def _async_update_storage(hass: HomeAssistant, url: str) -> None:
    store: Store[dict[str, Any]] = Store(hass, 1, "lovelace_resources")
    data = await store.async_load() or {}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    updated: list[dict[str, Any]] = []
    matched = False
    for item in items:
        if isinstance(item, dict) and _is_peak_resource(item):
            if not matched:
                updated.append(
                    {**item, "id": item.get("id") or FRONTEND_RESOURCE_ID, "type": "module", "url": url}
                )
                matched = True
            continue
        updated.append(item)
    if not matched:
        updated.append({"id": FRONTEND_RESOURCE_ID, "type": "module", "url": url})
    data["items"] = updated
    await store.async_save(data)
