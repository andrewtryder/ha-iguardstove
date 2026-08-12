"""Binary sensor platform for iGuardStove."""

import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import (
    IGuardStoveConfigEntry,
    IGuardStoveDataUpdateCoordinator,
)
from .entity import IGuardStoveEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IGuardStoveConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iGuardStove binary sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator

    known_devices = set(coordinator.device_ids)
    entities: list[BinarySensorEntity] = [
        IGuardStoveLockoutBinarySensor(coordinator, device_id)
        for device_id in coordinator.device_ids
    ]
    async_add_entities(entities)

    @callback
    def _async_add_new_devices(new_device_ids: list[str]) -> None:
        new_entities: list[BinarySensorEntity] = []
        for device_id in new_device_ids:
            if device_id not in known_devices:
                known_devices.add(device_id)
                new_entities.append(
                    IGuardStoveLockoutBinarySensor(coordinator, device_id)
                )
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{DOMAIN}_{entry.entry_id}_new_device",
            _async_add_new_devices,
        )
    )


class IGuardStoveLockoutBinarySensor(IGuardStoveEntity, BinarySensorEntity):
    """Binary sensor for effective stove lockout (Master Lock, Night Lock, etc.).

    on = lockout active, off = not locked out. No LOCK device_class is used
    because that class inverts polarity (on = unlocked).
    """

    _attr_translation_key = "stove_lockout"

    def __init__(
        self,
        coordinator: IGuardStoveDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize the lockout binary sensor."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_stove_lockout"

    @property
    def available(self) -> bool:
        """Return True if entity is available and lockout state is known."""
        return super().available and self.is_on is not None

    @property
    def is_on(self) -> bool | None:
        """Return True when the stove is effectively locked out."""
        data = self._device_data
        if not data:
            return None
        return data.get("is_lockout_active")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return related status and Master Lock for debugging."""
        data = self._device_data
        if not data:
            return None
        return {
            "status": data.get("status"),
            "master_locked": data.get("is_master_locked"),
        }
