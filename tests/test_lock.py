"""Tests for iGuardStove lock entity."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.iguardstove.client import CannotConnect, InvalidAuth
from custom_components.iguardstove.const import CONF_ALLOW_REMOTE_UNLOCK, DOMAIN

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
    hass: HomeAssistant,
    device_data: dict | None,
    options: dict | None = None,
) -> MockConfigEntry:
    """Helper: set up the integration with fixed device data and enable disabled lock entity."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
            "devices": MOCK_DEVICES,
        },
        options=options or {},
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


async def test_unlock_action_disabled_by_default_raises(hass: HomeAssistant) -> None:
    """Test calling unlock service raises remote_unlock_disabled when option is False."""
    await _setup_integration(hass, DEVICE_DATA_LOCKED)

    with pytest.raises(HomeAssistantError) as exc_info:
        await hass.services.async_call(
            "lock",
            "unlock",
            {"entity_id": "lock.guest_house_stove_stove_lock"},
            blocking=True,
        )

    assert exc_info.value.translation_key == "remote_unlock_disabled"


async def test_unlock_action_allowed_when_option_enabled(hass: HomeAssistant) -> None:
    """Test calling unlock service succeeds when CONF_ALLOW_REMOTE_UNLOCK is True."""
    await _setup_integration(
        hass, DEVICE_DATA_LOCKED, options={CONF_ALLOW_REMOTE_UNLOCK: True}
    )

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


async def test_lock_entity_unavailable_when_indeterminate(hass: HomeAssistant) -> None:
    """Test lock entity becomes unavailable when lock state is None (indeterminate)."""
    device_data_indeterminate = {
        "device_id": "AABBCCDD1234",
        "device_name": "Guest House Stove",
        "status": "Lost Communication",
        "is_locked": None,
    }
    await _setup_integration(hass, device_data_indeterminate)
    state = hass.states.get("lock.guest_house_stove_stove_lock")
    assert state is not None
    assert state.state == "unavailable"


async def test_lock_action_cannot_connect_raises_homeassistant_error(
    hass: HomeAssistant,
) -> None:
    """Test that CannotConnect during lock action raises HomeAssistantError."""
    await _setup_integration(hass, DEVICE_DATA_UNLOCKED)

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_set_lock_state",
            side_effect=CannotConnect("Offline"),
        ),
        pytest.raises(HomeAssistantError) as exc_info,
    ):
        await hass.services.async_call(
            "lock",
            "lock",
            {"entity_id": "lock.guest_house_stove_stove_lock"},
            blocking=True,
        )

    assert exc_info.value.translation_key == "lock_command_failed"


async def test_lock_action_invalid_auth_raises_homeassistant_error(
    hass: HomeAssistant,
) -> None:
    """Test that InvalidAuth during lock action raises HomeAssistantError."""
    await _setup_integration(hass, DEVICE_DATA_UNLOCKED)

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_set_lock_state",
            side_effect=InvalidAuth("Bad auth"),
        ),
        pytest.raises(HomeAssistantError) as exc_info,
    ):
        await hass.services.async_call(
            "lock",
            "lock",
            {"entity_id": "lock.guest_house_stove_stove_lock"},
            blocking=True,
        )

    assert exc_info.value.translation_key == "authentication_failed"


async def test_unlock_action_cannot_connect_raises_homeassistant_error(
    hass: HomeAssistant,
) -> None:
    """Test that CannotConnect during unlock action raises HomeAssistantError when allowed."""
    await _setup_integration(
        hass, DEVICE_DATA_LOCKED, options={CONF_ALLOW_REMOTE_UNLOCK: True}
    )

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_set_lock_state",
            side_effect=CannotConnect("Offline"),
        ),
        pytest.raises(HomeAssistantError) as exc_info,
    ):
        await hass.services.async_call(
            "lock",
            "unlock",
            {"entity_id": "lock.guest_house_stove_stove_lock"},
            blocking=True,
        )

    assert exc_info.value.translation_key == "lock_command_failed"


async def test_unlock_action_invalid_auth_raises_homeassistant_error(
    hass: HomeAssistant,
) -> None:
    """Test that InvalidAuth during unlock action raises HomeAssistantError when allowed."""
    await _setup_integration(
        hass, DEVICE_DATA_LOCKED, options={CONF_ALLOW_REMOTE_UNLOCK: True}
    )

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_set_lock_state",
            side_effect=InvalidAuth("Bad auth"),
        ),
        pytest.raises(HomeAssistantError) as exc_info,
    ):
        await hass.services.async_call(
            "lock",
            "unlock",
            {"entity_id": "lock.guest_house_stove_stove_lock"},
            blocking=True,
        )

    assert exc_info.value.translation_key == "authentication_failed"


async def test_lock_dynamic_device_added(hass: HomeAssistant) -> None:
    """Test that dispatcher signal dynamically adds new lock entity."""
    entry = await _setup_integration(hass, DEVICE_DATA_UNLOCKED)
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    async_dispatcher_send(
        hass,
        f"{DOMAIN}_{entry.entry_id}_new_device",
        ["NEWLOCKDEV"],
    )
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id("lock", DOMAIN, "NEWLOCKDEV_stove_lock")
        is not None
    )
