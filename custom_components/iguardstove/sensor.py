"""Sensor platform for iGuardStove."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IGuardStoveDataUpdateCoordinator
from .entity import IGuardStoveEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iGuardStove sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: IGuardStoveDataUpdateCoordinator = data["coordinator"]

    entities: list[SensorEntity] = []
    for device_id in coordinator.device_ids:
        entities.extend(
            [
                IGuardStoveStatusSensor(coordinator, device_id),
                IGuardStoveLastCheckinSensor(coordinator, device_id),
                IGuardStoveTemperatureSensor(coordinator, device_id),
                IGuardStoveFiresPreventedSensor(coordinator, device_id),
            ]
        )

    async_add_entities(entities)


class IGuardStoveStatusSensor(IGuardStoveEntity, SensorEntity):
    """Sensor reporting the stove's normalised status string.

    The ``status_raw`` attribute always holds the exact text returned by the
    portal, making it easy to identify new statuses not yet in STATUS_MAP.
    """

    _attr_icon = "mdi:stove"
    _attr_translation_key = "status"

    def __init__(
        self,
        coordinator: IGuardStoveDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize status sensor."""
        super().__init__(coordinator, device_id)
        self._attr_name = "Status"
        self._attr_unique_id = f"{device_id}_status"

    @property
    def native_value(self) -> str | None:
        """Return the normalised stove status label."""
        data = self._device_data
        if not data:
            return None
        return data.get("status")

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the raw portal status string for debugging/issue reporting."""
        data = self._device_data or {}
        return {"status_raw": data.get("status_raw")}


class IGuardStoveLastCheckinSensor(IGuardStoveEntity, SensorEntity):
    """Sensor reporting the last time the stove checked in with the cloud."""

    _attr_icon = "mdi:clock-check-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: IGuardStoveDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize last check-in sensor."""
        super().__init__(coordinator, device_id)
        self._attr_name = "Last Check-In"
        self._attr_unique_id = f"{device_id}_last_check_in"

    @property
    def native_value(self) -> str | None:
        """Return the relative last check-in time string."""
        data = self._device_data
        if not data:
            return None
        return data.get("last_check_in")


class IGuardStoveTemperatureSensor(IGuardStoveEntity, SensorEntity):
    """Sensor reporting the ambient temperature measured by the iGuardStove unit."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: IGuardStoveDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize temperature sensor."""
        super().__init__(coordinator, device_id)
        self._attr_name = "Temperature"
        self._attr_unique_id = f"{device_id}_temperature"

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit matching what the device reports (°F or °C)."""
        data = self._device_data
        if not data:
            return UnitOfTemperature.FAHRENHEIT
        unit_str = data.get("temperature_unit", "°F")
        if "C" in unit_str:
            return UnitOfTemperature.CELSIUS
        return UnitOfTemperature.FAHRENHEIT

    @property
    def native_value(self) -> float | None:
        """Return the temperature value."""
        data = self._device_data
        if not data:
            return None
        return data.get("temperature")


class IGuardStoveFiresPreventedSensor(IGuardStoveEntity, SensorEntity):
    """Sensor reporting cumulative automatic shut-offs (potential fires prevented)."""

    _attr_icon = "mdi:fire-off"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(
        self,
        coordinator: IGuardStoveDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize fires prevented sensor."""
        super().__init__(coordinator, device_id)
        self._attr_name = "Potential Fires Prevented"
        self._attr_unique_id = f"{device_id}_fires_prevented"

    @property
    def native_value(self) -> int | None:
        """Return the cumulative shut-off count."""
        data = self._device_data
        if not data:
            return None
        return data.get("fires_prevented")
