"""Sensor platform for iGuardStove."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import DOMAIN
from .coordinator import (
    IGuardStoveConfigEntry,
    IGuardStoveDataUpdateCoordinator,
)
from .entity import IGuardStoveEntity
from .types import DeviceData

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class IGuardStoveSensorEntityDescription(SensorEntityDescription):
    """Class describing iGuardStove sensor entities."""

    value_fn: Callable[[DeviceData], StateType]
    unit_fn: Callable[[DeviceData], str | None] | None = None
    attr_fn: Callable[[DeviceData], dict[str, Any]] | None = None


SENSOR_DESCRIPTIONS: tuple[IGuardStoveSensorEntityDescription, ...] = (
    IGuardStoveSensorEntityDescription(
        key="status",
        translation_key="status",
        value_fn=lambda d: d.get("status"),
        attr_fn=lambda d: {"status_raw": d.get("status_raw")},
    ),
    IGuardStoveSensorEntityDescription(
        key="last_check_in",
        translation_key="last_check_in",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.get("last_check_in"),
    ),
    IGuardStoveSensorEntityDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("temperature"),
        unit_fn=lambda d: (
            UnitOfTemperature.CELSIUS
            if "C" in d.get("temperature_unit", "°F")
            else UnitOfTemperature.FAHRENHEIT
        ),
    ),
    IGuardStoveSensorEntityDescription(
        key="fires_prevented",
        translation_key="fires_prevented",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.get("fires_prevented"),
    ),
)


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
                IGuardStoveSensor(coordinator, device_id, desc)
                for desc in SENSOR_DESCRIPTIONS
            ]
        )

    async_add_entities(entities)

    @callback
    def _async_add_new_devices(new_device_ids: list[str]) -> None:
        new_entities: list[SensorEntity] = []
        for device_id in new_device_ids:
            if device_id not in known_devices:
                known_devices.add(device_id)
                new_entities.extend(
                    [
                        IGuardStoveSensor(coordinator, device_id, desc)
                        for desc in SENSOR_DESCRIPTIONS
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


class IGuardStoveSensor(IGuardStoveEntity, SensorEntity):
    """Generic description-driven iGuardStove sensor entity."""

    entity_description: IGuardStoveSensorEntityDescription

    def __init__(
        self,
        coordinator: IGuardStoveDataUpdateCoordinator,
        device_id: str,
        description: IGuardStoveSensorEntityDescription,
    ) -> None:
        """Initialize description-driven sensor."""
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def native_value(self) -> StateType:
        """Return native sensor value."""
        data = self._device_data
        if not data:
            return None
        return self.entity_description.value_fn(data)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return native unit of measurement."""
        if self.entity_description.unit_fn:
            data = self._device_data
            if data:
                return self.entity_description.unit_fn(data)
        return self.entity_description.native_unit_of_measurement

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes if configured."""
        if self.entity_description.attr_fn:
            data = self._device_data
            if data is not None:
                return self.entity_description.attr_fn(data)
        return None
