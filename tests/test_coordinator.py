"""Tests for iGuardStove DataUpdateCoordinator."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.iguardstove.client import (
    CannotConnect,
    IGuardStoveClient,
    InvalidAuth,
)
from custom_components.iguardstove.const import DOMAIN
from custom_components.iguardstove.coordinator import IGuardStoveDataUpdateCoordinator
from custom_components.iguardstove.models import CoordinatorData
from custom_components.iguardstove.sensor import SENSOR_DESCRIPTIONS, IGuardStoveSensor
from custom_components.iguardstove.types import DeviceData

DEVICE_DATA_1: DeviceData = {
    "device_id": "DEV1",
    "device_name": "Stove 1",
    "status": "Stove Off",
}
DEVICE_DATA_2: DeviceData = {
    "device_id": "DEV2",
    "device_name": "Stove 2",
    "status": "Stove On",
}


@pytest.mark.asyncio
async def test_coordinator_per_device_error_isolation(hass: HomeAssistant) -> None:
    """Test that a failure on one device retains previous data without failing entire update."""
    client = MagicMock(spec=IGuardStoveClient)
    client.async_get_devices = AsyncMock(
        return_value=[{"device_id": "DEV1"}, {"device_id": "DEV2"}]
    )
    client.async_get_device_data = AsyncMock()

    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, ["DEV1", "DEV2"])
    coordinator.data = CoordinatorData(
        devices={"DEV1": DEVICE_DATA_1, "DEV2": DEVICE_DATA_2}, errors={}
    )

    # DEV1 succeeds with new data, DEV2 raises CannotConnect
    new_data_1 = {"device_id": "DEV1", "status": "Night Lock"}
    client.async_get_device_data.side_effect = lambda dev_id, *args, **kwargs: (
        new_data_1
        if dev_id == "DEV1"
        else (_ for _ in ()).throw(CannotConnect("Network drop"))
    )

    result = await coordinator._async_update_data()
    assert result.devices["DEV1"]["status"] == "Night Lock"
    assert result.devices["DEV2"]["status"] == "Stove On"  # Retained previous data
    assert "DEV2" in result.errors
    assert "DEV1" not in result.errors


@pytest.mark.asyncio
async def test_coordinator_per_device_availability(hass: HomeAssistant) -> None:
    """Test that entities become unavailable when an individual device fails."""
    client = MagicMock(spec=IGuardStoveClient)
    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, ["DEV1", "DEV2"])

    sensor1 = IGuardStoveSensor(coordinator, "DEV1", SENSOR_DESCRIPTIONS[0])
    sensor2 = IGuardStoveSensor(coordinator, "DEV2", SENSOR_DESCRIPTIONS[0])

    coordinator.data = CoordinatorData(
        devices={"DEV1": DEVICE_DATA_1, "DEV2": DEVICE_DATA_2},
        errors={"DEV2": "CannotConnect: Network drop"},
    )

    assert sensor1.available is True
    assert sensor2.available is False


@pytest.mark.asyncio
async def test_coordinator_all_devices_fail(hass: HomeAssistant) -> None:
    """Test that UpdateFailed is raised when all devices fail to update."""
    client = MagicMock(spec=IGuardStoveClient)
    client.async_get_devices = AsyncMock(return_value=[{"device_id": "DEV1"}])
    client.async_get_device_data = AsyncMock(side_effect=CannotConnect("Offline"))

    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, ["DEV1"])
    coordinator.data = None  # type: ignore[assignment]

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
    assert "DEV2" in result.devices


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


@pytest.mark.asyncio
async def test_coordinator_discovery_interval_throttling(hass: HomeAssistant) -> None:
    """Test that discovery runs at setup but is skipped on subsequent polls within 6 hours."""
    client = MagicMock(spec=IGuardStoveClient)
    client.async_get_devices = AsyncMock(return_value=[{"device_id": "DEV1"}])
    client.async_get_device_data = AsyncMock(
        return_value={"device_id": "DEV1", "status": "Stove Off"}
    )

    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, ["DEV1"])
    entry = MockConfigEntry(domain=DOMAIN, data={})
    coordinator.config_entry = entry

    # First update: performs discovery
    await coordinator._async_update_data()
    assert client.async_get_devices.call_count == 1

    # Second update (e.g. 60s poll): skips discovery
    await coordinator._async_update_data()
    assert client.async_get_devices.call_count == 1


@pytest.mark.asyncio
async def test_coordinator_surfaces_unexpected_exception(hass: HomeAssistant) -> None:
    """Test that unexpected non-client exceptions surface to caller instead of marking device unavailable."""
    client = MagicMock(spec=IGuardStoveClient)
    client.async_get_devices = AsyncMock(return_value=[{"device_id": "DEV1"}])
    client.async_get_device_data = AsyncMock(
        side_effect=ZeroDivisionError("Unexpected math error")
    )

    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, ["DEV1"])

    with pytest.raises(ZeroDivisionError, match="Unexpected math error"):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_coordinator_failed_discovery_retries_on_next_poll(
    hass: HomeAssistant,
) -> None:
    """Test that a failed discovery pass tracks fail count and retries after backoff."""
    client = MagicMock(spec=IGuardStoveClient)
    client.async_get_devices = AsyncMock(
        side_effect=[CannotConnect("Dashboard unavailable"), [{"device_id": "DEV1"}]]
    )
    client.async_get_device_data = AsyncMock(
        return_value={"device_id": "DEV1", "status": "Stove Off"}
    )

    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, ["DEV1"])

    # First update: discovery fails, _last_successful_discovery remains None
    await coordinator._async_update_data()
    assert client.async_get_devices.call_count == 1
    assert coordinator._last_successful_discovery is None
    assert coordinator._discovery_fail_count == 1

    # Second update (e.g. after backoff window): retries discovery and succeeds!
    with patch.object(coordinator, "_should_attempt_discovery", return_value=True):
        await coordinator._async_update_data()
        assert client.async_get_devices.call_count == 2
        assert coordinator._last_successful_discovery is not None
        assert coordinator._discovery_fail_count == 0


@pytest.mark.asyncio
async def test_coordinator_stale_device_reconciliation(hass: HomeAssistant) -> None:
    """Test that devices removed from portal dashboard are reconciled after repeated confirmation."""
    from homeassistant.util import dt as dt_util

    client = MagicMock(spec=IGuardStoveClient)
    # Dashboard now only returns DEV1 (DEV2 was removed from account)
    client.async_get_devices = AsyncMock(return_value=[{"device_id": "DEV1"}])
    client.async_get_device_data = AsyncMock(
        side_effect=lambda did, *args, **kwargs: {
            "device_id": did,
            "status": "Stove Off",
        }
    )

    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, ["DEV1", "DEV2"])
    coordinator.data = CoordinatorData(
        devices={
            "DEV1": {
                "device_id": "DEV1",
                "device_name": "Stove 1",
                "status": "Stove Off",
            },
            "DEV2": {
                "device_id": "DEV2",
                "device_name": "Stove 2",
                "status": "Stove Off",
            },
        },
        errors={},
    )

    now = dt_util.now()
    # Pass 1: DEV2 missing, count becomes 1, DEV2 retained for safety
    await coordinator._async_discover_devices(now)
    assert "DEV2" in coordinator.device_ids

    # Pass 2: DEV2 missing again, confirmed removed
    await coordinator._async_discover_devices(now)
    assert "DEV2" not in coordinator.device_ids
    assert coordinator.device_ids == ["DEV1"]


@pytest.mark.asyncio
async def test_coordinator_empty_discovery_retains_devices(hass: HomeAssistant) -> None:
    """Test that a single empty discovery pass retains existing registered devices."""
    from homeassistant.util import dt as dt_util

    client = MagicMock(spec=IGuardStoveClient)
    client.async_get_devices = AsyncMock(return_value=[])

    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, ["DEV1", "DEV2"])
    now = dt_util.now()
    success = await coordinator._async_discover_devices(now)
    assert success is True
    assert coordinator.device_ids == ["DEV1", "DEV2"]
    assert coordinator._empty_discovery_count == 1


@pytest.mark.asyncio
async def test_coordinator_validated_empty_removes_final_device(
    hass: HomeAssistant,
) -> None:
    """Test three consecutive validated empty discoveries remove the final device."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.util import dt as dt_util

    client = MagicMock(spec=IGuardStoveClient)
    client.async_get_devices = AsyncMock(return_value=[])

    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, ["DEV1"])
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"devices": [{"device_id": "DEV1", "device_name": "Stove 1"}]},
    )
    entry.add_to_hass(hass)
    coordinator.config_entry = entry
    entry.runtime_data = MagicMock(event_store=None)

    dev_reg = dr.async_get(hass)
    device_entry = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "DEV1")},
        name="Stove 1",
    )

    now = dt_util.now()
    await coordinator._async_discover_devices(now)
    assert coordinator.device_ids == ["DEV1"]
    await coordinator._async_discover_devices(now)
    assert coordinator.device_ids == ["DEV1"]
    await coordinator._async_discover_devices(now)
    assert coordinator.device_ids == []
    assert entry.data.get("devices") == []
    assert device_entry.id not in {
        d.id for d in dev_reg.devices.values() if entry.entry_id in d.config_entries
    }


