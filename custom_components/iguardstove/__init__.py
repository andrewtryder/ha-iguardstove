"""The iGuardStove integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .client import IGuardStoveClient
from .const import DOMAIN, USER_AGENT
from .coordinator import IGuardStoveDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.LOCK,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up iGuardStove from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    session = async_create_clientsession(hass, headers={"User-Agent": USER_AGENT})
    client = IGuardStoveClient(
        session,
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )

    # Log in and discover devices
    await client.async_login()

    # Prefer device list stored during config flow; fall back to live discovery
    stored_devices: list[dict] = entry.data.get("devices", [])
    if stored_devices:
        device_ids = [d["device_id"] for d in stored_devices]
    else:
        devices = await client.async_get_devices()
        device_ids = [d["device_id"] for d in devices]

    if not device_ids:
        _LOGGER.error(
            "No iGuardStove devices found for account %s",
            entry.data[CONF_USERNAME],
        )
        return False

    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, device_ids)

    # Perform the first data refresh before setting up platforms
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
