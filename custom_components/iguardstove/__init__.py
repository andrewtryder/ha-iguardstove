"""The iGuardStove integration."""

import logging
from typing import Any

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .client import CannotConnect, IGuardStoveClient, InvalidAuth
from .const import DOMAIN, USER_AGENT
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
    session = async_create_clientsession(
        hass, auto_cleanup=False, headers={"User-Agent": USER_AGENT}
    )
    client = IGuardStoveClient(
        session,
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    setup_complete = False

    try:
        try:
            await client.async_login()
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(
                f"Invalid credentials for account {entry.data[CONF_USERNAME]}"
            ) from err
        except CannotConnect as err:
            raise ConfigEntryNotReady(
                f"Failed to connect to iGuardFire: {err}"
            ) from err

        stored_devices: list[dict[str, Any]] = entry.data.get("devices", [])
        if stored_devices:
            device_ids = [d["device_id"] for d in stored_devices]
        else:
            try:
                devices = await client.async_get_devices()
                device_ids = [d["device_id"] for d in devices]
                if devices:
                    hass.config_entries.async_update_entry(
                        entry,
                        data={**dict(entry.data), "devices": devices},
                    )
            except InvalidAuth as err:
                raise ConfigEntryAuthFailed(
                    f"Invalid credentials discovering devices: {err}"
                ) from err
            except CannotConnect as err:
                raise ConfigEntryNotReady(
                    f"Failed to connect discovering devices: {err}"
                ) from err

        if not device_ids:
            _LOGGER.warning(
                "No iGuardStove devices found for account %s; keeping entry loaded",
                entry.data[CONF_USERNAME],
            )

        coordinator = IGuardStoveDataUpdateCoordinator(hass, client, device_ids)
        coordinator.config_entry = entry

        await coordinator.async_config_entry_first_refresh()

        entry.runtime_data = IGuardStoveData(
            client=client,
            coordinator=coordinator,
        )

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        setup_complete = True
        return True
    finally:
        if not setup_complete:
            await client.close()


async def async_unload_entry(
    hass: HomeAssistant, entry: IGuardStoveConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and entry.runtime_data and entry.runtime_data.client:
        await entry.runtime_data.client.close()
    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: IGuardStoveConfigEntry,
    device_entry: Any,
) -> bool:
    """Prepare and approve manual removal of a device from this config entry."""
    if device_entry is None:
        return True

    device_id: str | None = None
    for domain, identifier in device_entry.identifiers:
        if domain == DOMAIN:
            device_id = identifier
            break

    if device_id is None:
        return True

    runtime = getattr(config_entry, "runtime_data", None)
    if runtime is not None and runtime.coordinator is not None:
        return bool(runtime.coordinator.async_prepare_device_removal(device_id))

    # Entry is unloaded: active/inactive status cannot be established, so refuse
    # removal rather than pruning and risking the stove silently reappearing on
    # the next setup/discovery pass while it remains registered in the portal.
    return False


async def async_migrate_entry(
    hass: HomeAssistant, config_entry: IGuardStoveConfigEntry
) -> bool:
    """Migrate old entry schemas if version changes."""
    _LOGGER.debug(
        "Migrating iGuardStove config entry from version %s", config_entry.version
    )
    return config_entry.version == 1
