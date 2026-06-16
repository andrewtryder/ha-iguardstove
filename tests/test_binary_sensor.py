"""Tests for iGuardStove binary sensor entities."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.iguardstove.const import DOMAIN

MOCK_DEVICES = [{"device_id": "AABBCCDD1234", "device_name": "Guest House Stove"}]

DEVICE_DATA_UNLOCKED = {
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

DEVICE_DATA_LOCKED = {
    "device_id": "AABBCCDD1234",
    "device_name": "Guest House Stove",
    "status": "Night Lock",
    "status_raw": "iGuardStove is LOCKED OUT for the night",
    "is_locked": True,
    "last_check_in": "5 minutes ago",
    "temperature": 70.0,
    "temperature_unit": "°F",
    "fires_prevented": 3,
}

DEVICE_DATA_STOVE_ON = {
    "device_id": "AABBCCDD1234",
    "device_name": "Guest House Stove",
    "status": "Stove On",
    "status_raw": "iGuardStove is on",
    "is_locked": False,
    "last_check_in": "2 minutes ago",
    "temperature": 75.0,
    "temperature_unit": "°F",
    "fires_prevented": 3,
}


async def _setup_integration(hass: HomeAssistant, device_data: dict) -> MockConfigEntry:
    """Helper: set up the integration with fixed device data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
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
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=device_data,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return entry


# ---------------------------------------------------------------------------
# Lock binary sensor
# ---------------------------------------------------------------------------


async def test_locked_binary_sensor_unlocked(hass: HomeAssistant) -> None:
    """Test locked binary sensor is OFF when stove is unlocked."""
    await _setup_integration(hass, DEVICE_DATA_UNLOCKED)
    state = hass.states.get("binary_sensor.guest_house_stove_locked")
    assert state is not None
    assert state.state == "off"


async def test_locked_binary_sensor_locked(hass: HomeAssistant) -> None:
    """Test locked binary sensor is ON when stove is locked."""
    await _setup_integration(hass, DEVICE_DATA_LOCKED)
    state = hass.states.get("binary_sensor.guest_house_stove_locked")
    assert state is not None
    assert state.state == "on"
