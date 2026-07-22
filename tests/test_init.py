"""Tests for the iGuardStove integration setup and teardown lifecycle."""

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.iguardstove.client import (
    CannotConnect,
    IGuardStoveException,
    InvalidAuth,
)
from custom_components.iguardstove.const import DOMAIN

MOCK_DEVICES = [{"device_id": "AABBCCDD1234", "device_name": "Guest House Stove"}]

MOCK_DEVICE_DATA = {
    "AABBCCDD1234": {
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
}


def _make_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
            "devices": MOCK_DEVICES,
        },
    )


async def test_setup_and_unload_entry(hass: HomeAssistant) -> None:
    """Test a clean setup followed by a clean unload."""
    entry = _make_entry()
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
            return_value=MOCK_DEVICE_DATA["AABBCCDD1234"],
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not None
    assert entry.runtime_data.coordinator is not None
    assert entry.runtime_data.client is not None

    coordinator = entry.runtime_data.coordinator
    assert coordinator is not None

    # Unload
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_entry_login_invalid_auth(hass: HomeAssistant) -> None:
    """Test that login InvalidAuth during setup leads to SETUP_ERROR (auth failure)."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.iguardstove.client.IGuardStoveClient.async_login",
        side_effect=InvalidAuth("Bad credentials"),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_setup_entry_login_cannot_connect(hass: HomeAssistant) -> None:
    """Test that login CannotConnect during setup leads to SETUP_RETRY."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.iguardstove.client.IGuardStoveClient.async_login",
        side_effect=CannotConnect("Timeout"),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_entry_live_discovery_invalid_auth(hass: HomeAssistant) -> None:
    """Test setup with live discovery raises ConfigEntryAuthFailed on InvalidAuth."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
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
            side_effect=InvalidAuth("Revoked"),
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_setup_entry_live_discovery_cannot_connect(hass: HomeAssistant) -> None:
    """Test setup with live discovery raises ConfigEntryNotReady on CannotConnect."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
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
            side_effect=CannotConnect("Network failure"),
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_entry_coordinator_invalid_auth(hass: HomeAssistant) -> None:
    """Test that coordinator InvalidAuth leads to ConfigEntryAuthFailed and SETUP_ERROR."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            side_effect=InvalidAuth("Session revoked"),
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_setup_entry_coordinator_cannot_connect(hass: HomeAssistant) -> None:
    """Test that coordinator CannotConnect on first refresh leads to SETUP_RETRY."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            side_effect=CannotConnect("Connection error"),
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_entry_no_devices(hass: HomeAssistant) -> None:
    """Test that setup returns False (SETUP_ERROR) when no devices are found."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
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
            return_value=[],
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
