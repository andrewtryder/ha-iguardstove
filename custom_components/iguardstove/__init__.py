"""The iGuardStove integration."""

import logging

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .client import CannotConnect, IGuardStoveClient, InvalidAuth
from .const import USER_AGENT
from .coordinator import (
    IGuardStoveConfigEntry,
    IGuardStoveData,
    IGuardStoveDataUpdateCoordinator,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.LOCK,
    Platform.EVENT,
]


async def async_setup_entry(hass: HomeAssistant, entry: IGuardStoveConfigEntry) -> bool:
    """Set up iGuardStove from a config entry."""
    session = async_create_clientsession(hass, headers={"User-Agent": USER_AGENT})
    client = IGuardStoveClient(
        session,
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )

    try:
        await client.async_login()
    except InvalidAuth as err:
        raise ConfigEntryAuthFailed(
            f"Invalid credentials for account {entry.data[CONF_USERNAME]}"
        ) from err
    except CannotConnect as err:
        raise ConfigEntryNotReady(f"Failed to connect to iGuardFire: {err}") from err

    stored_devices: list[dict] = entry.data.get("devices", [])
    if stored_devices:
        device_ids = [d["device_id"] for d in stored_devices]
    else:
        try:
            devices = await client.async_get_devices()
            device_ids = [d["device_id"] for d in devices]
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(
                f"Invalid credentials discovering devices: {err}"
            ) from err
        except CannotConnect as err:
            raise ConfigEntryNotReady(
                f"Failed to connect discovering devices: {err}"
            ) from err

    if not device_ids:
        _LOGGER.error(
            "No iGuardStove devices found for account %s",
            entry.data[CONF_USERNAME],
        )
        return False

    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, device_ids)
    coordinator.config_entry = entry

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = IGuardStoveData(
        client=client,
        coordinator=coordinator,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: IGuardStoveConfigEntry
) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.client.async_close()
    return unload_ok
