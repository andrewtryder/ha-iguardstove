"""Base IGuardStoveEntity class."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import IGuardStoveDataUpdateCoordinator
from .types import DeviceData


class IGuardStoveEntity(CoordinatorEntity[IGuardStoveDataUpdateCoordinator]):
    """Base class for iGuardStove entities.

    All entities share the same coordinator and are keyed by device_id.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: IGuardStoveDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.device_id = device_id

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.device_id in self.coordinator.data.devices
            and self.device_id not in self.coordinator.data.errors
        )

    @property
    def _device_data(self) -> DeviceData | None:
        """Return the data dict for this device from the coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.devices.get(self.device_id)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information for this stove."""
        data = self._device_data or {}
        device_name = data.get("device_name", "iGuardStove")
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=device_name,
            manufacturer="iGuardFire",
            model="iGuardStove",
            configuration_url=(
                f"https://manage.iguardfire.com/devices/{self.device_id}/"
            ),
        )
