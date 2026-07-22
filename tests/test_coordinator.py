"""Tests for iGuardStove DataUpdateCoordinator."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.iguardstove.client import (
    CannotConnect,
    IGuardStoveClient,
)
from custom_components.iguardstove.const import DOMAIN
from custom_components.iguardstove.coordinator import IGuardStoveDataUpdateCoordinator

DEVICE_DATA_1 = {"device_id": "DEV1", "status": "Stove Off"}
DEVICE_DATA_2 = {"device_id": "DEV2", "status": "Stove On"}


@pytest.mark.asyncio
async def test_coordinator_per_device_error_isolation(hass: HomeAssistant) -> None:
    """Test that a failure on one device retains previous data without failing entire update."""
    client = MagicMock(spec=IGuardStoveClient)
    client.async_get_devices = AsyncMock(
        return_value=[{"device_id": "DEV1"}, {"device_id": "DEV2"}]
    )
    client.async_get_device_data = AsyncMock()

    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, ["DEV1", "DEV2"])
    coordinator.data = {"DEV1": DEVICE_DATA_1, "DEV2": DEVICE_DATA_2}

    # DEV1 succeeds with new data, DEV2 raises CannotConnect
    new_data_1 = {"device_id": "DEV1", "status": "Night Lock"}
    client.async_get_device_data.side_effect = lambda dev_id, *args, **kwargs: (
        new_data_1
        if dev_id == "DEV1"
        else (_ for _ in ()).throw(CannotConnect("Network drop"))
    )

    result = await coordinator._async_update_data()
    assert result["DEV1"]["status"] == "Night Lock"
    assert result["DEV2"]["status"] == "Stove On"  # Retained previous data


@pytest.mark.asyncio
async def test_coordinator_all_devices_fail(hass: HomeAssistant) -> None:
    """Test that UpdateFailed is raised when all devices fail to update."""
    client = MagicMock(spec=IGuardStoveClient)
    client.async_get_devices = AsyncMock(return_value=[{"device_id": "DEV1"}])
    client.async_get_device_data = AsyncMock(side_effect=CannotConnect("Offline"))

    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, ["DEV1"])
    coordinator.data = None

    with pytest.raises(
        UpdateFailed, match="Failed to fetch data for all iGuardStove devices"
    ):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_coordinator_dynamic_device_discovery(hass: HomeAssistant) -> None:
    """Test dynamic device discovery pass adds new devices."""
    client = MagicMock(spec=IGuardStoveClient)
    client.async_get_devices = AsyncMock(
        return_value=[{"device_id": "DEV1"}, {"device_id": "DEV2"}]
    )
    client.async_get_device_data = AsyncMock(
        side_effect=lambda did, *args, **kwargs: {
            "device_id": did,
            "status": "Stove Off",
        }
    )

    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, ["DEV1"])
    entry = MockConfigEntry(domain=DOMAIN, data={})
    coordinator.config_entry = entry

    result = await coordinator._async_update_data()
    assert "DEV2" in coordinator.device_ids
    assert "DEV2" in result


@pytest.mark.asyncio
async def test_dynamic_device_discovery_integration(hass: HomeAssistant) -> None:
    """Test that newly discovered devices dynamically create new entities."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [{"device_id": "DEV1", "device_name": "DEV1"}],
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
            return_value=[
                {"device_id": "DEV1", "device_name": "DEV1"},
                {"device_id": "DEV2", "device_name": "DEV2"},
            ],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            side_effect=lambda did, *args, **kwargs: {
                "device_id": did,
                "device_name": did,
                "status": "Stove Off",
            },
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert hass.states.get("sensor.dev1_status") is not None

        coordinator = entry.runtime_data.coordinator
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        from homeassistant.helpers import entity_registry as er

        assert hass.states.get("sensor.dev2_status") is not None
        registry = er.async_get(hass)
        assert (
            registry.async_get_entity_id("lock", DOMAIN, "DEV2_stove_lock") is not None
        )
