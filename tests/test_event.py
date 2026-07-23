"""Tests for iGuardStove event entity platform and deduplication."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.iguardstove.const import DOMAIN
from custom_components.iguardstove.event import make_event_fingerprint
from custom_components.iguardstove.models import StoveEvent, StoveEventType

pytestmark = pytest.mark.enable_socket


@pytest.mark.asyncio
async def test_event_entity_creation_and_initial_seeding(hass: HomeAssistant) -> None:
    """Test that event entity is created per stove and seeds initial events without firing."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [{"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}],
        },
    )
    entry.add_to_hass(hass)

    mock_tz = ZoneInfo("UTC")
    event_1 = StoveEvent(
        occurred_at=datetime(2026, 7, 22, 9, 47, tzinfo=mock_tz),
        event_type=StoveEventType.ACTIVITY_SEEN,
        raw_label="Activity Seen",
    )

    device_data = {
        "device_id": "AABBCCDD1234",
        "device_name": "Kitchen Stove",
        "status": "Stove Off",
        "today_events": (event_1,),
        "events_error": None,
    }

    captured_events: list = []

    @callback
    def _handle_event(evt):
        captured_events.append(evt)

    hass.bus.async_listen("state_changed", _handle_event)

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=[
                {"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}
            ],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=device_data,
        ) as mock_get_data,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Check entity existence
        state = hass.states.get("event.kitchen_stove_activity")
        assert state is not None

        # Verify no extra HTTP request during setup pass
        assert mock_get_data.call_count == 1


@pytest.mark.asyncio
async def test_event_entity_fires_new_events_oldest_first(
    hass: HomeAssistant,
) -> None:
    """Test that new events on subsequent updates fire exactly once, oldest-first."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [{"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}],
        },
    )
    entry.add_to_hass(hass)

    mock_tz = ZoneInfo("UTC")
    initial_event = StoveEvent(
        occurred_at=datetime(2026, 7, 22, 7, 0, tzinfo=mock_tz),
        event_type=StoveEventType.NIGHT_LOCK_OFF,
        raw_label="Night Lock OFF",
    )

    data_pass_1 = {
        "device_id": "AABBCCDD1234",
        "device_name": "Kitchen Stove",
        "status": "Stove Off",
        "today_events": (initial_event,),
        "events_error": None,
    }

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=[
                {"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}
            ],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=data_pass_1,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator = entry.runtime_data.coordinator

        # Pass 2: portal has 2 new events (table is newest-first: 9:50 AM then 9:47 AM)
        new_event_1 = StoveEvent(
            occurred_at=datetime(2026, 7, 22, 9, 47, tzinfo=mock_tz),
            event_type=StoveEventType.ACTIVITY_SEEN,
            raw_label="Activity Seen",
        )
        new_event_2 = StoveEvent(
            occurred_at=datetime(2026, 7, 22, 9, 50, tzinfo=mock_tz),
            event_type=StoveEventType.STOVE_ON,
            raw_label="Stove Turned ON",
        )

        data_pass_2 = {
            "device_id": "AABBCCDD1234",
            "device_name": "Kitchen Stove",
            "status": "Stove On",
            "today_events": (new_event_2, new_event_1, initial_event),
            "events_error": None,
        }

        fired_events: list[tuple[str, str]] = []

        entity = hass.data["entity_components"]["event"].get_entity(
            "event.kitchen_stove_activity"
        )
        assert entity is not None

        original_trigger = entity._trigger_event

        def _spy_trigger(event_type: str, event_data: dict):
            fired_events.append((event_type, event_data["occurred_at"]))
            original_trigger(event_type, event_data)

        entity._trigger_event = _spy_trigger

        with patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=data_pass_2,
        ):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

        # Should fire oldest first: 9:47 AM then 9:50 AM
        assert len(fired_events) == 2
        assert fired_events[0] == (
            "activity_seen",
            datetime(2026, 7, 22, 9, 47, tzinfo=mock_tz).isoformat(),
        )
        assert fired_events[1] == (
            "stove_on",
            datetime(2026, 7, 22, 9, 50, tzinfo=mock_tz).isoformat(),
        )

        # Pass 3: refresh with identical data -> no new events fired
        fired_events.clear()
        with patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=data_pass_2,
        ):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

        assert len(fired_events) == 0


@pytest.mark.asyncio
async def test_same_minute_duplicate_events(hass: HomeAssistant) -> None:
    """Test that two identical same-minute events can both fire once."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [{"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}],
        },
    )
    entry.add_to_hass(hass)

    mock_tz = ZoneInfo("UTC")
    data_pass_1 = {
        "device_id": "AABBCCDD1234",
        "device_name": "Kitchen Stove",
        "status": "Stove Off",
        "today_events": (),
        "events_error": None,
    }

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=[
                {"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}
            ],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=data_pass_1,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator = entry.runtime_data.coordinator
        entity = hass.data["entity_components"]["event"].get_entity(
            "event.kitchen_stove_activity"
        )

        fired_events: list[str] = []

        def _spy_trigger(event_type: str, event_data: dict):
            fired_events.append(event_type)

        entity._trigger_event = _spy_trigger

        # Two identical events in same minute
        dup_event_0 = StoveEvent(
            occurred_at=datetime(2026, 7, 22, 9, 47, tzinfo=mock_tz),
            event_type=StoveEventType.ACTIVITY_SEEN,
            raw_label="Activity Seen",
            duplicate_ordinal=0,
        )
        dup_event_1 = StoveEvent(
            occurred_at=datetime(2026, 7, 22, 9, 47, tzinfo=mock_tz),
            event_type=StoveEventType.ACTIVITY_SEEN,
            raw_label="Activity Seen",
            duplicate_ordinal=1,
        )

        data_pass_2 = {
            "device_id": "AABBCCDD1234",
            "device_name": "Kitchen Stove",
            "status": "Stove Off",
            "today_events": (dup_event_0, dup_event_1),
            "events_error": None,
        }

        with patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=data_pass_2,
        ):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

        assert len(fired_events) == 2
        assert fired_events == ["activity_seen", "activity_seen"]


