"""DataUpdateCoordinator for iGuardStove."""

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import (
    CannotConnect,
    IGuardStoveClient,
    IGuardStoveException,
    InvalidAuth,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Poll every 60 seconds - matches the multiscrape blueprint interval
SCAN_INTERVAL = timedelta(seconds=60)


class IGuardStoveDataUpdateCoordinator(
    DataUpdateCoordinator[dict[str, dict[str, Any]]]
):
    """Coordinator that polls all iGuardStove devices every 60 seconds.

    Data structure:
      { "<device_id>": { ...parsed device data... }, ... }
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: IGuardStoveClient,
        device_ids: list[str],
    ) -> None:
        """Initialize the coordinator."""
        self.client = client
        self.device_ids = device_ids
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Fetch data for all registered devices."""
        results: dict[str, dict[str, Any]] = {}
        for device_id in self.device_ids:
            try:
                data = await self.client.async_get_device_data(device_id)
                results[device_id] = data
            except CannotConnect as err:
                raise UpdateFailed(
                    f"Error communicating with iGuardFire for {device_id}: {err}"
                ) from err
            except InvalidAuth as err:
                raise UpdateFailed(
                    f"Authentication error for {device_id}: {err}"
                ) from err
            except IGuardStoveException as err:
                raise UpdateFailed(
                    f"Error fetching data for {device_id}: {err}"
                ) from err
        return results
