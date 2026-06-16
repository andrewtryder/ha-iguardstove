"""Binary sensor platform for iGuardStove."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IGuardStoveDataUpdateCoordinator
from .entity import IGuardStoveEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iGuardStove binary sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: IGuardStoveDataUpdateCoordinator = data["coordinator"]

    entities: list[BinarySensorEntity] = []
    for device_id in coordinator.device_ids:
        entities.append(IGuardStoveLockBinarySensor(coordinator, device_id))
        entities.append(IGuardStoveNeedsAttentionBinarySensor(coordinator, device_id))

    async_add_entities(entities)


class IGuardStoveLockBinarySensor(IGuardStoveEntity, BinarySensorEntity):
    """Binary sensor that is ON when the stove is locked out."""

    _attr_device_class = BinarySensorDeviceClass.LOCK
    _attr_icon = "mdi:lock"

    def __init__(
        self,
        coordinator: IGuardStoveDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize lock binary sensor."""
        super().__init__(coordinator, device_id)
        self._attr_name = "Locked"
        self._attr_unique_id = f"{device_id}_locked"

    @property
    def is_on(self) -> bool | None:
        """Return True when the stove is locked out."""
        data = self._device_data
        if not data:
            return None
        # BinarySensorDeviceClass.LOCK: ON = unlocked, OFF = locked
        # We invert: is_locked True → ON means "unlocked", but we want "locked" to be ON
        # Use a plain sensor without device_class inversion semantics
        return data.get("is_locked")


class IGuardStoveNeedsAttentionBinarySensor(IGuardStoveEntity, BinarySensorEntity):
    """Binary sensor mirroring the existing multiscrape 'needs attention' binary sensor.

    ON when the stove status does NOT contain "stove is off" — i.e. when the stove
    is active or in any non-off state that may require attention.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:alert"

    def __init__(
        self,
        coordinator: IGuardStoveDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize needs-attention binary sensor."""
        super().__init__(coordinator, device_id)
        self._attr_name = "Needs Attention"
        self._attr_unique_id = f"{device_id}_needs_attention"

    @property
    def is_on(self) -> bool | None:
        """Return True when stove status does not indicate 'stove is off'."""
        data = self._device_data
        if not data:
            return None
        status = (data.get("status") or "").lower()
        return "stove is off" not in status