@pytest.mark.asyncio
async def test_coordinator_parse_error_resets_empty_counter(
    hass: HomeAssistant,
) -> None:
    """Test DashboardParseError does not count toward empty-discovery removal."""
    from homeassistant.util import dt as dt_util

    from custom_components.iguardstove.exceptions import DashboardParseError

    client = MagicMock(spec=IGuardStoveClient)
    client.async_get_devices = AsyncMock(
        side_effect=[
            [],
            [],
            DashboardParseError("malformed"),
            [],
        ]
    )

    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, ["DEV1"])
    now = dt_util.now()
    await coordinator._async_discover_devices(now)
    await coordinator._async_discover_devices(now)
    assert coordinator._empty_discovery_count == 2
    assert await coordinator._async_discover_devices(now) is False
    assert coordinator._empty_discovery_count == 0
    await coordinator._async_discover_devices(now)
    assert coordinator.device_ids == ["DEV1"]
    assert coordinator._empty_discovery_count == 1


@pytest.mark.asyncio
async def test_coordinator_exponential_backoff_progression(hass: HomeAssistant) -> None:
    """Test dynamic discovery exponential backoff delay calculation and reset."""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    client = MagicMock(spec=IGuardStoveClient)
    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, ["DEV1"])
    now = dt_util.now()

    coordinator._last_successful_discovery = now - timedelta(hours=7)
    coordinator._last_discovery_attempt = now

    # Initial state: 0 failures, should attempt discovery
    assert coordinator._should_attempt_discovery(now) is True

    # 1 failure: backoff is 5 minutes (5 * 2^0)
    coordinator._discovery_fail_count = 1
    assert coordinator._should_attempt_discovery(now + timedelta(minutes=4)) is False
    assert coordinator._should_attempt_discovery(now + timedelta(minutes=5)) is True

    # 2 failures: backoff is 10 minutes (5 * 2^1)
    coordinator._discovery_fail_count = 2
    assert coordinator._should_attempt_discovery(now + timedelta(minutes=9)) is False
    assert coordinator._should_attempt_discovery(now + timedelta(minutes=10)) is True

    # 3 failures: backoff is 20 minutes (5 * 2^2)
    coordinator._discovery_fail_count = 3
    assert coordinator._should_attempt_discovery(now + timedelta(minutes=19)) is False
    assert coordinator._should_attempt_discovery(now + timedelta(minutes=20)) is True

    # 10 failures: max backoff capped at 360 minutes (6 hours)
    coordinator._discovery_fail_count = 10
    assert coordinator._should_attempt_discovery(now + timedelta(minutes=359)) is False
    assert coordinator._should_attempt_discovery(now + timedelta(minutes=360)) is True


