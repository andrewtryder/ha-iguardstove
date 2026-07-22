"""Tests for iGuardStove lock entity."""

from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
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


async def _setup_integration(
    hass: HomeAssistant, device_data: dict | None
) -> MockConfigEntry:
    """Helper: set up the integration with fixed device data and enable disabled lock entity."""
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

        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            "lock", DOMAIN, "AABBCCDD1234_stove_lock"
        )
        if entity_id:
            registry.async_update_entity(entity_id, disabled_by=None)
            await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()

    return entry


async def test_lock_entity_is_unlocked(hass: HomeAssistant) -> None:
    """Test lock entity reports unlocked state correctly."""
    await _setup_integration(hass, DEVICE_DATA_UNLOCKED)
    state = hass.states.get("lock.guest_house_stove_stove_lock")
    assert state is not None
    assert state.state == "unlocked"


async def test_lock_entity_is_locked(hass: HomeAssistant) -> None:
    """Test lock entity reports locked state correctly."""
    await _setup_integration(hass, DEVICE_DATA_LOCKED)
    state = hass.states.get("lock.guest_house_stove_stove_lock")
    assert state is not None
    assert state.state == "locked"


async def test_lock_action_calls_async_set_lock_state(hass: HomeAssistant) -> None:
    """Test that calling lock service invokes async_set_lock_state with target_locked=True."""
    await _setup_integration(hass, DEVICE_DATA_UNLOCKED)

    with patch(
        "custom_components.iguardstove.client.IGuardStoveClient.async_set_lock_state",
        new_callable=AsyncMock,
        return_value=None,
    ) as mock_set_state:
        await hass.services.async_call(
            "lock",
            "lock",
            {"entity_id": "lock.guest_house_stove_stove_lock"},
            blocking=True,
        )
        await hass.async_block_till_done()

    mock_set_state.assert_called_once_with("AABBCCDD1234", True)


async def test_unlock_action_calls_async_set_lock_state(hass: HomeAssistant) -> None:
    """Test that calling unlock service invokes async_set_lock_state with target_locked=False."""
    await _setup_integration(hass, DEVICE_DATA_LOCKED)

    with patch(
        "custom_components.iguardstove.client.IGuardStoveClient.async_set_lock_state",
        new_callable=AsyncMock,
        return_value=None,
    ) as mock_set_state:
        await hass.services.async_call(
            "lock",
            "unlock",
            {"entity_id": "lock.guest_house_stove_stove_lock"},
            blocking=True,
        )
        await hass.async_block_till_done()

    mock_set_state.assert_called_once_with("AABBCCDD1234", False)


async def test_lock_entity_missing_data(hass: HomeAssistant) -> None:
    """Test lock entity reports unknown state when device data is missing or incomplete."""
    await _setup_integration(hass, None)
    state = hass.states.get("lock.iguardstove_stove_lock")
    assert state is not None
    assert state.state == "unknown"


async def test_lock_entity_missing_is_locked_key(hass: HomeAssistant) -> None:
    """Test lock entity returns unknown state when is_locked key is missing."""
    device_data_no_lock = {
        "device_id": "AABBCCDD1234",
        "device_name": "Guest House Stove",
        "status": "Stove Off",
        "status_raw": "iGuardStove is off",
    }
    await _setup_integration(hass, device_data_no_lock)
    state = hass.states.get("lock.guest_house_stove_stove_lock")
    assert state is not None
    assert state.state == "unknown"
