"""The Permobil ConnectMe integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import PermobilCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    address: str = entry.data[CONF_ADDRESS]
    coordinator = PermobilCoordinator(hass, entry, address)

    await coordinator.async_start()

    # Wait briefly for first sample so entities have data; non-fatal on timeout.
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:  # noqa: BLE001
        # No initial data yet — entities will become available once first
        # frame arrives. Don't block startup.
        pass

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    coordinator: PermobilCoordinator | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if coordinator is not None:
        await coordinator.async_stop()
    return unload_ok
