"""Lock platform for iGuardStove."""

import logging
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import IGuardStoveClient
from .const import DOMAIN
from .coordinator import (
    IGuardStoveConfigEntry,
    IGuardStoveDataUpdateCoordinator,
)
from .entity import IGuardStoveEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IGuardStoveConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iGuardStove lock entities from a config entry."""
    coordinator = entry.runtime_data.coordinator
    client = entry.runtime_data.client

    known_devices = set(coordinator.device_ids)
    entities: list[LockEntity] = [
        IGuardStoveLock(coordinator, client, device_id)
        for device_id in coordinator.device_ids
    ]
    async_add_entities(entities)

    def _async_add_new_devices(new_device_ids: list[str]) -> None:
        new_entities: list[LockEntity] = []
        for device_id in new_device_ids:
            if device_id not in known_devices:
                known_devices.add(device_id)
                new_entities.append(IGuardStoveLock(coordinator, client, device_id))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{DOMAIN}_{entry.entry_id}_new_device",
            _async_add_new_devices,
        )
    )


class IGuardStoveLock(IGuardStoveEntity, LockEntity):
    """Lock entity representing the iGuardStove lockout state.

    Locking the entity engages the night-lock / manual lock on the physical
    device. Unlocking removes it, subject to any schedule configured on the
    device itself.

    For safety against unintended remote appliance activation, this write-capable
    entity is disabled by default in the Home Assistant Entity Registry and requires
    explicit user opt-in to enable.
    """

    _attr_icon = "mdi:stove"
    _attr_translation_key = "stove_lock"
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: IGuardStoveDataUpdateCoordinator,
        client: IGuardStoveClient,
        device_id: str,
    ) -> None:
        """Initialize the lock entity."""
        super().__init__(coordinator, device_id)
        self._client = client
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
        await self._client.async_set_lock_state(self.device_id, True)
        await self.coordinator.async_request_refresh()

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the stove (disengage lockout)."""
        await self._client.async_set_lock_state(self.device_id, False)
        await self.coordinator.async_request_refresh()
