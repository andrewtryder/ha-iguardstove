"""Tests for the iGuardStove integration setup and teardown lifecycle."""

from __future__ import annotations

from unittest.mock import patch

import pytest
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
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=MOCK_DEVICE_DATA["AABBCCDD1234"],
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert DOMAIN in hass.data
    assert entry.entry_id in hass.data[DOMAIN]

    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    assert coordinator is not None

    # Unload
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert entry.entry_id not in hass.data.get(DOMAIN, {})


@pytest.mark.parametrize(
    ("exc", "label"),
    [
        (CannotConnect("timeout"), "CannotConnect"),
        (InvalidAuth("bad token"), "InvalidAuth"),
        (IGuardStoveException("generic error"), "IGuardStoveException"),
    ],
)
async def test_setup_entry_coordinator_failure(
    hass: HomeAssistant,
    exc: Exception,
    label: str,
) -> None:
    """Test that coordinator errors on first refresh lead to SETUP_RETRY."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            side_effect=exc,
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
            # No 'devices' key — forces live discovery
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
            return_value=[],  # empty list → no device IDs
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
