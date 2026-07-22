"""DataUpdateCoordinator for iGuardStove."""

import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import (
    CannotConnect,
    IGuardStoveClient,
    IGuardStoveException,
    InvalidAuth,
)
from .const import DOMAIN
from .types import DeviceData

_LOGGER = logging.getLogger(__name__)

# Poll every 60 seconds - matches the multiscrape blueprint interval
SCAN_INTERVAL = timedelta(seconds=60)


@dataclass
class IGuardStoveData:
    """Runtime data stored in ConfigEntry.runtime_data."""

    client: IGuardStoveClient
    coordinator: "IGuardStoveDataUpdateCoordinator"


type IGuardStoveConfigEntry = ConfigEntry[IGuardStoveData]


class IGuardStoveDataUpdateCoordinator(DataUpdateCoordinator[dict[str, DeviceData]]):
    """Coordinator that polls all iGuardStove devices every 60 seconds."""

    config_entry: IGuardStoveConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        client: IGuardStoveClient,
        device_ids: list[str],
    ) -> None:
        """Initialize the coordinator."""
        self.client = client
        self.device_ids = list(device_ids)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, DeviceData]:
        """Fetch data for all registered devices with error isolation and discovery."""
        # Dynamic discovery pass
        try:
            discovered = await self.client.async_get_devices()
            discovered_ids = [d["device_id"] for d in discovered]
            new_device_ids = [
                did for did in discovered_ids if did not in self.device_ids
            ]
            if new_device_ids:
                _LOGGER.info(
                    "Discovered %d new iGuardStove device(s): %s",
                    len(new_device_ids),
                    new_device_ids,
                )
                self.device_ids.extend(new_device_ids)
                if hasattr(self, "config_entry") and self.config_entry:
                    async_dispatcher_send(
                        self.hass,
                        f"{DOMAIN}_{self.config_entry.entry_id}_new_device",
                        new_device_ids,
                    )
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(
                f"Authentication error during discovery pass: {err}"
            ) from err
        except Exception as err:
            _LOGGER.debug("Could not perform dynamic device discovery pass: %s", err)

        results: dict[str, DeviceData] = {}
        for device_id in list(self.device_ids):
            try:
                data = await self.client.async_get_device_data(device_id)
                results[device_id] = data
            except InvalidAuth as err:
                raise ConfigEntryAuthFailed(
                    f"Authentication error for {device_id}: {err}"
                ) from err
            except (CannotConnect, IGuardStoveException, Exception) as err:
                _LOGGER.warning("Error fetching data for device %s: %s", device_id, err)
                if self.data and device_id in self.data:
                    results[device_id] = self.data[device_id]

        if not results and self.device_ids:
            raise UpdateFailed("Failed to fetch data for all iGuardStove devices")

        return results
