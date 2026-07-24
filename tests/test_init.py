"""Tests for the iGuardStove integration setup and teardown lifecycle."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.iguardstove.client import (
    CannotConnect,
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

    client = entry.runtime_data.client
    with patch.object(client, "close", new_callable=AsyncMock) as mock_close:
        # Unload
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.NOT_LOADED
        mock_close.assert_called_once()


async def test_remove_config_entry_device(hass: HomeAssistant) -> None:
    """Test async_remove_config_entry_device returns True."""
    from custom_components.iguardstove import async_remove_config_entry_device

    entry = _make_entry()
    entry.add_to_hass(hass)
    assert await async_remove_config_entry_device(hass, entry, None) is True


async def test_setup_entry_login_invalid_auth(hass: HomeAssistant) -> None:
    """Test that login InvalidAuth during setup leads to SETUP_ERROR (auth failure)."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            side_effect=InvalidAuth("Bad credentials"),
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.close",
            new_callable=AsyncMock,
        ) as mock_close,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    mock_close.assert_awaited_once()


async def test_setup_entry_login_cannot_connect(hass: HomeAssistant) -> None:
    """Test that login CannotConnect during setup leads to SETUP_RETRY."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            side_effect=CannotConnect("Timeout"),
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.close",
            new_callable=AsyncMock,
        ) as mock_close,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    mock_close.assert_awaited_once()


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
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.close",
            new_callable=AsyncMock,
        ) as mock_close,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    mock_close.assert_awaited_once()


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
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.close",
            new_callable=AsyncMock,
        ) as mock_close,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    mock_close.assert_awaited_once()


async def test_setup_entry_live_discovery_dashboard_parse_error(
    hass: HomeAssistant,
) -> None:
    """Test setup with live discovery raises ConfigEntryNotReady on DashboardParseError."""
    from custom_components.iguardstove.exceptions import DashboardParseError

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
            side_effect=DashboardParseError("malformed dashboard"),
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.close",
            new_callable=AsyncMock,
        ) as mock_close,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    mock_close.assert_awaited_once()


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
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=MOCK_DEVICES,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            side_effect=InvalidAuth("Session revoked"),
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.close",
            new_callable=AsyncMock,
        ) as mock_close,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    mock_close.assert_awaited_once()


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
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=MOCK_DEVICES,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            side_effect=CannotConnect("Connection error"),
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.close",
            new_callable=AsyncMock,
        ) as mock_close,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    mock_close.assert_awaited_once()


async def test_setup_entry_unexpected_exception_closes_session(
    hass: HomeAssistant,
) -> None:
    """Unexpected setup failures must still close the owned client session."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            side_effect=RuntimeError("boom"),
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.close",
            new_callable=AsyncMock,
        ) as mock_close,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    mock_close.assert_awaited_once()


async def test_setup_entry_success_keeps_session_open(hass: HomeAssistant) -> None:
    """Successful setup must keep the session open until unload."""
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
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.close",
            new_callable=AsyncMock,
        ) as mock_close,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        mock_close.assert_not_called()

        client = entry.runtime_data.client
        with patch.object(client, "close", new_callable=AsyncMock) as unload_close:
            await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()
            unload_close.assert_awaited_once()


async def test_setup_entry_no_devices(hass: HomeAssistant) -> None:
    """Test that setup remains loaded when the portal has no devices."""
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

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.coordinator.device_ids == []


async def test_setup_reload_and_unload_session_cleanup(hass: HomeAssistant) -> None:
    """Test setup -> reload -> unload cycle cleans up aiohttp sessions properly."""
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
    first_client = entry.runtime_data.client

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
        patch.object(first_client, "close", new_callable=AsyncMock) as mock_close_1,
    ):
        # Reload
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    mock_close_1.assert_called_once()

    second_client = entry.runtime_data.client
    assert second_client is not first_client

    with patch.object(second_client, "close", new_callable=AsyncMock) as mock_close_2:
        # Unload
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    mock_close_2.assert_called_once()