@pytest.mark.asyncio
async def test_coordinator_stale_device_reconciliation_including_final_device(
    hass: HomeAssistant,
) -> None:
    """Test device registry cleanup when devices (and the final device) are removed from portal."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.util import dt as dt_util

    client = MagicMock(spec=IGuardStoveClient)
    # Portal now returns only DEV2 (DEV1 removed)
    client.async_get_devices = AsyncMock(return_value=[{"device_id": "DEV2"}])

    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, ["DEV1", "DEV2"])
    dev_reg = dr.async_get(hass)
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    coordinator.config_entry = entry

    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "DEV1")},
        name="Stove 1",
    )
    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "DEV2")},
        name="Stove 2",
    )

    now = dt_util.now()
    # Pass 1: DEV1 missing, count becomes 1
    await coordinator._async_discover_devices(now)
    assert "DEV1" in coordinator.device_ids

    # Pass 2: DEV1 missing again; this config entry is detached (device may be deleted)
    await coordinator._async_discover_devices(now)
    assert "DEV1" not in coordinator.device_ids
    remaining_dev1 = dev_reg.async_get_device(identifiers={(DOMAIN, "DEV1")})
    assert remaining_dev1 is None or entry.entry_id not in remaining_dev1.config_entries
    assert dev_reg.async_get_device(identifiers={(DOMAIN, "DEV2")}) is not None


@pytest.mark.asyncio
async def test_coordinator_auth_failure_raises_config_entry_auth_failed(
    hass: HomeAssistant,
) -> None:
    """Test that InvalidAuth in coordinator raises ConfigEntryAuthFailed to halt polling and trigger reauth."""
    client = MagicMock(spec=IGuardStoveClient)
    client.async_get_device_data = AsyncMock(
        side_effect=InvalidAuth("Invalid credentials")
    )

    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, ["DEV1"])

    with pytest.raises(ConfigEntryAuthFailed, match="Authentication error for DEV1"):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_async_prepare_device_removal_refuses_active(hass: HomeAssistant) -> None:
    """Refuse manual removal while the device is still actively reporting."""
    client = MagicMock(spec=IGuardStoveClient)
    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, ["DEV1"])
    coordinator.data = CoordinatorData(
        devices={
            "DEV1": {
                "device_id": "DEV1",
                "device_name": "Stove 1",
                "status": "Stove Off",
            }
        },
        errors={},
    )
    assert coordinator.async_prepare_device_removal("DEV1") is False
    assert coordinator.device_ids == ["DEV1"]


@pytest.mark.asyncio
async def test_async_prepare_device_removal_cleans_unavailable(
    hass: HomeAssistant,
) -> None:
    """Allow manual removal and prune local state for an unavailable device."""
    from homeassistant.helpers import device_registry as dr

    client = MagicMock(spec=IGuardStoveClient)
    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, ["DEV1", "DEV2"])
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "devices": [
                {"device_id": "DEV1", "device_name": "Stove 1"},
                {"device_id": "DEV2", "device_name": "Stove 2"},
            ]
        },
    )
    entry.add_to_hass(hass)
    coordinator.config_entry = entry
    coordinator._unavailable_devices.add("DEV1")
    coordinator.data = CoordinatorData(
        devices={
            "DEV1": {"device_id": "DEV1", "device_name": "Stove 1"},
            "DEV2": {"device_id": "DEV2", "device_name": "Stove 2"},
        },
        errors={"DEV1": "offline"},
    )

    store = MagicMock()
    store.clear_device = MagicMock()
    entry.runtime_data = MagicMock(event_store=store)

    dev_reg = dr.async_get(hass)
    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "DEV1")},
        name="Stove 1",
    )

    assert coordinator.async_prepare_device_removal("DEV1") is True
    assert "DEV1" not in coordinator.device_ids
    assert store.clear_device.called
    assert all(d["device_id"] != "DEV1" for d in entry.data["devices"])


@pytest.mark.asyncio
async def test_async_rediscover_now_propagates_invalid_auth(
    hass: HomeAssistant,
) -> None:
    """One-shot rediscovery must raise InvalidAuth for options-flow mapping."""
    client = MagicMock(spec=IGuardStoveClient)
    client.async_get_devices = AsyncMock(side_effect=InvalidAuth("revoked"))
    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, ["DEV1"])
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    coordinator.config_entry = entry

    with pytest.raises(InvalidAuth, match="revoked"):
        await coordinator.async_rediscover_now()


@pytest.mark.asyncio
async def test_async_rediscover_now_propagates_cannot_connect(
    hass: HomeAssistant,
) -> None:
    """One-shot rediscovery must raise CannotConnect for options-flow mapping."""
    client = MagicMock(spec=IGuardStoveClient)
    client.async_get_devices = AsyncMock(side_effect=CannotConnect("offline"))
    coordinator = IGuardStoveDataUpdateCoordinator(hass, client, ["DEV1"])
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    coordinator.config_entry = entry

    with pytest.raises(CannotConnect, match="offline"):
        await coordinator.async_rediscover_now()