@pytest.mark.asyncio
async def test_unknown_events_fire_with_raw_label(hass: HomeAssistant) -> None:
    """Test that unknown events fire with event_type='unknown' and raw_label attribute."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [{"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}],
        },
    )
    entry.add_to_hass(hass)

    mock_tz = ZoneInfo("UTC")
    data_pass_1 = {
        "device_id": "AABBCCDD1234",
        "device_name": "Kitchen Stove",
        "status": "Stove Off",
        "today_events": (),
        "events_error": None,
    }

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=[
                {"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}
            ],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=data_pass_1,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator = entry.runtime_data.coordinator
        entity = hass.data["entity_components"]["event"].get_entity(
            "event.kitchen_stove_activity"
        )

        fired_data: list[tuple[str, dict]] = []

        def _spy_trigger(event_type: str, event_data: dict):
            fired_data.append((event_type, event_data))

        entity._trigger_event = _spy_trigger

        unknown_evt = StoveEvent(
            occurred_at=datetime(2026, 7, 22, 10, 15, tzinfo=mock_tz),
            event_type=StoveEventType.UNKNOWN,
            raw_label="Rare Custom Alert",
        )

        data_pass_2 = {
            "device_id": "AABBCCDD1234",
            "device_name": "Kitchen Stove",
            "status": "Stove Off",
            "today_events": (unknown_evt,),
            "events_error": None,
        }

        with patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=data_pass_2,
        ):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

        assert len(fired_data) == 1
        assert fired_data[0][0] == "unknown"
        assert fired_data[0][1]["raw_label"] == "Rare Custom Alert"


@pytest.mark.asyncio
async def test_multi_device_independent_seen_state(hass: HomeAssistant) -> None:
    """Test that multi-device setups keep independent seen event state."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [
                {"device_id": "DEV1", "device_name": "Stove 1"},
                {"device_id": "DEV2", "device_name": "Stove 2"},
            ],
        },
    )
    entry.add_to_hass(hass)

    mock_tz = ZoneInfo("UTC")
    event_dev1 = StoveEvent(
        occurred_at=datetime(2026, 7, 22, 9, 0, tzinfo=mock_tz),
        event_type=StoveEventType.ACTIVITY_SEEN,
        raw_label="Activity Seen",
    )

    def _get_data(dev_id, *args, **kwargs):
        if dev_id == "DEV1":
            return {
                "device_id": "DEV1",
                "device_name": "Stove 1",
                "status": "Stove Off",
                "today_events": (event_dev1,),
                "events_error": None,
            }
        return {
            "device_id": "DEV2",
            "device_name": "Stove 2",
            "status": "Stove Off",
            "today_events": (),
            "events_error": None,
        }

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=[
                {"device_id": "DEV1", "device_name": "Stove 1"},
                {"device_id": "DEV2", "device_name": "Stove 2"},
            ],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            side_effect=_get_data,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity_1 = hass.data["entity_components"]["event"].get_entity(
            "event.stove_1_activity"
        )
        entity_2 = hass.data["entity_components"]["event"].get_entity(
            "event.stove_2_activity"
        )

        assert entity_1 is not None
        assert entity_2 is not None

        # Pass 2: DEV2 receives the same event timing & label as DEV1 had
        fired_2: list[str] = []
        entity_2._trigger_event = lambda et, ed: fired_2.append(et)

        def _get_data_pass_2(dev_id, *args, **kwargs):
            return {
                "device_id": dev_id,
                "device_name": f"Stove {dev_id[-1]}",
                "status": "Stove Off",
                "today_events": (event_dev1,),
                "events_error": None,
            }

        coordinator = entry.runtime_data.coordinator
        with patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            side_effect=_get_data_pass_2,
        ):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

        # DEV2 fires because DEV1's seen state is independent
        assert len(fired_2) == 1
        assert fired_2[0] == "activity_seen"


