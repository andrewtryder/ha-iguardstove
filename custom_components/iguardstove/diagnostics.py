"""Diagnostics support for iGuardStove."""

import hashlib
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


def _anonymize_id(val: str) -> str:
    """Anonymize identifier string using a short 8-char SHA-256 digest."""
    return hashlib.sha256(val.encode("utf-8")).hexdigest()[:8]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: IGuardStoveConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator

    devices_data: dict[str, Any] = {}
    errors_data: dict[str, Any] = {}

    if coordinator.data:
        for did, dev_dict in coordinator.data.devices.items():
            anon_id = _anonymize_id(did)
            redacted_dev = async_redact_data(dev_dict, TO_REDACT)
            if "device_id" in redacted_dev:
                redacted_dev["device_id"] = anon_id
            if "device_name" in redacted_dev:
                redacted_dev["device_name"] = f"iGuardStove {anon_id}"
            devices_data[anon_id] = redacted_dev

        for did, err in coordinator.data.errors.items():
            errors_data[_anonymize_id(did)] = err

    diagnostics_data: dict[str, Any] = {
        "config_entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "coordinator": {
            "device_ids": [_anonymize_id(did) for did in coordinator.device_ids],
            "last_update_success": coordinator.last_update_success,
            "data": {
                "devices": devices_data,
                "errors": errors_data,
            },
        },
    }

    return diagnostics_data
