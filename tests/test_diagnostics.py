"""Tests for iGuardStove diagnostics."""

from unittest.mock import patch

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.iguardstove.const import DOMAIN
from custom_components.iguardstove.diagnostics import async_get_config_entry_diagnostics

MOCK_DEVICES = [{"device_id": "AABBCCDD1234", "device_name": "Guest House Stove"}]
MOCK_DEVICE_DATA = {
    "device_id": "AABBCCDD1234",
    "device_name": "Guest House Stove",
    "status": "Stove Off",
    "status_raw": "iGuardStove is off",
    "is_locked": False,
    "last_check_in": "20 minutes ago",
    "temperature": 72.0,
    "temperature_unit": "°F",
    "fires_prevented": 3,
}


async def test_diagnostics_redaction(hass: HomeAssistant) -> None:
    """Test that diagnostics output redacts sensitive username and password fields."""
    entry = MockConfigEntry(
        domain=DOMAIN,
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
    assert diag["coordinator"]["device_ids"] == ["AABBCCDD1234"]