@pytest.mark.asyncio
async def test_reloading_integration_does_not_replay_persisted_events(
    hass: HomeAssistant,
) -> None:
    """Test that reloading integration with persisted storage does not replay events."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [{"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}],
        },
    )
    entry.add_to_hass(hass)

    mock_tz = ZoneInfo("UTC")
    event_1 = StoveEvent(
        occurred_at=datetime(2026, 7, 22, 9, 47, tzinfo=mock_tz),
        event_type=StoveEventType.ACTIVITY_SEEN,
        raw_label="Activity Seen",
    )
    fp = make_event_fingerprint("AABBCCDD1234", event_1)

    mock_store_data = {"version": 1, "seen_events": {"AABBCCDD1234": [fp]}}

    device_data = {
        "device_id": "AABBCCDD1234",
        "device_name": "Kitchen Stove",
        "status": "Stove Off",
        "today_events": (event_1,),
        "events_error": None,
    }

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=[
                {"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}
            ],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=device_data,
        ),
        patch(
            "homeassistant.helpers.storage.Store.async_load",
            return_value=mock_store_data,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity = hass.data["entity_components"]["event"].get_entity(
            "event.kitchen_stove_activity"
        )
        assert entity is not None

        fired_events: list[str] = []
        entity._trigger_event = lambda et, ed: fired_events.append(et)

        coordinator = entry.runtime_data.coordinator
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # No events replayed because stored fingerprint was loaded!
        assert len(fired_events) == 0


@pytest.mark.asyncio
async def test_event_pruning_and_day_rotation(hass: HomeAssistant) -> None:
    """Test pruning of fingerprints older than 48 hours."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [{"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}],
        },
    )
    entry.add_to_hass(hass)

    now = dt_util.now()

    old_dt = now - timedelta(days=3)
    old_event = StoveEvent(
        occurred_at=old_dt,
        event_type=StoveEventType.ACTIVITY_SEEN,
        raw_label="Activity Seen",
    )
    old_fp = make_event_fingerprint("AABBCCDD1234", old_event)

    new_event = StoveEvent(
        occurred_at=now - timedelta(hours=1),
        event_type=StoveEventType.STOVE_ON,
        raw_label="Stove Turned ON",
    )
    new_fp = make_event_fingerprint("AABBCCDD1234", new_event)

    mock_store_data = {
        "version": 1,
        "seen_events": {"AABBCCDD1234": [old_fp, new_fp]},
    }

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=[
                {"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}
            ],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value={
                "device_id": "AABBCCDD1234",
                "device_name": "Kitchen Stove",
                "status": "Stove Off",
                "today_events": (new_event,),
                "events_error": None,
            },
        ),
        patch(
            "homeassistant.helpers.storage.Store.async_load",
            return_value=mock_store_data,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity = hass.data["entity_components"]["event"].get_entity(
            "event.kitchen_stove_activity"
        )
        assert entity is not None

        # Trigger pruning
        entity._prune_fingerprints()

        # Old fingerprint pruned, new fingerprint retained
        assert old_fp not in entity._seen_fingerprints
        assert new_fp in entity._seen_fingerprints


@pytest.mark.asyncio
async def test_event_store_load_error_and_save_error(hass: HomeAssistant) -> None:
    """Test handling of store load and save errors."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [{"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}],
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
                {"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}
            ],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value={
                "device_id": "AABBCCDD1234",
                "device_name": "Kitchen Stove",
                "status": "Stove Off",
                "today_events": (),
                "events_error": None,
            },
        ),
        patch(
            "homeassistant.helpers.storage.Store.async_load",
            side_effect=OSError("Read error"),
        ),
        patch(
            "homeassistant.helpers.storage.Store.async_save",
            side_effect=OSError("Write error"),
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity = hass.data["entity_components"]["event"].get_entity(
            "event.kitchen_stove_activity"
        )
        assert entity is not None
        assert entity.available is True

        # Test save error resilience via StoreManager
        entity._store_manager.update_seen("AABBCCDD1234", {"test_fp"})


@pytest.mark.asyncio
async def test_event_entity_availability_on_events_error(
    hass: HomeAssistant,
) -> None:
    """Test entity availability behavior when events_error is present or data is missing."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [{"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}],
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
                {"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}
            ],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value={
                "device_id": "AABBCCDD1234",
                "device_name": "Kitchen Stove",
                "status": "Stove Off",
                "today_events": (),
                "events_error": "Today's Events section missing",
            },
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity = hass.data["entity_components"]["event"].get_entity(
            "event.kitchen_stove_activity"
        )
        assert entity is not None
        assert entity.available is False


