"""Sensor platform for iGuardStove."""

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

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
    """Set up iGuardStove sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator

    known_devices = set(coordinator.device_ids)
    entities: list[SensorEntity] = []
    for device_id in coordinator.device_ids:
        entities.extend(
            [
                IGuardStoveStatusSensor(coordinator, device_id),
                IGuardStoveLastCheckinSensor(coordinator, device_id),
                IGuardStoveTemperatureSensor(coordinator, device_id),
            ]
        )

    async_add_entities(entities)

    def _async_add_new_devices(new_device_ids: list[str]) -> None:
        new_entities: list[SensorEntity] = []
        for device_id in new_device_ids:
            if device_id not in known_devices:
                known_devices.add(device_id)
                new_entities.extend(
                    [
                        IGuardStoveStatusSensor(coordinator, device_id),
                        IGuardStoveLastCheckinSensor(coordinator, device_id),
                        IGuardStoveTemperatureSensor(coordinator, device_id),
                    ]
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
