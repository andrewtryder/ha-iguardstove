"""DataUpdateCoordinator for iGuardStove."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import (
    CannotConnect,
    IGuardStoveClient,
    IGuardStoveException,
    InvalidAuth,
)
from .const import DOMAIN
from .models import CoordinatorData
from .types import DeviceData

_LOGGER = logging.getLogger(__name__)

# Poll every 60 seconds - matches the multiscrape blueprint interval
SCAN_INTERVAL = timedelta(seconds=60)
# Perform dynamic device discovery pass every 6 hours
DISCOVERY_INTERVAL = timedelta(hours=6)


@dataclass
class IGuardStoveData:
    """Runtime data stored in ConfigEntry.runtime_data."""

    client: IGuardStoveClient
    coordinator: "IGuardStoveDataUpdateCoordinator"


type IGuardStoveConfigEntry = ConfigEntry[IGuardStoveData]


class IGuardStoveDataUpdateCoordinator(DataUpdateCoordinator[CoordinatorData]):
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
        self._unavailable_devices: set[str] = set()
        self._last_discovery_time: datetime | None = None
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    async def _async_discover_devices(self) -> bool:
        """Perform dynamic device discovery pass and reconcile registered devices."""
        try:
            discovered = await self.client.async_get_devices()
            discovered_ids = {d["device_id"] for d in discovered}

            new_device_ids = [
                d["device_id"]
                for d in discovered
                if d["device_id"] not in self.device_ids
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

            stale_device_ids = [
                did for did in self.device_ids if did not in discovered_ids
            ]
            if stale_device_ids:
                _LOGGER.info(
                    "Reconciling %d removed iGuardStove device(s): %s",
                    len(stale_device_ids),
                    stale_device_ids,
                )
                for did in stale_device_ids:
                    self.device_ids.remove(did)
                    self._unavailable_devices.discard(did)
                    if self.data and did in self.data.devices:
                        self.data.devices.pop(did, None)
                    if self.data and did in self.data.errors:
                        self.data.errors.pop(did, None)

            return True
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(
                f"Authentication error during discovery pass: {err}"
            ) from err
        except Exception as err:
            _LOGGER.warning("Could not perform dynamic device discovery pass: %s", err)
            return False

    async def _async_update_data(self) -> CoordinatorData:
        """Fetch data for all registered devices with error isolation and discovery."""
        now = dt_util.now()
        if (
            self._last_discovery_time is None
            or now - self._last_discovery_time >= DISCOVERY_INTERVAL
        ):
            if await self._async_discover_devices():
                self._last_discovery_time = now

        event_date = now.date()
        tzinfo = now.tzinfo

        devices: dict[str, DeviceData] = {}
        errors: dict[str, str] = {}
        for device_id in list(self.device_ids):
            try:
                data = await self.client.async_get_device_data(
                    device_id, event_date=event_date, tzinfo=tzinfo
                )
                devices[device_id] = data
                if device_id in self._unavailable_devices:
                    _LOGGER.info("iGuardStove %s is available again", device_id)
                    self._unavailable_devices.remove(device_id)
            except InvalidAuth as err:
                raise ConfigEntryAuthFailed(
                    f"Authentication error for {device_id}: {err}"
                ) from err
            except (CannotConnect, IGuardStoveException) as err:
                if device_id not in self._unavailable_devices:
                    _LOGGER.info("iGuardStove %s is unavailable: %s", device_id, err)
                    self._unavailable_devices.add(device_id)
                errors[device_id] = str(err)

                if self.data and device_id in self.data.devices:
                    devices[device_id] = self.data.devices[device_id]

        if len(errors) == len(self.device_ids) and self.device_ids:
            raise UpdateFailed("Failed to fetch data for all iGuardStove devices")

        return CoordinatorData(devices=devices, errors=errors)
