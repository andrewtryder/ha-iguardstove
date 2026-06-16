"""Tests for iGuardStove lock entity."""

from unittest.mock import AsyncMock, patch

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


async def test_lock_action_calls_toggle(hass: HomeAssistant) -> None:
    """Test that calling lock service invokes async_toggle_lock."""
    await _setup_integration(hass, DEVICE_DATA_UNLOCKED)

    with patch(
        "custom_components.iguardstove.client.IGuardStoveClient.async_toggle_lock",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_toggle:
        await hass.services.async_call(
            "lock",
            "lock",
            {"entity_id": "lock.guest_house_stove_stove_lock"},
            blocking=True,
        )
        await hass.async_block_till_done()

    mock_toggle.assert_called_once_with("AABBCCDD1234")


async def test_unlock_action_calls_toggle(hass: HomeAssistant) -> None:
    """Test that calling unlock service invokes async_toggle_lock."""
    await _setup_integration(hass, DEVICE_DATA_LOCKED)

    with patch(
        "custom_components.iguardstove.client.IGuardStoveClient.async_toggle_lock",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_toggle:
        await hass.services.async_call(
            "lock",
            "unlock",
            {"entity_id": "lock.guest_house_stove_stove_lock"},
            blocking=True,
        )
        await hass.async_block_till_done()

    mock_toggle.assert_called_once_with("AABBCCDD1234")


async def test_lock_skips_toggle_when_already_locked(hass: HomeAssistant) -> None:
    """Test that calling lock when already locked skips the toggle."""
    await _setup_integration(hass, DEVICE_DATA_LOCKED)

    with patch(
        "custom_components.iguardstove.client.IGuardStoveClient.async_toggle_lock",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_toggle:
        await hass.services.async_call(
            "lock",
            "lock",
            {"entity_id": "lock.guest_house_stove_stove_lock"},
            blocking=True,
        )
        await hass.async_block_till_done()

    mock_toggle.assert_not_called()


async def test_unlock_skips_toggle_when_already_unlocked(hass: HomeAssistant) -> None:
    """Test that calling unlock when already unlocked skips the toggle."""
    await _setup_integration(hass, DEVICE_DATA_UNLOCKED)

    with patch(
        "custom_components.iguardstove.client.IGuardStoveClient.async_toggle_lock",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_toggle:
        await hass.services.async_call(
            "lock",
            "unlock",
            {"entity_id": "lock.guest_house_stove_stove_lock"},
            blocking=True,
        )
        await hass.async_block_till_done()

    mock_toggle.assert_not_called()