@pytest.mark.asyncio
async def test_event_dynamic_device_added(hass: HomeAssistant) -> None:
    """Test that dispatcher signal dynamically adds new event entity."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [{"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}],
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
                {"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}
            ],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value={
                "device_id": "AABBCCDD1234",
                "device_name": "Kitchen Stove",
                "status": "Stove Off",
            },
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        from homeassistant.helpers import entity_registry as er
        from homeassistant.helpers.dispatcher import async_dispatcher_send

        async_dispatcher_send(
            hass,
            f"{DOMAIN}_{entry.entry_id}_new_device",
            ["NEWEVENTDEV"],
        )
        await hass.async_block_till_done()

        registry = er.async_get(hass)
        assert (
            registry.async_get_entity_id("event", DOMAIN, "NEWEVENTDEV_activity")
            is not None
        )


@pytest.mark.asyncio
async def test_restart_seeding_with_persisted_storage(hass: HomeAssistant) -> None:
    """Test that current-day portal rows are seeded on first coordinator snapshot even when store has old data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [{"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}],
        },
    )
    entry.add_to_hass(hass)

    mock_tz = ZoneInfo("UTC")
    today_event = StoveEvent(
        occurred_at=datetime(2026, 7, 22, 10, 0, tzinfo=mock_tz),
        event_type=StoveEventType.STOVE_ON,
        raw_label="Stove Turned ON",
    )

    old_fp = "AABBCCDD1234|2026-07-21T08:00:00+00:00|stove turned off|0"

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=[
                {"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}
            ],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value={
                "device_id": "AABBCCDD1234",
                "device_name": "Kitchen Stove",
                "status": "Stove On",
                "today_events": (today_event,),
                "events_error": None,
            },
        ),
        patch(
            "homeassistant.helpers.storage.Store.async_load",
            return_value={"version": 1, "seen_events": {"AABBCCDD1234": [old_fp]}},
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity = hass.data["entity_components"]["event"].get_entity(
            "event.kitchen_stove_activity"
        )
        assert entity is not None

        # Today's event should be in seen_fingerprints, without having emitted an event
        today_fp = make_event_fingerprint("AABBCCDD1234", today_event)
        assert today_fp in entity._seen_fingerprints
        assert old_fp in entity._seen_fingerprints


@pytest.mark.asyncio
async def test_deterministic_fingerprint_pruning(hass: HomeAssistant) -> None:
    """Test that pruning deterministically retains the newest 500 records."""
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
            return_value=[{"device_id": "DEV1", "device_name": "DEV1"}],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value={
                "device_id": "DEV1",
                "device_name": "DEV1",
                "status": "Stove Off",
                "today_events": (),
            },
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity = hass.data["entity_components"]["event"].get_entity(
            "event.dev1_activity"
        )
        assert entity is not None

        now = dt_util.now()
        fps = set()
        # Generate 600 fingerprints over recent hours
        for i in range(600):
            dt = now - timedelta(minutes=i)
            fps.add(f"DEV1|{dt.isoformat()}|label|{i}")

        entity._seen_fingerprints = fps
        entity._prune_fingerprints()

        assert len(entity._seen_fingerprints) == 500
        # Oldest fingerprint (i=599) should have been pruned out
        oldest_dt = now - timedelta(minutes=599)
        oldest_fp = f"DEV1|{oldest_dt.isoformat()}|label|599"
        assert oldest_fp not in entity._seen_fingerprints


@pytest.mark.asyncio
async def test_event_store_manager_filters_non_string_records(
    hass: HomeAssistant,
) -> None:
    """Test that EventStoreManager filters out non-string records on load."""
    from custom_components.iguardstove.event import EventStoreManager

    mock_store = MagicMock()
    mock_store.async_load = AsyncMock(
        return_value={
            "version": 1,
            "seen_events": {
                "DEV1": ["valid_fp_1", 123, None, {"bad": "data"}],
                12345: ["ignored_dev_key"],
            },
        }
    )

    manager = EventStoreManager(mock_store)
    await manager.async_load()

    assert manager.get_seen("DEV1") == {"valid_fp_1"}


@pytest.mark.asyncio
async def test_prune_fingerprints_handles_naive_timestamps_and_non_strings(
    hass: HomeAssistant,
) -> None:
    """Test that _prune_fingerprints safely handles naive timestamp strings and non-string elements."""
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
            return_value=[{"device_id": "DEV1", "device_name": "DEV1"}],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value={
                "device_id": "DEV1",
                "device_name": "DEV1",
                "status": "Stove Off",
                "today_events": (),
            },
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity = hass.data["entity_components"]["event"].get_entity(
            "event.dev1_activity"
        )
        assert entity is not None

        # Populate with naive timestamp string, unparseable string, and non-string values
        recent_naive_fp = "DEV1|2026-07-22T12:00:00|recent naive label|0"
        old_naive_fp = "DEV1|2020-01-01T00:00:00|old naive label|0"
        bad_format_fp = "invalid_fingerprint_without_pipe"
        non_string_val = 99999

        entity._seen_fingerprints = {
            recent_naive_fp,
            old_naive_fp,
            bad_format_fp,
            non_string_val,  # type: ignore[arg-type]
        }

        entity._prune_fingerprints()

        # Non-string values and old naive timestamps pruned; recent naive timestamp & unparseable format retained safely
        assert recent_naive_fp in entity._seen_fingerprints
        assert bad_format_fp in entity._seen_fingerprints
        assert old_naive_fp not in entity._seen_fingerprints
        assert non_string_val not in entity._seen_fingerprints


@pytest.mark.asyncio
async def test_event_suppression_when_disabled_in_options(hass: HomeAssistant) -> None:
    """Test that event triggers are suppressed when activity event collection option is disabled."""
    from custom_components.iguardstove.const import CONF_ENABLE_ACTIVITY_EVENTS

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [{"device_id": "DEV1", "device_name": "Stove 1"}],
        },
        options={
            CONF_ENABLE_ACTIVITY_EVENTS: False,
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
            return_value=[{"device_id": "DEV1", "device_name": "Stove 1"}],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value={
                "device_id": "DEV1",
                "device_name": "Stove 1",
                "status": "Stove Off",
                "today_events": (),
            },
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity = hass.data["entity_components"]["event"].get_entity(
            "event.stove_1_activity"
        )
        assert entity is not None

        mock_trigger = MagicMock()
        entity._trigger_event = mock_trigger

        now = dt_util.now()
        new_event = StoveEvent(
            occurred_at=now,
            event_type=StoveEventType.STOVE_ON,
            raw_label="Stove Turned On",
        )

        coordinator = entry.runtime_data.coordinator
        coordinator.data.devices["DEV1"] = {
            "device_id": "DEV1",
            "device_name": "Stove 1",
            "status": "Stove On",
            "today_events": (new_event,),
        }
        entity._handle_coordinator_update()

        # Event trigger suppressed because option is False
        mock_trigger.assert_not_called()
