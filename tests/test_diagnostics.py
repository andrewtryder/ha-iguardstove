"""Tests for iGuardStove diagnostics."""

import hashlib
import json
from unittest.mock import patch

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.iguardstove.const import BASE_URL, DOMAIN
from custom_components.iguardstove.diagnostics import async_get_config_entry_diagnostics

MOCK_DEVICES = [{"device_id": "AABBCCDD1234", "device_name": "Guest House Stove"}]
MOCK_DEVICE_DATA = {
    "device_id": "AABBCCDD1234",
    "device_name": "Guest House Stove",
    "status": "Stove Off",
    "status_raw": "iGuardStove is off at https://manage.iguardfire.com",
    "is_locked": False,
    "last_check_in": "20 minutes ago",
    "temperature": 72.0,
    "temperature_unit": "°F",
    "fires_prevented": 3,
}


async def test_diagnostics_redaction(hass: HomeAssistant) -> None:
    """Test that diagnostics output redacts sensitive username, password, URLs, and hardware/room identifiers."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="iGuardStove (sensitive_user@example.com)",
        data={
            CONF_USERNAME: "sensitive_user@example.com",
            CONF_PASSWORD: "super_secret_password",
            "devices": MOCK_DEVICES,
        },
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=MOCK_DEVICES,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=MOCK_DEVICE_DATA,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag is not None
    assert "config_entry" in diag
    assert "coordinator" in diag

    entry_data = diag["config_entry"]["data"]
    assert entry_data[CONF_USERNAME] == "**REDACTED**"
    assert entry_data[CONF_PASSWORD] == "**REDACTED**"

    expected_anon_id = hashlib.sha256(b"AABBCCDD1234").hexdigest()[:8]
    assert diag["coordinator"]["device_ids"] == [expected_anon_id]

    dev_data = diag["coordinator"]["data"]["devices"][expected_anon_id]
    assert dev_data["device_id"] == expected_anon_id
    assert dev_data["device_name"] == f"iGuardStove {expected_anon_id}"
    assert dev_data["status"] == "Stove Off"
    assert dev_data["temperature"] == 72.0

    # Recursive serialization assertion
    diag_str = json.dumps(diag)
    assert "sensitive_user@example.com" not in diag_str
    assert "super_secret_password" not in diag_str
    assert "AABBCCDD1234" not in diag_str
    assert "Guest House Stove" not in diag_str
    assert BASE_URL not in diag_str


async def test_diagnostics_error_strings_fully_redacted(hass: HomeAssistant) -> None:
    """Coordinator error strings must scrub device IDs, names, credentials, and portal URLs."""
    from custom_components.iguardstove.models import CoordinatorData

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="iGuardStove (sensitive_user@example.com)",
        data={
            CONF_USERNAME: "sensitive_user@example.com",
            CONF_PASSWORD: "super_secret_password",
            "devices": MOCK_DEVICES,
        },
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=MOCK_DEVICES,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=MOCK_DEVICE_DATA,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    device_url = f"{BASE_URL}/devices/AABBCCDD1234/"
    entry.runtime_data.coordinator.data = CoordinatorData(
        devices={
            "AABBCCDD1234": {
                **MOCK_DEVICE_DATA,
                "status": "Stove Off",
            }
        },
        errors={
            "AABBCCDD1234": (
                "CannotConnect: HTTP request to "
                f"{device_url} returned status 503 for Guest House Stove "
                "(user=sensitive_user@example.com password=super_secret_password)"
            ),
        },
    )

    diag = await async_get_config_entry_diagnostics(hass, entry)
    expected_anon_id = hashlib.sha256(b"AABBCCDD1234").hexdigest()[:8]
    error_text = diag["coordinator"]["data"]["errors"][expected_anon_id]
    assert "HTTP request" in error_text
    assert "returned status 503" in error_text

    diag_str = json.dumps(diag)
    assert "AABBCCDD1234" not in diag_str
    assert "Guest House Stove" not in diag_str
    assert "sensitive_user@example.com" not in diag_str
    assert "super_secret_password" not in diag_str
    assert device_url not in diag_str
    assert BASE_URL not in diag_str


def test_sanitize_nested_helper() -> None:
    """Test _sanitize_nested helper with lists, dicts, tuples, sets, and non-string primitives."""
    from custom_components.iguardstove.diagnostics import _sanitize_nested

    raw_data = {
        "username": "secret_user",
        "nested_list": ["secret_user", 123, True, None],
        "nested_dict": {
            "sub_key": "secret_user",
            "url": "https://manage.iguardfire.com/devices/DEV123/",
        },
        "nested_tuple": ("secret_user", "safe_val"),
        "other": "hello secret_user world",
    }
    sanitized = _sanitize_nested(
        raw_data, ("secret_user", "https://manage.iguardfire.com/devices/DEV123/")
    )
    assert sanitized["username"] == "**REDACTED**"
    assert sanitized["nested_list"][0].startswith("[REDACTED_")
    assert sanitized["nested_list"][1] == 123
    assert sanitized["nested_list"][2] is True
    assert sanitized["nested_list"][3] is None
    assert sanitized["nested_dict"]["sub_key"].startswith("[REDACTED_")
    assert sanitized["nested_dict"]["url"].startswith("[REDACTED_")
    assert sanitized["nested_tuple"][0].startswith("[REDACTED_")
    assert sanitized["nested_tuple"][1] == "safe_val"
