"""Lock platform for iGuardStove Master Lock."""

import logging
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import IGuardStoveClient
from .const import CONF_ALLOW_REMOTE_UNLOCK, DOMAIN
from .coordinator import (
    IGuardStoveConfigEntry,
    IGuardStoveDataUpdateCoordinator,
)
from .entity import IGuardStoveEntity
from .exceptions import CannotConnect, InvalidAuth

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IGuardStoveConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iGuardStove Master Lock entities from a config entry."""
    coordinator = entry.runtime_data.coordinator
    client = entry.runtime_data.client

    known_devices = set(coordinator.device_ids)
    entities: list[LockEntity] = [
        IGuardStoveLock(coordinator, client, device_id)
        for device_id in coordinator.device_ids
    ]
    async_add_entities(entities)

    @callback
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
    """Lock entity representing the iGuardStove Master Lock.

    This entity controls the remote Master Lock toggle on the portal form.
    It does not represent Scheduled/Night Lock or other schedule-driven
    lockouts; those are exposed via the Stove lockout binary sensor and the
    Status sensor.

    For safety against unintended remote appliance activation, this write-capable
    entity is disabled by default in the Home Assistant Entity Registry and requires
    explicit user opt-in to enable.
    """

    _attr_translation_key = "master_lock"
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: IGuardStoveDataUpdateCoordinator,
        client: IGuardStoveClient,
        device_id: str,
    ) -> None:
        """Initialize the Master Lock entity."""
        super().__init__(coordinator, device_id)
        self._client = client
        self._attr_unique_id = f"{device_id}_master_lock"

    @property
    def available(self) -> bool:
        """Return True if entity is available and Master Lock state is known."""
        return super().available and self.is_locked is not None

    @property
    def is_locked(self) -> bool | None:
        """Return True if Master Lock is currently engaged."""
        data = self._device_data
        if not data:
            return None
        return data.get("is_master_locked")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return related status and lockout for debugging."""
        data = self._device_data
        if not data:
            return None
        return {
            "status": data.get("status"),
            "lockout_active": data.get("is_lockout_active"),
        }

    async def async_lock(self, **kwargs: Any) -> None:
        """Engage Master Lock."""
        try:
            await self._client.async_set_lock_state(self.device_id, True)
        except InvalidAuth as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="authentication_failed",
            ) from err
        except CannotConnect as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="lock_command_failed",
            ) from err

        await self.coordinator.async_request_refresh()

    async def async_unlock(self, **kwargs: Any) -> None:
        """Disengage Master Lock."""
        allow_unlock = self.coordinator.config_entry.options.get(
            CONF_ALLOW_REMOTE_UNLOCK, False
        )
        if not allow_unlock:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="remote_unlock_disabled",
            )

        try:
            await self._client.async_set_lock_state(self.device_id, False)
        except InvalidAuth as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="authentication_failed",
            ) from err
        except CannotConnect as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="lock_command_failed",
            ) from err

        await self.coordinator.async_request_refresh()
