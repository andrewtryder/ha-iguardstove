"""Tests for iGuardStove lockout binary sensor."""

from unittest.mock import patch

from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.iguardstove.const import DOMAIN

MOCK_DEVICES = [{"device_id": "AABBCCDD1234", "device_name": "Guest House Stove"}]

DEVICE_DATA_LOCKOUT_OFF = {
    "device_id": "AABBCCDD1234",
    "device_name": "Guest House Stove",
    "status": "Stove Off",
    "status_raw": "iGuardStove is off",
    "is_master_locked": False,
    "is_lockout_active": False,
    "last_check_in": "20 minutes ago",
    "temperature": 72.0,
    "temperature_unit": "°F",
    "fires_prevented": 3,
}

DEVICE_DATA_LOCKOUT_ON = {
    "device_id": "AABBCCDD1234",
    "device_name": "Guest House Stove",
    "status": "Night Lock",
    "status_raw": "iGuardStove is LOCKED OUT for the night",
    "is_master_locked": False,
    "is_lockout_active": True,
    "last_check_in": "5 minutes ago",
    "temperature": 70.0,
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
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=MOCK_DEVICES,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=device_data,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return entry


async def test_lockout_binary_sensor_off(hass: HomeAssistant) -> None:
    """Test lockout binary sensor reports off when not locked out."""
    await _setup_integration(hass, DEVICE_DATA_LOCKOUT_OFF)
    state = hass.states.get("binary_sensor.guest_house_stove_stove_lockout")
    assert state is not None
    assert state.state == "off"
    assert state.attributes.get("master_locked") is False
    assert state.attributes.get("status") == "Stove Off"


async def test_lockout_binary_sensor_on(hass: HomeAssistant) -> None:
    """Test lockout binary sensor reports on during Night Lock with Master Lock off."""
    await _setup_integration(hass, DEVICE_DATA_LOCKOUT_ON)
    state = hass.states.get("binary_sensor.guest_house_stove_stove_lockout")
    assert state is not None
    assert state.state == STATE_ON
    assert state.attributes.get("master_locked") is False
    assert state.attributes.get("status") == "Night Lock"


async def test_lockout_binary_sensor_unavailable_when_indeterminate(
    hass: HomeAssistant,
) -> None:
    """Test lockout sensor is unavailable when lockout state is None."""
    device_data = {
        "device_id": "AABBCCDD1234",
        "device_name": "Guest House Stove",
        "status": "Lost Communication",
        "is_master_locked": None,
        "is_lockout_active": None,
    }
    await _setup_integration(hass, device_data)
    state = hass.states.get("binary_sensor.guest_house_stove_stove_lockout")
    assert state is not None
    assert state.state == STATE_UNAVAILABLE


async def test_lockout_binary_sensor_enabled_by_default(hass: HomeAssistant) -> None:
    """Stove lockout binary sensor is enabled by default."""
    await _setup_integration(hass, DEVICE_DATA_LOCKOUT_OFF)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, "AABBCCDD1234_stove_lockout"
    )
    assert entity_id is not None
    entity = registry.async_get(entity_id)
    assert entity is not None
    assert entity.disabled is False


async def test_lockout_dynamic_device_added(hass: HomeAssistant) -> None:
    """Test that dispatcher signal dynamically adds new lockout binary sensor."""
    entry = await _setup_integration(hass, DEVICE_DATA_LOCKOUT_OFF)
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    async_dispatcher_send(
        hass,
        f"{DOMAIN}_{entry.entry_id}_new_device",
        ["NEWLOCKOUTDEV"],
    )
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id(
            "binary_sensor", DOMAIN, "NEWLOCKOUTDEV_stove_lockout"
        )
        is not None
    )
