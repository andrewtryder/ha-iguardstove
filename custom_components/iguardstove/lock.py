"""Lock platform for iGuardStove.

Exposes the stove lockout as a Home Assistant lock entity so users can
lock/unlock the stove from the HA UI, automations, and voice assistants.

Note: The iGuardFire portal uses a single "toggle" POST rather than separate
lock/unlock endpoints, so both lock() and unlock() call the same toggle.
The coordinator is refreshed immediately after to reflect the new state.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import IGuardStoveClient
from .const import DOMAIN
from .coordinator import IGuardStoveDataUpdateCoordinator
from .entity import IGuardStoveEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iGuardStove lock entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: IGuardStoveDataUpdateCoordinator = data["coordinator"]
    client: IGuardStoveClient = data["client"]

    entities: list[LockEntity] = []
    for device_id in coordinator.device_ids:
        entities.append(IGuardStoveLock(coordinator, client, device_id))

    async_add_entities(entities)


class IGuardStoveLock(IGuardStoveEntity, LockEntity):
    """Lock entity representing the iGuardStove lockout state.

    Locking the entity engages the night-lock / manual lock on the physical
    device. Unlocking removes it, subject to any schedule configured on the
    device itself.
    """

    _attr_icon = "mdi:stove"

    def __init__(
        self,
        coordinator: IGuardStoveDataUpdateCoordinator,
        client: IGuardStoveClient,
        device_id: str,
    ) -> None:
        """Initialize the lock entity."""
        super().__init__(coordinator, device_id)
        self._client = client
        self._attr_name = "Stove Lock"
        self._attr_unique_id = f"{device_id}_stove_lock"

    @property
    def is_locked(self) -> bool | None:
        """Return True if the stove is currently locked out."""
        data = self._device_data
        if not data:
            return None
        return data.get("is_locked")

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the stove (engage lockout)."""
        data = self._device_data or {}
        if data.get("is_locked"):
            _LOGGER.debug(
                "Device %s is already locked, skipping toggle",
                self.device_id,
            )
            return
        await self._client.async_toggle_lock(self.device_id)
        await self.coordinator.async_request_refresh()

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the stove (disengage lockout)."""
        data = self._device_data or {}
        if not data.get("is_locked"):
            _LOGGER.debug(
                "Device %s is already unlocked, skipping toggle",
                self.device_id,
            )
            return
        await self._client.async_toggle_lock(self.device_id)
        await self.coordinator.async_request_refresh()
