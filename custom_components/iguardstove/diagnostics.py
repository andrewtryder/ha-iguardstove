"""Diagnostics support for iGuardStove."""

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import IGuardStoveConfigEntry

TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
    "password",
    "username",
    "csrfmiddlewaretoken",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: IGuardStoveConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator

    devices_data = (
        async_redact_data(coordinator.data.devices, TO_REDACT)
        if coordinator.data
        else {}
    )
    errors_data = coordinator.data.errors if coordinator.data else {}

    diagnostics_data: dict[str, Any] = {
        "config_entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "coordinator": {
            "device_ids": coordinator.device_ids,
            "last_update_success": coordinator.last_update_success,
            "data": {
                "devices": devices_data,
                "errors": errors_data,
            },
        },
    }

    return diagnostics_data
