"""Diagnostics support for iGuardStove."""

import hashlib
import re
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import BASE_URL
from .coordinator import IGuardStoveConfigEntry

TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
    "password",
    "username",
    "csrfmiddlewaretoken",
}

EMAIL_RE = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")


def _anonymize_id(val: str) -> str:
    """Anonymize identifier string using a short 8-char SHA-256 digest."""
    if not val:
        return ""
    return hashlib.sha256(val.encode("utf-8")).hexdigest()[:8]


def _sanitize_string(val: str) -> str:
    """Sanitize string values by scrubbing URLs, emails, and sensitive terms."""
    if not isinstance(val, str):
        return val
    s = val.replace(BASE_URL, "[REDACTED_URL]")
    s = EMAIL_RE.sub("[REDACTED_EMAIL]", s)
    return s


def _sanitize_nested(obj: Any, sensitive_tokens: tuple[str, ...]) -> Any:
    """Recursively sanitize dictionary/list structure against sensitive tokens."""
    if isinstance(obj, dict):
        res = {}
        for k, v in obj.items():
            if k in TO_REDACT:
                res[k] = "**REDACTED**"
            else:
                res[k] = _sanitize_nested(v, sensitive_tokens)
        return res
    elif isinstance(obj, list | tuple):
        sanitized = [_sanitize_nested(item, sensitive_tokens) for item in obj]
        return tuple(sanitized) if isinstance(obj, tuple) else sanitized
    elif isinstance(obj, str):
        s = _sanitize_string(obj)
        for tok in sensitive_tokens:
            if tok and len(tok) >= 3 and tok in s:
                s = s.replace(tok, f"[REDACTED_{_anonymize_id(tok)}]")
        return s
    return obj


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: IGuardStoveConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry with strict redaction."""
    coordinator = entry.runtime_data.coordinator

    # Build sensitive tokens list to scrub from nested text
    username = entry.data.get(CONF_USERNAME, "")
    password = entry.data.get(CONF_PASSWORD, "")
    device_tokens: list[str] = []
    for d in entry.data.get("devices", []):
        if isinstance(d, dict):
            for key in ("device_id", "device_name"):
                val = d.get(key)
                if isinstance(val, str) and val:
                    device_tokens.append(val)
    device_tokens.extend(coordinator.device_ids)
    if coordinator.data:
        for did, dev_dict in coordinator.data.devices.items():
            device_tokens.append(did)
            name = dev_dict.get("device_name")
            if isinstance(name, str) and name:
                device_tokens.append(name)

    sensitive_tokens = tuple(
        t for t in (username, password, *device_tokens) if t and isinstance(t, str)
    )

    # Sanitize config entry metadata explicitly
    stored_devices = entry.data.get("devices", [])
    sanitized_entry_devices = [
        {
            "device_id": _anonymize_id(d.get("device_id", "")),
            "device_name": f"iGuardStove {_anonymize_id(d.get('device_id', ''))}",
        }
        for d in stored_devices
    ]

    config_entry_data = {
        "entry_id": entry.entry_id,
        "domain": entry.domain,
        "version": entry.version,
        "title": f"iGuardStove ({_anonymize_id(entry.title)})",
        "data": {
            CONF_USERNAME: "**REDACTED**",
            CONF_PASSWORD: "**REDACTED**",
            "devices": sanitized_entry_devices,
        },
        "options": async_redact_data(dict(entry.options), TO_REDACT),
    }

    devices_data: dict[str, Any] = {}
    errors_data: dict[str, Any] = {}

    if coordinator.data:
        for did, dev_dict in coordinator.data.devices.items():
            anon_id = _anonymize_id(did)
            dev_copy = dict(dev_dict)
            dev_copy["device_id"] = anon_id
            dev_copy["device_name"] = f"iGuardStove {anon_id}"
            devices_data[anon_id] = _sanitize_nested(dev_copy, sensitive_tokens)

        for did, err in coordinator.data.errors.items():
            anon_id = _anonymize_id(did)
            errors_data[anon_id] = _sanitize_nested(str(err), sensitive_tokens)

    diagnostics_data: dict[str, Any] = {
        "config_entry": config_entry_data,
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