async def test_async_migrate_entry(hass: HomeAssistant) -> None:
    """Test config entry migration for version 1 and unsupported future version."""
    from custom_components.iguardstove import async_migrate_entry

    entry_v1 = MockConfigEntry(domain=DOMAIN, version=1, data={})
    entry_v1.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry_v1) is True

    entry_future = MockConfigEntry(domain=DOMAIN, version=99, data={})
    entry_future.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry_future) is False


async def test_remove_config_entry_device_scenarios(hass: HomeAssistant) -> None:
    """Test removal of stale device entries including final device."""
    from homeassistant.helpers import device_registry as dr

    from custom_components.iguardstove import async_remove_config_entry_device

    entry = _make_entry()
    entry.add_to_hass(hass)

    dev_reg = dr.async_get(hass)
    device_entry = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "AABBCCDD1234")},
        name="Guest House Stove",
    )

    # Removing known device entry while unloaded refuses (active status unknown)
    assert await async_remove_config_entry_device(hass, entry, device_entry) is False

    # Removing with None device_entry returns True
    assert await async_remove_config_entry_device(hass, entry, None) is True


async def test_remove_active_device_refused(hass: HomeAssistant) -> None:
    """Loaded active devices must not be removable via the registry hook."""
    from homeassistant.helpers import device_registry as dr

    from custom_components.iguardstove import async_remove_config_entry_device

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
    coordinator = entry.runtime_data.coordinator
    assert "AABBCCDD1234" not in coordinator._unavailable_devices
    assert "AABBCCDD1234" not in coordinator.data.errors

    dev_reg = dr.async_get(hass)
    device_entry = dev_reg.async_get_device(identifiers={(DOMAIN, "AABBCCDD1234")})
    assert device_entry is not None
    assert await async_remove_config_entry_device(hass, entry, device_entry) is False
    assert any(d["device_id"] == "AABBCCDD1234" for d in entry.data["devices"])


async def test_remove_unavailable_device_cleans_persisted_state(
    hass: HomeAssistant,
) -> None:
    """Unavailable loaded devices may be removed and pruned from entry data."""
    from homeassistant.helpers import device_registry as dr

    from custom_components.iguardstove import async_remove_config_entry_device

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

    coordinator = entry.runtime_data.coordinator
    coordinator._unavailable_devices.add("AABBCCDD1234")
    coordinator.data.errors["AABBCCDD1234"] = "offline"
    store = MagicMock()
    store.clear_device = MagicMock()
    entry.runtime_data.event_store = store

    dev_reg = dr.async_get(hass)
    device_entry = dev_reg.async_get_device(identifiers={(DOMAIN, "AABBCCDD1234")})
    assert device_entry is not None
    assert await async_remove_config_entry_device(hass, entry, device_entry) is True
    assert "AABBCCDD1234" not in coordinator.device_ids
    assert all(d["device_id"] != "AABBCCDD1234" for d in entry.data["devices"])
    store.clear_device.assert_called_once_with("AABBCCDD1234")


async def test_remove_device_while_unloaded_is_refused(
    hass: HomeAssistant,
) -> None:
    """Unloaded removals are refused; persisted devices stay until status is known."""
    from homeassistant.helpers import device_registry as dr

    from custom_components.iguardstove import async_remove_config_entry_device

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
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED

    devices_before = list(entry.data.get("devices", []))
    dev_reg = dr.async_get(hass)
    device_entry = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "AABBCCDD1234")},
        name="Guest House Stove",
    )
    assert await async_remove_config_entry_device(hass, entry, device_entry) is False
    assert entry.data.get("devices") == devices_before

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
    assert "AABBCCDD1234" in entry.runtime_data.coordinator.device_ids
    assert any(d["device_id"] == "AABBCCDD1234" for d in entry.data["devices"])
